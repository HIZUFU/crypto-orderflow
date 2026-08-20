import pytest


def calculate_pnl(direction: str, entry: float, exit: float, notional: float, fee_rate: float) -> float:
    gross = (exit - entry) / entry * notional
    if direction == "SHORT":
        gross *= -1
    return gross - notional * fee_rate * 2


def test_long_pnl_includes_round_trip_fees() -> None:
    assert calculate_pnl("LONG", 100, 101, 10, 0.001) == pytest.approx(0.08)


def test_short_pnl_is_positive_when_price_falls() -> None:
    assert calculate_pnl("SHORT", 100, 99, 10, 0.001) == pytest.approx(0.08)
