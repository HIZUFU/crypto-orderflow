from app.strategy.orderflow import generate_signal


def base_features() -> dict[str, float]:
    return {
        "mid_price": 100.0,
        "spread_bps": 2.0,
        "imbalance": 0.3,
        "microprice_offset_bps": 1.0,
        "delta_ratio_3s": 0.25,
        "trades_3s": 5.0,
    }


def test_long_signal_requires_confirming_flow() -> None:
    signal = generate_signal("BTCUSDT", base_features())
    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.stop_loss < signal.reference_price < signal.take_profit


def test_wide_spread_is_blocked() -> None:
    features = base_features()
    features["spread_bps"] = 10.0
    assert generate_signal("BTCUSDT", features) is None


def test_conflicting_delta_is_blocked() -> None:
    features = base_features()
    features["delta_ratio_3s"] = -0.5
    assert generate_signal("BTCUSDT", features) is None
