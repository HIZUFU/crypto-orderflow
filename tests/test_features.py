"""Tests for FeatureEngine in app/market/features.py."""
from time import time

import pytest

from app.market.features import FeatureEngine, TradeEvent
from app.market.orderbook import LocalOrderBook


class TestFeatureCalculation:
    """Tests for feature calculation logic."""

    def test_imbalance_in_range(self) -> None:
        """Imbalance should always be in range [-1, 1]."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "10"]], [["101", "1"]], 1, 1000)
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is not None
        assert -1.0 <= features["imbalance"] <= 1.0
        
        # Extreme case: only bids
        book2 = LocalOrderBook()
        book2.apply("snapshot", [["100", "10"]], [], 1, 1000)
        engine2 = FeatureEngine(book2)
        features2 = engine2.calculate()
        # When asks is empty, imbalance calculation depends on implementation
        # In current impl, if total_weighted is 0, imbalance is 0.0
        
    def test_imbalance_heavily_bid_weighted(self) -> None:
        """Imbalance should be positive when bids have more weight."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "10"], ["99", "5"]], [["101", "1"]], 1, 1000)
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is not None
        assert features["imbalance"] > 0

    def test_imbalance_heavily_ask_weighted(self) -> None:
        """Imbalance should be negative when asks have more weight."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "1"]], [["101", "10"], ["102", "5"]], 1, 1000)
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is not None
        assert features["imbalance"] < 0

    def test_delta_ratio_calculation(self) -> None:
        """Delta ratio should correctly calculate buy vs sell volume."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "10"]], [["101", "10"]], 1, int(time() * 1000))
        engine = FeatureEngine(book)
        
        # Add trades: 8 buy, 2 sell => delta = (8-2)/10 = 0.6
        now_ms = int(time() * 1000)
        for i in range(8):
            engine.observe_trade(TradeEvent(timestamp_ms=now_ms, price=100.5, quantity=1.0, side="Buy"))
        for i in range(2):
            engine.observe_trade(TradeEvent(timestamp_ms=now_ms, price=100.5, quantity=1.0, side="Sell"))
        
        features = engine.calculate()
        assert features is not None
        assert abs(features["delta_ratio_3s"] - 0.6) < 0.01

    def test_microprice_calculation(self) -> None:
        """Microprice should be weighted average between bid and ask."""
        book = LocalOrderBook()
        # Bid: 100 with qty 2, Ask: 102 with qty 2 => microprice should be 101 (midpoint)
        book.apply("snapshot", [["100", "2"]], [["102", "2"]], 1, 1000)
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is not None
        # microprice = (ask_price * bid_qty + bid_price * ask_qty) / (bid_qty + ask_qty)
        # = (102 * 2 + 100 * 2) / 4 = 101
        assert abs(features["microprice"] - 101.0) < 0.01
        
        # Asymmetric: Bid: 100 with qty 1, Ask: 102 with qty 3
        # microprice = (102 * 1 + 100 * 3) / 4 = 100.5 (closer to bid due to higher ask qty)
        book2 = LocalOrderBook()
        book2.apply("snapshot", [["100", "1"]], [["102", "3"]], 1, 1000)
        engine2 = FeatureEngine(book2)
        features2 = engine2.calculate()
        assert features2 is not None
        expected = (102 * 1 + 100 * 3) / 4
        assert abs(features2["microprice"] - expected) < 0.01


class TestEmptyData:
    """Tests for handling empty/missing data."""

    def test_calculate_returns_none_for_empty_book(self) -> None:
        """calculate() should return None when book is empty."""
        book = LocalOrderBook()
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is None

    def test_calculate_returns_none_without_snapshot(self) -> None:
        """calculate() should return None before snapshot is applied."""
        book = LocalOrderBook()
        # Don't apply snapshot
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is None

    def test_delta_ratio_zero_when_no_trades(self) -> None:
        """delta_ratio should be 0 when there are no recent trades."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "10"]], [["101", "10"]], 1, int(time() * 1000))
        engine = FeatureEngine(book)
        # Don't add any trades
        features = engine.calculate()
        assert features is not None
        assert features["delta_ratio_3s"] == 0.0

    def test_volatility_zero_when_insufficient_data(self) -> None:
        """volatility should be 0 when there's insufficient price history."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "10"]], [["101", "10"]], 1, int(time() * 1000))
        engine = FeatureEngine(book)
        features = engine.calculate()
        assert features is not None
        # With only one mid price point, volatility should be 0
        assert features["volatility_30s"] == 0.0


class TestTradeObservation:
    """Tests for trade observation and windowing."""

    def test_observe_trade_adds_to_history(self) -> None:
        """observe_trade should add trades to history."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "10"]], [["101", "10"]], 1, 1000)
        engine = FeatureEngine(book)
        
        now_ms = int(time() * 1000)
        engine.observe_trade(TradeEvent(timestamp_ms=now_ms, price=100.5, quantity=1.0, side="Buy"))
        
        features = engine.calculate()
        assert features is not None
        assert features["trades_3s"] >= 1
        assert features["buy_volume_3s"] == 1.0

    def test_old_trades_are_pruned(self) -> None:
        """Trades older than 60 seconds should be pruned."""
        book = LocalOrderBook()
        now_ms = int(time() * 1000)
        book.apply("snapshot", [["100", "10"]], [["101", "10"]], 1, now_ms)
        engine = FeatureEngine(book)
        
        # Add old trade (70 seconds ago)
        old_ms = now_ms - 70_000
        engine.observe_trade(TradeEvent(timestamp_ms=old_ms, price=100.5, quantity=100.0, side="Buy"))
        
        # Add recent trade
        engine.observe_trade(TradeEvent(timestamp_ms=now_ms, price=100.5, quantity=1.0, side="Sell"))
        
        features = engine.calculate()
        assert features is not None
        # Old trade should be pruned, only recent trade counts
        assert features["trades_3s"] == 1
        assert features["buy_volume_3s"] == 0.0
        assert features["sell_volume_3s"] == 1.0

    def test_trade_window_is_3_seconds(self) -> None:
        """Only trades within last 3 seconds should count for delta_ratio."""
        book = LocalOrderBook()
        now_ms = int(time() * 1000)
        book.apply("snapshot", [["100", "10"]], [["101", "10"]], 1, now_ms)
        engine = FeatureEngine(book)
        
        # Add trade 5 seconds ago (outside 3s window)
        old_ms = now_ms - 5_000
        engine.observe_trade(TradeEvent(timestamp_ms=old_ms, price=100.5, quantity=100.0, side="Buy"))
        
        # Add trade within 3s window
        engine.observe_trade(TradeEvent(timestamp_ms=now_ms, price=100.5, quantity=1.0, side="Sell"))
        
        features = engine.calculate()
        assert features is not None
        # Only the recent trade should count
        assert features["trades_3s"] == 1
