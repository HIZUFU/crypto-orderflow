from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    quantity: Decimal


class LocalOrderBook:
    """Reconstructs a Bybit L2 snapshot/delta stream for one symbol."""

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.update_id: int | None = None
        self.exchange_timestamp_ms: int | None = None
        self.ready = False

    def apply(
        self,
        message_type: str,
        bids: list[list[str]],
        asks: list[list[str]],
        update_id: int,
        timestamp_ms: int,
    ) -> None:
        if message_type == "snapshot":
            self.bids.clear()
            self.asks.clear()
            self.ready = True

        if not self.ready:
            return

        self._apply_side(self.bids, bids)
        self._apply_side(self.asks, asks)
        self.update_id = update_id
        self.exchange_timestamp_ms = timestamp_ms

    @staticmethod
    def _apply_side(side: dict[Decimal, Decimal], levels: list[list[str]]) -> None:
        for raw_price, raw_quantity in levels:
            price = Decimal(raw_price)
            quantity = Decimal(raw_quantity)
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity

    def top(self, depth: int = 20) -> tuple[list[BookLevel], list[BookLevel]]:
        bids = [BookLevel(price, quantity) for price, quantity in sorted(self.bids.items(), reverse=True)[:depth]]
        asks = [BookLevel(price, quantity) for price, quantity in sorted(self.asks.items())[:depth]]
        return bids, asks

    def best_bid_ask(self) -> tuple[BookLevel, BookLevel] | None:
        bids, asks = self.top(1)
        if not bids or not asks:
            return None
        return bids[0], asks[0]
