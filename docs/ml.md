# Machine learning pipeline

This directory contains CatBoost-based meta-labeling components for filtering order-flow signals.

## Workflow

1. **Collect history** — run the application in paper mode for at least several days to accumulate closed trades with outcomes.

2. **Export to Parquet:**
   ```powershell
   python -m app.ml.export
   ```
   This creates `data/history/alerts_YYYYMMDD_HHMMSS.parquet` and `data/history/trades_YYYYMMDD_HHMMSS.parquet`.

3. **Train CatBoost model:**
   ```powershell
   pip install -e ".[ml]"
   python -m app.ml.train
   ```
   This joins alerts with closed trades, labels them as profitable/unprofitable, trains a CatBoostClassifier, and saves `data/models/signal_filter.cbm`.

4. **Enable model in production** — set `USE_ML_FILTER=true` in `.env` and restart the application. The trained model will score every new signal and suppress weak ones.

## Meta-labeling concept

The rule-based strategy (`app/strategy/orderflow.py`) generates candidate signals. The CatBoost model does not replace the strategy; it filters signals by predicting the probability that a given signal will reach its target before stop-loss.

Features used:
- All order-flow features from `FeatureEngine`;
- The rule-based signal score.

Label: `1` if `pnl > 0` after fees, `0` otherwise.

The model threshold is configurable. Higher thresholds reduce false positives but also reduce the number of alerts.

## Why CatBoost instead of neural networks

- CatBoost is fast: predictions take microseconds on CPU.
- It handles tabular financial data better than deep learning.
- It rarely overfits on noisy market data.
- It does not require a GPU.

## Storage: Parquet vs CSV

Parquet is a columnar binary format that is 10–100× faster to read than CSV and uses compression. It is ideal for storing large time-series archives of features and outcomes.

## Future: ClickHouse for large-scale data

When the system tracks hundreds of symbols or stores every order-book update, PostgreSQL will become a bottleneck. At that stage, migrate hot time-series queries to ClickHouse (columnar OLAP database) and keep only transactional data (alerts, trades, user actions) in PostgreSQL.

ClickHouse setup is documented separately and is not required for the first version.
