"""Binance spot and USD-M futures public market adapter."""
import json
import logging

import httpx
import websockets

from app.exchanges.base import Exchange, OrderBookUpdate, TradeUpdate

logger = logging.getLogger(__name__)


class BinanceExchange(Exchange):
    def __init__(self, ws_url: str = "wss://fstream.binance.com/stream", depth: int = 20) -> None:
        super().__init__("binance", ws_url)
        self.depth = depth

    def _rest_url(self, symbol: str) -> str:
        if "fstream" in self.ws_url:
            return f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol.upper()}&limit=1000"
        return f"https://api.binance.com/api/v3/depth?symbol={symbol.upper()}&limit=1000"

    async def _snapshot(self, symbol: str) -> OrderBookUpdate:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self._rest_url(symbol))
            response.raise_for_status()
            data = response.json()
        return OrderBookUpdate(symbol=symbol.upper(), bids=data.get("bids", []), asks=data.get("asks", []), update_id=int(data.get("lastUpdateId", 0)), timestamp_ms=0, is_snapshot=True)

    async def subscribe(self, symbols: list[str]):
        for symbol in symbols:
            yield await self._snapshot(symbol)
        streams = []
        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)
            streams.extend((f"{normalized}@depth{self.depth}@100ms", f"{normalized}@aggTrade"))
        stream_url = f"{self.ws_url}?streams={'/'.join(streams)}"
        async with websockets.connect(stream_url, ping_interval=20, ping_timeout=20) as socket:
            logger.info("Binance subscribed to %s symbols", len(symbols))
            async for raw_message in socket:
                message = json.loads(raw_message)
                data = message.get("data", {})
                stream = message.get("stream", "")
                if "@depth" in stream and data.get("s"):
                    yield OrderBookUpdate(symbol=data["s"], bids=data.get("b", []), asks=data.get("a", []), update_id=int(data.get("u", 0)), timestamp_ms=int(data.get("E", 0)), is_snapshot=False)
                elif "@aggTrade" in stream and data.get("s"):
                    yield TradeUpdate(symbol=data["s"], price=float(data["p"]), quantity=float(data["q"]), side="Sell" if data.get("m") else "Buy", timestamp_ms=int(data["T"]), trade_id=str(data.get("a", "")))

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").lower()

    def denormalize_symbol(self, exchange_symbol: str) -> str:
        value = exchange_symbol.upper()
        return f"{value[:-4]}/USDT" if value.endswith("USDT") else value
