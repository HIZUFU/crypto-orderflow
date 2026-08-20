# Architecture

## Runtime flow

```text
Bybit public WebSocket
        |
        v
MarketService -> LocalOrderBook -> FeatureEngine -> Order-Flow Momentum rule
        |                                  |
        +-------------------------------> Alert (database)
                                             |
                                      FastAPI dashboard
                                             |
                                      PaperTrade journal
```

The process is intentionally a single deployable service in v0.1. This keeps the data path inspectable on a home PC. The code boundaries already separate market data, features, strategy, persistence, and HTTP APIs so a later worker split does not require rewriting the strategy.

## Data contract

Every market event has an exchange timestamp and is processed in arrival order. The local order book applies a Bybit snapshot and subsequent price-level deltas. A new snapshot resets the book. A delta with quantity `0` deletes a level.

The first feature set is deliberately small:

- weighted bid/ask imbalance over the first 20 levels;
- spread in basis points;
- microprice and its offset from mid;
- buy/sell volume and delta ratio over three seconds;
- trade intensity;
- rolling 30-second mid-price range;
- visible bid/ask depth.

## Strategy boundary

`app/strategy/orderflow.py` only proposes a signal. It does not place orders. Risk sizing, fees, expiry, and paper execution remain separate concerns. The current rule is a research baseline and must not be described as a validated edge.

## Tiger.com boundary

Tiger.com is treated as a visual execution terminal and manual-control surface. Public product documentation confirms DOM, trade feed, alerts, and crypto exchange connections, but this application does not depend on an undocumented Tiger protocol for market data. The market source of truth is the direct exchange stream. A future integration may open the same symbol in Tiger through its documented local link mechanism, but it must remain optional and must never be the only risk control.

## Storage evolution

SQLite is the default for a first local run. Docker Compose uses PostgreSQL. Before collecting large raw streams, add a retention policy and Parquet/ClickHouse archival plan. Do not store every raw update indefinitely in the transactional database.

## Planned increments

1. Add exchange instrument metadata and exact tick/lot rounding.
2. Add paper position monitoring against live prices with stop/target/timeout exits.
3. Add Telegram and Windows notifications.
4. Add authenticated dashboard access when remote access is needed.
5. Add walk-forward datasets and model versioning.
6. Add a separately reviewed live executor only after paper validation.
