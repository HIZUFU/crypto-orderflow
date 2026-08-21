import asyncio
import json
import logging
from datetime import timedelta
from time import monotonic

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import Alert, AlertOutcome, PaperTrade, utc_now
from app.exchanges import get_exchange
from app.market.candles import CandleAggregator
from app.market.features import FeatureEngine, TradeEvent
from app.market.orderbook import LocalOrderBook
from app.ml.filter import SignalFilter
from app.strategy.orderflow import generate_signal

logger = logging.getLogger(__name__)


class MarketService:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker) -> None:
        self.settings = settings
        self.session_factory = session_factory
        ws_url = settings.bybit_ws_url if settings.default_exchange == "bybit" else settings.binance_ws_url
        self.exchange = get_exchange(settings.default_exchange, ws_url=ws_url, depth=settings.orderbook_depth)
        self.books = {symbol: LocalOrderBook() for symbol in settings.tracked_symbols}
        self.engines = {symbol: FeatureEngine(self.books[symbol]) for symbol in settings.tracked_symbols}
        self.candles = {symbol: CandleAggregator(symbol) for symbol in settings.tracked_symbols}
        self.latest: dict[str, dict[str, float]] = {}
        self.last_signal_at: dict[str, float] = {}
        self.ml_filter: SignalFilter | None = None
        if settings.use_ml_filter:
            try:
                self.ml_filter = SignalFilter(settings.model_path)
                if self.ml_filter.model:
                    logger.info("CatBoost filter loaded from %s", settings.model_path)
                else:
                    logger.warning("ML filter enabled without a model; rule-only mode is active")
            except Exception:
                logger.exception("Could not load CatBoost filter")
        self._task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._outcome_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="market-data")
        if self.settings.enable_auto_close:
            self._monitor_task = asyncio.create_task(self._monitor_positions(), name="position-monitor")
        self._outcome_task = asyncio.create_task(self._monitor_alert_outcomes(), name="alert-outcome-monitor")

    async def stop(self) -> None:
        self._stop.set()
        tasks = [task for task in (self._task, self._monitor_task, self._outcome_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._task = self._monitor_task = self._outcome_task = None

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._stream_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market stream failed; reconnecting")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.reconnect_delay_seconds)
                except asyncio.TimeoutError:
                    pass

    async def _stream_once(self) -> None:
        async for update in self.exchange.subscribe(self.settings.tracked_symbols):
            if self._stop.is_set():
                return
            if hasattr(update, "bids"):
                symbol = update.symbol.upper()
                if symbol not in self.books:
                    continue
                self.books[symbol].apply(
                    "snapshot" if update.is_snapshot else "delta",
                    update.bids,
                    update.asks,
                    update.update_id,
                    update.timestamp_ms,
                )
                features = self.engines[symbol].calculate()
                if features is not None:
                    self.latest[symbol] = features
                    await self._maybe_alert(symbol, features)
            elif hasattr(update, "price"):
                symbol = update.symbol.upper()
                if symbol not in self.engines:
                    continue
                event = TradeEvent(update.timestamp_ms, update.price, update.quantity, update.side)
                self.engines[symbol].observe_trade(event)
                self.candles[symbol].add_trade(event.timestamp_ms, event.price, event.quantity)

    async def _maybe_alert(self, symbol: str, features: dict[str, float]) -> None:
        now = monotonic()
        if now - self.last_signal_at.get(symbol, 0.0) < self.settings.signal_cooldown_seconds:
            return
        signal = generate_signal(
            symbol,
            features,
            self.settings.paper_notional_usdt,
            self.settings.paper_leverage,
            self.settings.risk_value,
            self.settings.reward_risk_ratio,
        )
        if signal is None:
            return
        ml_probability = None
        ml_passed = False
        if self.ml_filter and self.ml_filter.model:
            ml_probability = self.ml_filter.predict_proba(features, signal.score)
            ml_passed = ml_probability >= self.settings.ml_threshold
            if not ml_passed:
                logger.debug("CatBoost rejected %s %s at %.3f", symbol, signal.direction, ml_probability)
                return
        self.last_signal_at[symbol] = now
        created = utc_now()
        async with self.session_factory() as session:
            session.add(Alert(
                created_at=created,
                expires_at=created + timedelta(seconds=self.settings.signal_ttl_seconds),
                symbol=signal.symbol,
                direction=signal.direction,
                entry_low=signal.entry_low,
                entry_high=signal.entry_high,
                reference_price=signal.reference_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                position_notional=self.settings.paper_notional_usdt,
                leverage=self.settings.paper_leverage,
                risk_amount=signal.risk_amount,
                score=signal.score,
                reason=signal.reason,
                features_json=json.dumps(signal.features),
                exchange=self.exchange.name,
                ml_probability=ml_probability,
                ml_passed_filter=ml_passed,
            ))
            await session.commit()
        logger.info("alert %s %s %s score=%.3f", self.exchange.name, symbol, signal.direction, signal.score)

    async def _monitor_positions(self) -> None:
        while not self._stop.is_set():
            try:
                await self._check_positions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("position monitor error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.position_monitor_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def _check_positions(self) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(PaperTrade).where(PaperTrade.status == "open"))
            trades = list(result.scalars())
            for trade in trades:
                features = self.latest.get(trade.symbol)
                current = features.get("mid_price") if features else None
                if current is None:
                    continue
                reason = None
                if trade.direction == "LONG":
                    reason = "stop_loss" if current <= trade.stop_loss else "take_profit" if current >= trade.take_profit else None
                else:
                    reason = "stop_loss" if current >= trade.stop_loss else "take_profit" if current <= trade.take_profit else None
                if reason:
                    gross = ((current - trade.entry_price) / trade.entry_price) * trade.notional
                    if trade.direction == "SHORT":
                        gross *= -1
                    trade.fees = trade.notional * self.settings.paper_fee_rate * 2
                    trade.pnl = gross - trade.fees
                    trade.exit_price = current
                    trade.exit_reason = reason
                    trade.closed_at = utc_now()
                    trade.status = "closed"
                    outcome_result = await session.execute(select(AlertOutcome).where(AlertOutcome.paper_trade_id == trade.id).order_by(desc(AlertOutcome.created_at)))
                    outcome = outcome_result.scalars().first()
                    if outcome:
                        outcome.outcome_type = reason
                        outcome.outcome_timestamp = trade.closed_at
                        outcome.price_at_outcome = current
                    logger.info("auto-closed trade %s: %s pnl=%.4f", trade.id, reason, trade.pnl)
            await session.commit()

    async def _monitor_alert_outcomes(self) -> None:
        while not self._stop.is_set():
            try:
                await self._check_expired_alerts()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("alert outcome monitor error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.outcome_monitor_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def _check_expired_alerts(self) -> None:
        now = utc_now()
        async with self.session_factory() as session:
            result = await session.execute(select(Alert).where(Alert.expires_at < now, Alert.outcome_type == "pending"))
            for alert in result.scalars():
                alert.outcome_type = "expired"
                current = (self.latest.get(alert.symbol) or {}).get("mid_price")
                hypothetical = None
                reached_target = None
                hit_stop = None
                if current is not None:
                    hypothetical = ((current - alert.reference_price) / alert.reference_price) * alert.position_notional
                    if alert.direction == "SHORT":
                        hypothetical *= -1
                    reached_target = current >= alert.take_profit if alert.direction == "LONG" else current <= alert.take_profit
                    hit_stop = current <= alert.stop_loss if alert.direction == "LONG" else current >= alert.stop_loss
                session.add(AlertOutcome(
                    alert_id=alert.id,
                    outcome_type="expired",
                    outcome_timestamp=now,
                    price_at_outcome=current,
                    hypothetical_pnl=hypothetical,
                    reached_target=reached_target,
                    hit_stop=hit_stop,
                    ml_probability=alert.ml_probability,
                    ml_passed_filter=alert.ml_passed_filter,
                ))
            await session.commit()
