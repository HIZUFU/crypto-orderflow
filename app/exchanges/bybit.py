"""Bybit exchange adapter."""
import json
import logging
from typing import AsyncIterator

import websockets

from app.exchanges.base import Exchange, OrderBookUpdate, TradeUpdate

logger = logging.getLogger(__name__)


class BybitExchange(Exchange):
    """Bybit linear futures market data adapter."""
    
    def __init__(self, ws_url: str = "wss://stream.bybit.com/v5/public/linear", depth: int = 50) -> None:
        super().__init__("bybit", ws_url)
        self.depth = depth
    
    async def subscribe(self, symbols: list[str]) -> AsyncIterator[OrderBookUpdate | TradeUpdate]:
        """Subscribe to Bybit order book and trades."""
        args = []
        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)
            args.append(f"orderbook.{self.depth}.{normalized}")
            args.append(f"publicTrade.{normalized}")
        
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as socket:
            await socket.send(json.dumps({"op": "subscribe", "args": args}))
            logger.info(f"Bybit subscribed to {len(symbols)} symbols")
            
            async for raw_message in socket:
                message = json.loads(raw_message)
                
                # Parse order book updates
                topic = message.get("topic", "")
                if topic.startswith("orderbook."):
                    data = message.get("data") or {}
                    symbol = data.get("s")
                    if symbol:
                        yield OrderBookUpdate(
                            symbol=symbol,
                            bids=data.get("b", []),
                            asks=data.get("a", []),
                            update_id=int(data.get("u", 0)),
                            timestamp_ms=int(message.get("ts", 0)),
                            is_snapshot=(message.get("type") == "snapshot"),
                        )
                
                # Parse trade updates
                elif topic.startswith("publicTrade."):
                    for trade in message.get("data", []):
                        symbol = trade.get("s")
                        if symbol:
                            yield TradeUpdate(
                                symbol=symbol,
                                price=float(trade["p"]),
                                quantity=float(trade["v"]),
                                side=trade["S"],  # "Buy" or "Sell"
                                timestamp_ms=int(trade["T"]),
                                trade_id=trade.get("i", ""),
                            )
    
    def normalize_symbol(self, symbol: str) -> str:
        """Convert BTC/USDT -> BTCUSDT."""
        return symbol.replace("/", "").upper()
    
    def denormalize_symbol(self, exchange_symbol: str) -> str:
        """Convert BTCUSDT -> BTC/USDT."""
        # Simple heuristic: assume USDT pairs
        if exchange_symbol.endswith("USDT"):
            base = exchange_symbol[:-4]
            return f"{base}/USDT"
        return exchange_symbol
