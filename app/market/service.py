import asyncio
import json
import logging
from datetime import timedelta
from time import monotonic

import websockets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import Alert, PaperTrade, utc_now
from app.market.candles import CandleAggregator
from app.market.features import FeatureEngine, TradeEvent
from app.market.orderbook import LocalOrderBook
from app.strategy.orderflow import generate_signal

logger = logging.getLogger(__name__)


class MarketService:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.books = {symbol: LocalOrderBook() for symbol in settings.tracked_symbols}
        self.engines = {symbol: FeatureEngine(self.books[symbol]) for symbol in settings.tracked_symbols}
        self.candles = {symbol: CandleAggregator(symbol) for symbol in settings.tracked_symbols}
        self.latest: dict[str, dict[str, float]] = {}
        self.last_signal_at: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="market-data")
        if self.settings.enable_auto_close:
            self._monitor_task = asyncio.create_task(self._monitor_positions(), name="position-monitor")

    async def stop(self) -> None:
        self._stop.set()
        tasks = []
        if self._task:
            self._task.cancel()
            tasks.append(self._task)
        if self._monitor_task:
            self._monitor_task.cancel()
            tasks.append(self._monitor_task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._monitor_task = None

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
        args = []
        for symbol in self.settings.tracked_symbols:
            args.append(f"orderbook.{self.settings.orderbook_depth}.{symbol}")
            args.append(f"publicTrade.{symbol}")
        async with websockets.connect(self.settings.bybit_ws_url, ping_interval=20, ping_timeout=20) as socket:
            await socket.send(json.dumps({"op": "subscribe", "args": args}))
            async for raw_message in socket:
                if self._stop.is_set():
                    return
                await self._handle_message(json.loads(raw_message))

    async def _handle_message(self, message: dict) -> None:
        topic = message.get("topic", "")
        data = message.get("data") or {}
        if topic.startswith("orderbook."):
            symbol = data.get("s")
            if symbol not in self.books:
                return
            self.books[symbol].apply(
                message.get("type", "snapshot"),
                data.get("b", []),
                data.get("a", []),
                int(data.get("u", 0)),
                int(message.get("ts", 0)),
            )
            features = self.engines[symbol].calculate()
            if features is not None:
                self.latest[symbol] = features
                await self._maybe_alert(symbol, features)
        elif topic.startswith("publicTrade."):
            for trade in message.get("data", []):
                symbol = trade.get("s")
                if symbol in self.engines:
                    trade_event = TradeEvent(
                        timestamp_ms=int(trade["T"]),
                        price=float(trade["p"]),
                        quantity=float(trade["v"]),
                        side=trade["S"],
                    )
                    self.engines[symbol].observe_trade(trade_event)
                    
                    # Also feed to candle aggregator
                    if symbol in self.candles:
                        self.candles[symbol].add_trade(
                            timestamp_ms=trade_event.timestamp_ms,
                            price=trade_event.price,
                            volume=trade_event.quantity,
                        )

    async def _maybe_alert(self, symbol: str, features: dict[str, float]) -> None:
        now = monotonic()
        if now - self.last_signal_at.get(symbol, 0.0) < self.settings.signal_cooldown_seconds:
            return
        signal = generate_signal(symbol, features, self.settings.paper_notional_usdt, self.settings.paper_leverage)
        if signal is None:
            return
        self.last_signal_at[symbol] = now
        created = utc_now()
        async with self.session_factory() as session:
            session.add(
                Alert(
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
                )
            )
            await session.commit()
        logger.info("paper alert %s %s score=%.3f", symbol, signal.direction, signal.score)

    async def _monitor_positions(self) -> None:
        """Monitor open paper trades and close them if stop/target is hit."""
        while not self._stop.is_set():
            try:
                await self._check_positions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("position monitor error")
            
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.position_monitor_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def _check_positions(self) -> None:
        """Check open positions against current prices and close if needed."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.status == "open")
            )
            open_trades = list(result.scalars())
            
            if not open_trades:
                return
            
            for trade in open_trades:
                # Get current mid price from features
                features = self.latest.get(trade.symbol)
                if features is None:
                    continue
                
                current_price = features.get("mid_price")
                if current_price is None:
                    continue
                
                should_close = False
                exit_reason = None
                
                if trade.direction == "LONG":
                    if current_price <= trade.stop_loss:
                        should_close = True
                        exit_reason = "stop_loss"
                    elif current_price >= trade.take_profit:
                        should_close = True
                        exit_reason = "take_profit"
                elif trade.direction == "SHORT":
                    if current_price >= trade.stop_loss:
                        should_close = True
                        exit_reason = "stop_loss"
                    elif current_price <= trade.take_profit:
                        should_close = True
                        exit_reason = "take_profit"
                
                if should_close:
                    # Calculate PnL
                    gross = ((current_price - trade.entry_price) / trade.entry_price) * trade.notional
                    if trade.direction == "SHORT":
                        gross *= -1
                    
                    trade.fees = trade.notional * self.settings.paper_fee_rate * 2
                    trade.pnl = gross - trade.fees
                    trade.exit_price = current_price
                    trade.exit_reason = exit_reason
                    trade.closed_at = utc_now()
                    trade.status = "closed"
                    
                    logger.info(
                        "auto-closed %s %s at %.2f (%s), pnl=%.4f USDT",
                        trade.symbol,
                        trade.direction,
                        current_price,
                        exit_reason,
                        trade.pnl,
                    )
            
            await session.commit()
