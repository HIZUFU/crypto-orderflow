from app.market.candles import CandleAggregator


def test_candle_aggregator_rolls_completed_candles() -> None:
    aggregator = CandleAggregator("BTCUSDT", max_candles=10)
    aggregator.add_trade(60_000, 100.0, 1.0)
    aggregator.add_trade(60_500, 101.0, 2.0)
    aggregator.add_trade(120_000, 99.0, 3.0)

    candles = aggregator.get_candles("1m")
    assert len(candles) == 2
    assert candles[0]["open"] == 100.0
    assert candles[0]["high"] == 101.0
    assert candles[0]["close"] == 101.0
    assert candles[0]["volume"] == 3.0
    assert candles[1]["close"] == 99.0
