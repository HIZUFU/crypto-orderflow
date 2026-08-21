"""OHLCV candle aggregator from trade stream."""
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class Candle:
    """OHLCV candle."""
    timestamp: int  # Unix timestamp in milliseconds (start of candle)
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int = 0


class CandleAggregator:
    """
    Aggregate trades into OHLCV candles in real-time.
    
    Supports multiple timeframes simultaneously (1m, 5m, 15m, 1h).
    Keeps a rolling window of recent candles in memory.
    """
    
    TIMEFRAMES = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
    }
    
    def __init__(self, symbol: str, max_candles: int = 500) -> None:
        self.symbol = symbol
        self.max_candles = max_candles
        
        # Current incomplete candles (one per timeframe)
        self.current: dict[str, Candle | None] = {tf: None for tf in self.TIMEFRAMES}
        
        # Completed candles (rolling window per timeframe)
        self.history: dict[str, Deque[Candle]] = {
            tf: deque(maxlen=max_candles) for tf in self.TIMEFRAMES
        }
    
    def add_trade(self, timestamp_ms: int, price: float, volume: float) -> dict[str, Candle | None]:
        """
        Process a trade and update candles.
        
        Returns dict of newly completed candles (timeframe -> Candle or None).
        """
        completed = {}
        
        for timeframe, interval_ms in self.TIMEFRAMES.items():
            candle_start = (timestamp_ms // interval_ms) * interval_ms
            current = self.current[timeframe]
            
            # Start new candle if needed
            if current is None or current.timestamp != candle_start:
                # Save previous candle if it exists
                if current is not None:
                    self.history[timeframe].append(current)
                    completed[timeframe] = current
                
                # Create new candle
                self.current[timeframe] = Candle(
                    timestamp=candle_start,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume,
                    trades=1,
                )
            else:
                # Update current candle
                current.high = max(current.high, price)
                current.low = min(current.low, price)
                current.close = price
                current.volume += volume
                current.trades += 1
        
        return completed
    
    def get_candles(self, timeframe: str = "1m", limit: int = 100) -> list[dict]:
        """Get recent completed candles for a timeframe."""
        if timeframe not in self.TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {timeframe}")
        
        candles = list(self.history[timeframe])
        
        # Include current incomplete candle if it exists
        if self.current[timeframe] is not None:
            candles.append(self.current[timeframe])
        
        # Return last N candles
        return [
            {
                "time": c.timestamp // 1000,  # Convert to seconds for lightweight-charts
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles[-limit:]
        ]
    
    def get_current_price(self) -> float | None:
        """Get latest close price from 1m candle."""
        candle = self.current.get("1m")
        return candle.close if candle else None
