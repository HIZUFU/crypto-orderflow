import asyncio
import json
import logging
from datetime import timedelta
from time import monotonic

import websockets
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import Alert, utc_now
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
        self.latest: dict[str, dict[str, float]] = {}
        self.last_signal_at: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="market-data")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._stream_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market stream failed; reconnecting")
                await asyncio.sleep(self.settings.reconnect_delay_seconds)

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
                    self.engines[symbol].observe_trade(
                        TradeEvent(
                            timestamp_ms=int(trade["T"]),
                            price=float(trade["p"]),
                            quantity=float(trade["v"]),
                            side=trade["S"],
                        )
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
