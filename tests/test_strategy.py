"""Tests for generate_signal in app/strategy/orderflow.py."""
import pytest

from app.strategy.orderflow import Signal, generate_signal


def base_features() -> dict[str, float]:
    """Return base features that should generate a LONG signal."""
    return {
        "mid_price": 100.0,
        "spread_bps": 2.0,
        "imbalance": 0.3,
        "microprice": 100.05,
        "microprice_offset_bps": 1.0,
        "buy_volume_3s": 5.0,
        "sell_volume_3s": 2.0,
        "delta_ratio_3s": 0.25,
        "trades_3s": 5.0,
        "trade_intensity": 1.67,
        "volatility_30s": 0.02,
        "book_depth_bid": 6.5,
        "book_depth_ask": 6.0,
    }


class TestLongSignal:
    """Tests for LONG signal generation."""

    def test_generate_signal_long_success(self) -> None:
        """Should generate LONG signal when conditions are met."""
        features = base_features()
        signal = generate_signal("BTCUSDT", features)
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.symbol == "BTCUSDT"
        # Verify stop_loss < reference_price < take_profit for LONG
        assert signal.stop_loss < signal.reference_price < signal.take_profit

    def test_long_stop_loss_calculation(self) -> None:
        """LONG stop_loss should be below entry (risk_pct = 0.0015)."""
        features = base_features()
        signal = generate_signal("BTCUSDT", features, notional=100.0)
        assert signal is not None
        # stop_loss = mid * (1 - 0.0015)
        expected_stop = 100.0 * (1 - 0.0015)
        assert abs(signal.stop_loss - expected_stop) < 0.001

    def test_long_take_profit_calculation(self) -> None:
        """LONG take_profit should be above entry (reward_pct = 0.0030)."""
        features = base_features()
        signal = generate_signal("BTCUSDT", features, notional=100.0)
        assert signal is not None
        # take_profit = mid * (1 + 0.0030)
        expected_target = 100.0 * (1 + 0.0030)
        assert abs(signal.take_profit - expected_target) < 0.001

    def test_long_risk_amount_calculation(self) -> None:
        """LONG risk_amount should be notional * risk_pct."""
        features = base_features()
        notional = 100.0
        signal = generate_signal("BTCUSDT", features, notional=notional)
        assert signal is not None
        # risk_amount = notional * 0.0015
        expected_risk = notional * 0.0015
        assert abs(signal.risk_amount - expected_risk) < 0.001


class TestShortSignal:
    """Tests for SHORT signal generation."""

    def test_generate_signal_short_success(self) -> None:
        """Should generate SHORT signal when conditions are met."""
        features = base_features()
        # Invert features for SHORT
        features["imbalance"] = -0.3
        features["delta_ratio_3s"] = -0.25
        features["microprice_offset_bps"] = -1.0
        
        signal = generate_signal("BTCUSDT", features)
        assert signal is not None
        assert signal.direction == "SHORT"
        # Verify stop_loss > reference_price > take_profit for SHORT
        assert signal.stop_loss > signal.reference_price > signal.take_profit

    def test_short_stop_loss_calculation(self) -> None:
        """SHORT stop_loss should be above entry (risk_pct = 0.0015)."""
        features = base_features()
        features["imbalance"] = -0.3
        features["delta_ratio_3s"] = -0.25
        features["microprice_offset_bps"] = -1.0
        
        signal = generate_signal("BTCUSDT", features, notional=100.0)
        assert signal is not None
        # stop_loss = mid * (1 + 0.0015)
        expected_stop = 100.0 * (1 + 0.0015)
        assert abs(signal.stop_loss - expected_stop) < 0.001

    def test_short_take_profit_calculation(self) -> None:
        """SHORT take_profit should be below entry (reward_pct = 0.0030)."""
        features = base_features()
        features["imbalance"] = -0.3
        features["delta_ratio_3s"] = -0.25
        features["microprice_offset_bps"] = -1.0
        
        signal = generate_signal("BTCUSDT", features, notional=100.0)
        assert signal is not None
        # take_profit = mid * (1 - 0.0030)
        expected_target = 100.0 * (1 - 0.0030)
        assert abs(signal.take_profit - expected_target) < 0.001


