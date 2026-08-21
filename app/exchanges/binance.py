"""Binance Futures exchange adapter."""
import json
import logging
from typing import AsyncIterator

import websockets

from app.exchanges.base import Exchange, OrderBookUpdate, TradeUpdate

logger = logging.getLogger(__name__)


class BinanceExchange(Exchange):
    """Binance USD-M futures market data adapter."""
    
    def __init__(self, ws_url: str = "wss://fstream.binance.com/ws", depth: int = 20) -> None:
        super().__init__("binance", ws_url)
        self.depth = depth
    
    async def subscribe(self, symbols: list[str]) -> AsyncIterator[OrderBookUpdate | TradeUpdate]:
        """Subscribe to Binance order book and trades."""
        # Binance uses combined stream format
        streams = []
        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)
            streams.append(f"{normalized}@depth{self.depth}@100ms")
            streams.append(f"{normalized}@aggTrade")
        
        stream_names = "/".join(streams)
        ws_url = f"{self.ws_url}/{stream_names}"
        
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as socket:
            logger.info(f"Binance subscribed to {len(symbols)} symbols")
            
            async for raw_message in socket:
                message = json.loads(raw_message)
                
                # Binance uses "stream" and "data" wrapper
                stream = message.get("stream", "")
                data = message.get("data", {})
                
                # Parse order book updates
                if "@depth" in stream:
                    symbol = data.get("s")
                    if symbol:
                        yield OrderBookUpdate(
                            symbol=symbol,
                            bids=data.get("b", []),
                            asks=data.get("a", []),
                            update_id=int(data.get("u", 0)),
                            timestamp_ms=int(data.get("E", 0)),
                            is_snapshot=False,  # Binance sends updates, not snapshots
                        )
                
                # Parse trade updates
                elif "@aggTrade" in stream:
                    symbol = data.get("s")
                    if symbol:
                        yield TradeUpdate(
                            symbol=symbol,
                            price=float(data["p"]),
                            quantity=float(data["q"]),
                            side="Buy" if data["m"] is False else "Sell",  # m=false means buyer is maker
                            timestamp_ms=int(data["T"]),
                            trade_id=str(data.get("a", "")),
                        )
    
    def normalize_symbol(self, symbol: str) -> str:
        """Convert BTC/USDT -> btcusdt (lowercase for Binance streams)."""
        return symbol.replace("/", "").lower()
    
    def denormalize_symbol(self, exchange_symbol: str) -> str:
        """Convert btcusdt -> BTC/USDT."""
        # Simple heuristic: assume USDT pairs
        exchange_symbol = exchange_symbol.upper()
        if exchange_symbol.endswith("USDT"):
            base = exchange_symbol[:-4]
            return f"{base}/USDT"
        return exchange_symbol