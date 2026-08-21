"""Base exchange interface for market data streaming."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class OrderBookUpdate:
    """Normalized order book update."""
    symbol: str
    bids: list[tuple[str, str]]  # [(price, quantity), ...]
    asks: list[tuple[str, str]]
    update_id: int
    timestamp_ms: int
    is_snapshot: bool


@dataclass
class TradeUpdate:
    """Normalized trade update."""
    symbol: str
    price: float
    quantity: float
    side: str  # "Buy" or "Sell"
    timestamp_ms: int
    trade_id: str


class Exchange(ABC):
    """
    Abstract base class for exchange connections.
    
    Each exchange implementation handles its own WebSocket protocol,
    message parsing, and data normalization.
    """
    
    def __init__(self, name: str, ws_url: str) -> None:
        self.name = name
        self.ws_url = ws_url
    
    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> AsyncIterator[OrderBookUpdate | TradeUpdate]:
        """
        Subscribe to order book and trade streams for given symbols.
        
        Yields normalized updates that can be consumed by MarketService.
        """
        pass
    
    @abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to exchange-specific format.
        
        Example: "BTC/USDT" -> "BTCUSDT" (Bybit) or "btcusdt" (Binance)
        """
        pass
    
    @abstractmethod
    def denormalize_symbol(self, exchange_symbol: str) -> str:
        """
        Convert exchange symbol back to standard format.
        
        Example: "BTCUSDT" -> "BTC/USDT"
        """
        pass