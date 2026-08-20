from decimal import Decimal

from app.market.orderbook import LocalOrderBook


def test_snapshot_and_delta_reconstruct_book() -> None:
    book = LocalOrderBook()
    book.apply("snapshot", [["100", "2"], ["99", "1"]], [["101", "3"]], 1, 1000)
    best = book.best_bid_ask()
    assert best is not None
    assert best[0].price == Decimal("100")
    book.apply("delta", [["100", "0"], ["98", "4"]], [["101", "5"]], 2, 1100)
    bids, asks = book.top(5)
    assert bids[0].price == Decimal("99")
    assert asks[0].quantity == Decimal("5")


def test_delta_before_snapshot_is_ignored() -> None:
    book = LocalOrderBook()
    book.apply("delta", [["100", "2"]], [], 1, 1000)
    assert not book.ready
    assert book.best_bid_ask() is None
