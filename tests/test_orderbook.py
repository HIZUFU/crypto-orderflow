"""Tests for LocalOrderBook in app/market/orderbook.py."""
from decimal import Decimal

import pytest

from app.market.orderbook import LocalOrderBook


class TestSnapshot:
    """Tests for snapshot application."""

    def test_snapshot_overwrites_state(self) -> None:
        """Applying a snapshot should completely overwrite the current book state."""
        book = LocalOrderBook()
        # Initial snapshot
        book.apply("snapshot", [["100", "2"], ["99", "1"]], [["101", "3"]], 1, 1000)
        best = book.best_bid_ask()
        assert best is not None
        assert best[0].price == Decimal("100")
        assert best[1].price == Decimal("101")
        
        # New snapshot should completely replace old state
        book.apply("snapshot", [["200", "5"]], [["201", "4"]], 2, 2000)
        best = book.best_bid_ask()
        assert best is not None
        assert best[0].price == Decimal("200")
        assert best[1].price == Decimal("201")
        # Old levels should be gone
        bids, asks = book.top(10)
        assert len(bids) == 1
        assert len(asks) == 1

    def test_snapshot_sets_ready_flag(self) -> None:
        """Snapshot should set the ready flag to True."""
        book = LocalOrderBook()
        assert book.ready is False
        book.apply("snapshot", [["100", "1"]], [["101", "1"]], 1, 1000)
        assert book.ready is True


class TestDelta:
    """Tests for delta application."""

    def test_delta_adds_new_levels(self) -> None:
        """Delta should add new price levels that don't exist."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "2"]], [["101", "2"]], 1, 1000)
        # Add new levels via delta
        book.apply("delta", [["99", "1.5"]], [["102", "1.5"]], 2, 1100)
        bids, asks = book.top(10)
        prices_bid = [level.price for level in bids]
        prices_ask = [level.price for level in asks]
        assert Decimal("99") in prices_bid
        assert Decimal("102") in prices_ask

    def test_delta_updates_existing_levels(self) -> None:
        """Delta should update quantity of existing price levels."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "2"]], [["101", "2"]], 1, 1000)
        # Update existing level
        book.apply("delta", [["100", "5"]], [["101", "3"]], 2, 1100)
        bids, asks = book.top(10)
        assert bids[0].quantity == Decimal("5")
        assert asks[0].quantity == Decimal("3")

    def test_delta_removes_zero_quantity_levels(self) -> None:
        """Delta should remove levels where quantity becomes 0."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "2"], ["99", "1"]], [["101", "3"]], 1, 1000)
        # Remove top bid by setting quantity to 0
        book.apply("delta", [["100", "0"]], [], 2, 1100)
        bids, asks = book.top(10)
        # Top bid should now be 99
        assert bids[0].price == Decimal("99")
        assert len(bids) == 1

    def test_delta_before_snapshot_is_ignored(self) -> None:
        """Delta messages before snapshot should be ignored."""
        book = LocalOrderBook()
        book.apply("delta", [["100", "2"]], [], 1, 1000)
        assert book.ready is False
        assert book.best_bid_ask() is None


class TestBestBidAsk:
    """Tests for best bid/ask retrieval."""

    def test_get_best_bid_returns_highest_price(self) -> None:
        """get_best_bid should return the highest bid price."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "1"], ["101", "2"], ["99", "3"]], [["103", "1"]], 1, 1000)
        best = book.best_bid_ask()
        assert best is not None
        assert best[0].price == Decimal("101")

    def test_get_best_ask_returns_lowest_price(self) -> None:
        """get_best_ask should return the lowest ask price."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "1"]], [["103", "1"], ["101", "2"], ["102", "3"]], 1, 1000)
        best = book.best_bid_ask()
        assert best is not None
        assert best[1].price == Decimal("101")

    def test_returns_none_when_book_empty(self) -> None:
        """best_bid_ask should return None if either side is empty."""
        book = LocalOrderBook()
        book.apply("snapshot", [], [["101", "1"]], 1, 1000)
        assert book.best_bid_ask() is None
        
        book.apply("snapshot", [["100", "1"]], [], 2, 1100)
        assert book.best_bid_ask() is None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_negative_prices_handled(self) -> None:
        """Negative prices should be handled (Decimal accepts them)."""
        book = LocalOrderBook()
        # The implementation doesn't validate prices, just stores them
        book.apply("snapshot", [["-100", "1"]], [["101", "1"]], 1, 1000)
        bids, asks = book.top(10)
        # Negative price is stored as-is (validation would be added in production)
        assert bids[0].price == Decimal("-100")

    def test_top_returns_correct_depth(self) -> None:
        """top() should return requested depth."""
        book = LocalOrderBook()
        bids_data = [[str(100 - i), str(i + 1)] for i in range(10)]
        asks_data = [[str(101 + i), str(i + 1)] for i in range(10)]
        book.apply("snapshot", bids_data, asks_data, 1, 1000)
        
        # Request depth of 5
        bids, asks = book.top(5)
        assert len(bids) == 5
        assert len(asks) == 5
        
        # Request depth of 20 (more than available)
        bids, asks = book.top(20)
        assert len(bids) == 10
        assert len(asks) == 10

    def test_update_id_stored(self) -> None:
        """update_id should be stored from each message."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "1"]], [["101", "1"]], 5, 1000)
        assert book.update_id == 5
        book.apply("delta", [], [], 10, 1100)
        assert book.update_id == 10

    def test_timestamp_stored(self) -> None:
        """exchange_timestamp_ms should be stored from each message."""
        book = LocalOrderBook()
        book.apply("snapshot", [["100", "1"]], [["101", "1"]], 1, 1234567890)
        assert book.exchange_timestamp_ms == 1234567890
