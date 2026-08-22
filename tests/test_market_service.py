from app.config import Settings
from app.exchanges.binance import BinanceExchange
from app.market.service import ConnectionSpec, MarketService, default_ws_url


def test_default_stream_urls_cover_spot_and_linear() -> None:
    assert default_ws_url("bybit", "spot").endswith("/spot")
    assert default_ws_url("bybit", "linear").endswith("/linear")
    assert "stream.binance.com" in default_ws_url("binance", "spot")
    assert "fstream.binance.com" in default_ws_url("binance", "linear")


def test_binance_legacy_ws_endpoint_normalizes_to_combined_stream() -> None:
    exchange = BinanceExchange(ws_url="wss://fstream.binance.com/ws")
    assert exchange._stream_url(["btcusdt@aggTrade"]) == "wss://fstream.binance.com/stream?streams=btcusdt@aggTrade"


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


def test_source_keys_are_stable_for_same_connection() -> None:
    service = MarketService(Settings(use_ml_filter=False), None)
    specs = [ConnectionSpec(7, "Desk", "bybit", "linear", None, ("BTCUSDT", "ETHUSDT"))]
    service._prepare_sources(specs)
    first = set(service.sources)
    service._prepare_sources(specs)
    assert set(service.sources) == first
    assert service.resolve_source("BTCUSDT", "7:BTCUSDT") == "7:BTCUSDT"
