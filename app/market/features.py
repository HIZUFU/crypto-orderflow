from collections import deque
from dataclasses import dataclass
from time import time

from app.market.orderbook import LocalOrderBook


@dataclass
class TradeEvent:
    timestamp_ms: int
    price: float
    quantity: float
    side: str


class FeatureEngine:
    def __init__(self, book: LocalOrderBook) -> None:
        self.book = book
        self.trades: deque[TradeEvent] = deque(maxlen=5000)
        self.mid_history: deque[tuple[float, float]] = deque(maxlen=5000)

    def observe_trade(self, event: TradeEvent) -> None:
        self.trades.append(event)
        cutoff = event.timestamp_ms - 60_000
        while self.trades and self.trades[0].timestamp_ms < cutoff:
            self.trades.popleft()

    def calculate(self, depth: int = 20) -> dict[str, float] | None:
        best = self.book.best_bid_ask()
        if best is None:
            return None
        bid, ask = best
        mid = (float(bid.price) + float(ask.price)) / 2
        spread_bps = (float(ask.price - bid.price) / mid) * 10_000
        bids, asks = self.book.top(depth)

        bid_weighted = sum(float(level.quantity) / (index + 1) for index, level in enumerate(bids))
        ask_weighted = sum(float(level.quantity) / (index + 1) for index, level in enumerate(asks))
        total_weighted = bid_weighted + ask_weighted
        imbalance = (bid_weighted - ask_weighted) / total_weighted if total_weighted else 0.0

        bid_qty = float(bid.quantity)
        ask_qty = float(ask.quantity)
        microprice = ((float(ask.price) * bid_qty) + (float(bid.price) * ask_qty)) / (bid_qty + ask_qty) if bid_qty + ask_qty else mid

        now_ms = int(time() * 1000)
        recent = [trade for trade in self.trades if trade.timestamp_ms >= now_ms - 3_000]
        buy_volume = sum(trade.quantity for trade in recent if trade.side.lower() == "buy")
        sell_volume = sum(trade.quantity for trade in recent if trade.side.lower() == "sell")
        total_trade_volume = buy_volume + sell_volume
        delta_ratio = (buy_volume - sell_volume) / total_trade_volume if total_trade_volume else 0.0

        self.mid_history.append((now_ms / 1000, mid))
        while self.mid_history and self.mid_history[0][0] < now_ms / 1000 - 30:
            self.mid_history.popleft()
        prices = [price for _, price in self.mid_history]
        volatility = (max(prices) - min(prices)) / mid if prices else 0.0

        return {
            "mid_price": mid,
            "spread_bps": spread_bps,
            "imbalance": imbalance,
            "microprice": microprice,
            "microprice_offset_bps": (microprice - mid) / mid * 10_000,
            "buy_volume_3s": buy_volume,
            "sell_volume_3s": sell_volume,
            "delta_ratio_3s": delta_ratio,
            "trades_3s": float(len(recent)),
            "trade_intensity": len(recent) / 3.0,
            "volatility_30s": volatility,
            "book_depth_bid": sum(float(level.quantity) for level in bids),
            "book_depth_ask": sum(float(level.quantity) for level in asks),
        }
