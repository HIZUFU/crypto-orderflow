from app.config import Settings
from app.market.service import ConnectionSpec, MarketService, default_ws_url


def test_default_stream_urls_cover_spot_and_linear() -> None:
    assert default_ws_url("bybit", "spot").endswith("/spot")
    assert default_ws_url("bybit", "linear").endswith("/linear")
    assert "stream.binance.com" in default_ws_url("binance", "spot")
    assert "fstream.binance.com" in default_ws_url("binance", "linear")


def test_sources_are_isolated_by_connection_and_symbol() -> None:
    service = MarketService(Settings(use_ml_filter=False), None)
    service._prepare_sources([
        ConnectionSpec(1, "Bybit spot", "bybit", "spot", None, ("BTCUSDT",)),
        ConnectionSpec(2, "Binance futures", "binance", "linear", None, ("BTCUSDT",)),
    ])
    assert set(service.sources) == {"1:BTCUSDT", "2:BTCUSDT"}
    assert service.resolve_source("BTCUSDT", "1:BTCUSDT") == "1:BTCUSDT"
    assert service.resolve_source("BTCUSDT", "2:BTCUSDT") == "2:BTCUSDT"
    assert service.resolve_source("BTCUSDT", "missing") is None


def test_signal_state_rearms_only_after_neutral_features() -> None:
    service = MarketService(Settings(use_ml_filter=False), None)
    service._prepare_sources([ConnectionSpec(1, "Desk", "bybit", "linear", None, ("BTCUSDT",))])
    assert service.signal_state["1:BTCUSDT"] is None
    service.signal_state["1:BTCUSDT"] = "SHORT"
    assert service.signal_state["1:BTCUSDT"] == "SHORT"