class TestSignalFilters:
    """Tests for signal filtering rules."""

    def test_wide_spread_is_blocked(self) -> None:
        """Signal should NOT be generated if spread > 8 bps."""
        features = base_features()
        features["spread_bps"] = 10.0
        signal = generate_signal("BTCUSDT", features)
        assert signal is None

    def test_low_trades_is_blocked(self) -> None:
        """Signal should NOT be generated if trades_3s < 2."""
        features = base_features()
        features["trades_3s"] = 1.0
        signal = generate_signal("BTCUSDT", features)
        assert signal is None

    def test_low_imbalance_is_blocked(self) -> None:
        """Signal should NOT be generated if imbalance < 0.22."""
        features = base_features()
        features["imbalance"] = 0.15  # Below threshold
        signal = generate_signal("BTCUSDT", features)
        assert signal is None

    def test_low_delta_is_blocked(self) -> None:
        """Signal should NOT be generated if delta < 0.18."""
        features = base_features()
        features["delta_ratio_3s"] = 0.10  # Below threshold
        signal = generate_signal("BTCUSDT", features)
        assert signal is None

    def test_zero_spread_is_blocked(self) -> None:
        """Signal should NOT be generated if spread <= 0."""
        features = base_features()
        features["spread_bps"] = 0.0
        signal = generate_signal("BTCUSDT", features)
        assert signal is None

    def test_negative_spread_is_blocked(self) -> None:
        """Signal should NOT be generated if spread is negative."""
        features = base_features()
        features["spread_bps"] = -1.0
        signal = generate_signal("BTCUSDT", features)
        assert signal is None

    def test_conflicting_delta_is_blocked(self) -> None:
        """LONG signal should NOT be generated with negative delta."""
        features = base_features()
        features["delta_ratio_3s"] = -0.5
        signal = generate_signal("BTCUSDT", features)
        assert signal is None


class TestSignalProperties:
    """Tests for signal object properties."""

    def test_entry_band_calculation(self) -> None:
        """entry_low and entry_high should form a band around mid."""
        features = base_features()
        signal = generate_signal("BTCUSDT", features)
        assert signal is not None
        # entry_band = mid * 0.00025
        expected_band = 100.0 * 0.00025
        assert abs(signal.entry_low - (100.0 - expected_band)) < 0.001
        assert abs(signal.entry_high - (100.0 + expected_band)) < 0.001

    def test_score_is_capped(self) -> None:
        """Signal score should be capped at 0.99."""
        features = base_features()
        # Create extreme features that would produce high score
        features["imbalance"] = 1.0
        features["delta_ratio_3s"] = 1.0
        features["microprice_offset_bps"] = 10.0
        
        signal = generate_signal("BTCUSDT", features)
        assert signal is not None
        assert signal.score <= 0.99

    def test_reason_contains_feature_values(self) -> None:
        """Signal reason should contain key feature values."""
        features = base_features()
        signal = generate_signal("BTCUSDT", features)
        assert signal is not None
        assert "imbalance" in signal.reason
        assert "delta_3s" in signal.reason
        assert "microprice_offset" in signal.reason

    def test_features_are_preserved(self) -> None:
        """Signal should preserve the input features."""
        features = base_features()
        signal = generate_signal("BTCUSDT", features)
        assert signal is not None
        assert signal.features == features

    def test_leverage_parameter_does_not_affect_prices(self) -> None:
        """Leverage should not affect stop_loss/take_profit calculations."""
        features = base_features()
        signal_1x = generate_signal("BTCUSDT", features, leverage=1)
        signal_10x = generate_signal("BTCUSDT", features, leverage=10)
        assert signal_1x is not None
        assert signal_10x is not None
        # Prices should be identical regardless of leverage
        assert signal_1x.stop_loss == signal_10x.stop_loss
        assert signal_1x.take_profit == signal_10x.take_profit
