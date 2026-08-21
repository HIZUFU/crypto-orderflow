"""Exchange registry and factory."""
from app.exchanges.base import Exchange
from app.exchanges.binance import BinanceExchange
from app.exchanges.bybit import BybitExchange

__all__ = ["Exchange", "BybitExchange", "BinanceExchange", "get_exchange"]


EXCHANGES = {
    "bybit": BybitExchange,
    "binance": BinanceExchange,
}


def get_exchange(name: str, **kwargs) -> Exchange:
    """
    Get exchange instance by name.
    
    Args:
        name: Exchange name ("bybit" or "binance")
        **kwargs: Exchange-specific configuration
    
    Returns:
        Exchange instance
    
    Raises:
        ValueError: If exchange not found
    """
    name = name.lower()
    if name not in EXCHANGES:
        raise ValueError(f"Unknown exchange: {name}. Available: {list(EXCHANGES.keys())}")
    return EXCHANGES[name](**kwargs)