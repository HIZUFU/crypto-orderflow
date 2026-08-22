"""Binance spot and USD-M futures public market data adapter."""
import asyncio
import json
import logging

import httpx
import websockets

from app.exchanges.base import Exchange, OrderBookUpdate, TradeUpdate

logger = logging.getLogger(__name__)


class BinanceExchange(Exchange):
    def __init__(
        self,
        ws_url: str = "wss://fstream.binance.com/stream",
        depth: int = 20,
        market_type: str = "linear",
    ) -> None:
        super().__init__("binance", ws_url)
        self.depth = depth
        self.market_type = market_type

    def _rest_url(self, symbol: str) -> str:
        if self.market_type == "linear":
            return f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol.upper()}&limit=1000"
        return f"https://api.binance.com/api/v3/depth?symbol={symbol.upper()}&limit=1000"

    def _stream_url(self, streams: list[str]) -> str:
        base = self.ws_url.rstrip("/")
        if base.endswith("/ws"):
            base = f"{base[:-3]}/stream"
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}streams={'/'.join(streams)}"

    async def _snapshot(self, symbol: str) -> OrderBookUpdate:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self._rest_url(symbol))
            response.raise_for_status()
            data = response.json()
        return OrderBookUpdate(
            symbol=symbol.upper(), bids=data.get("bids", []), asks=data.get("asks", []),
            update_id=int(data.get("lastUpdateId", 0)), timestamp_ms=0, is_snapshot=True,
        )

    async def subscribe(self, symbols: list[str]):
        streams = []
        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)
            # A diff depth stream is required to reconcile a REST snapshot. The partial
            # depth streams only allow 5, 10 or 20 levels and cannot support depth=50.
            streams.extend((f"{normalized}@depth@100ms", f"{normalized}@aggTrade"))
        async with websockets.connect(
            self._stream_url(streams), ping_interval=20, ping_timeout=20
        ) as socket:
            # Connect before snapshots so buffered events can be checked against REST ids.
            snapshots = await asyncio.gather(*(self._snapshot(symbol) for symbol in symbols))
            last_update = {snapshot.symbol: snapshot.update_id for snapshot in snapshots}
            synced = {snapshot.symbol: False for snapshot in snapshots}
            for snapshot in snapshots:
                yield snapshot
            logger.info("Binance subscribed to %s symbols", len(symbols))
            async for raw_message in socket:
                message = json.loads(raw_message)
                data = message.get("data", {})
                stream = message.get("stream", "")
                symbol = data.get("s")
                if "@depth" in stream and symbol:
                    upper_symbol = symbol.upper()
                    first_update = int(data.get("U", 0))
                    final_update = int(data.get("u", 0))
                    previous_update = int(data.get("pu", 0))
                    snapshot_id = last_update[upper_symbol]
                    if final_update <= snapshot_id:
                        continue
                    if not synced[upper_symbol]:
                        if first_update > snapshot_id + 1:
                            snapshot = await self._snapshot(upper_symbol)
                            last_update[upper_symbol] = snapshot.update_id
                            yield snapshot
                            continue
                        if not (first_update <= snapshot_id + 1 <= final_update):
                            continue
                        synced[upper_symbol] = True
                    elif previous_update and previous_update != last_update[upper_symbol]:
                        snapshot = await self._snapshot(upper_symbol)
                        last_update[upper_symbol] = snapshot.update_id
                        synced[upper_symbol] = False
                        yield snapshot
                        continue
                    last_update[upper_symbol] = final_update
                    yield OrderBookUpdate(
                        symbol=upper_symbol, bids=data.get("b", []), asks=data.get("a", []),
                        update_id=final_update, timestamp_ms=int(data.get("E", 0)), is_snapshot=False,
                    )
                elif "@aggTrade" in stream and symbol:
                    yield TradeUpdate(
                        symbol=symbol.upper(), price=float(data["p"]), quantity=float(data["q"]),
                        side="Sell" if data.get("m") else "Buy", timestamp_ms=int(data["T"]),
                        trade_id=str(data.get("a", "")),
                    )

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").lower()

    def denormalize_symbol(self, exchange_symbol: str) -> str:
        value = exchange_symbol.upper()
        return f"{value[:-4]}/USDT" if value.endswith("USDT") else value
