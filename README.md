# Orderflow Lab v1.0

Paper-only order-flow analytics with a live market dashboard, alert journal, chart workspace, paper PnL and CatBoost research pipeline.

## What Is Included

- Public Bybit linear WebSocket for L2 order book and public trades.
- Exchange adapter boundary for Bybit and Binance market streams.
- Transparent features: weighted book imbalance, microprice, spread, trade delta, intensity and log-return volatility.
- Rule-based LONG/SHORT candidates with explicit evidence, risk, stop and target.
- Paper execution only with automatic stop/target closure and live unrealized PnL.
- Alert journal: every alert is tracked as pending, opened, skipped, expired or completed.
- Hypothetical mark-to-market result for alerts that expired without a paper trade.
- Chart workspace with candles, alert markers, order book depth and feature snapshot.
- PnL analytics with realized/unrealized PnL, win rate, profit factor, drawdown and equity curve.
- CatBoost meta-labeling pipeline with a shared train/inference feature contract.
- Local SQLite schema migration so an existing `data/orderflow.db` is upgraded on startup.

Real order execution is intentionally unavailable. `TRADING_MODE=paper` and `LIVE_TRADING_ENABLED=false` remain product boundaries. Public market data does not require exchange API keys.

## Run On D:

```powershell
cd D:\Projects
Remove-Item -Recurse -Force .\crypto-orderflow -ErrorAction SilentlyContinue
git clone https://github.com/HIZUFU/crypto-orderflow.git
cd .\crypto-orderflow

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The startup migration preserves existing alerts and trades. Do not delete `data/orderflow.db` unless you intentionally want a fresh paper journal.

## Pages

- `/` - Trading desk with live market pressure, active alerts and open paper positions.
- `/chart.html` - Candles, order book depth, feature snapshot and alert markers.
- `/alerts.html` - Full alert journal with filters and detail reports.
- `/pnl.html` - Paper PnL, equity curve and trade journal.
- `/ml.html` - CatBoost model status and training readiness.
- `/settings.html` - Runtime settings and watchlist management.

## API Checks

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/market
Invoke-RestMethod http://127.0.0.1:8000/api/orderbook/BTCUSDT
Invoke-RestMethod http://127.0.0.1:8000/api/alerts/analytics
Invoke-RestMethod http://127.0.0.1:8000/api/stats/pnl
Invoke-RestMethod http://127.0.0.1:8000/api/ml/status
```

## Alert And PnL Workflow

1. Wait for `books_ready` to show `2/2` and for the feed to produce a candidate.
2. Open a currently active alert with `Open paper`. Expired alerts are deliberately blocked.
3. The alert detail report stores the feature snapshot, reason, rule score, ML probability, entry, stop and target.
4. The position closes automatically at stop/target or can be closed manually.
5. `/alerts.html` records the action event and final result.
6. `/pnl.html` includes only paper trades opened from issued alerts.

## CatBoost Workflow

Collect at least 50 closed paper trades first:

```powershell
python -m app.ml.export
python -m app.ml.train
```

The training command uses completed trades only, keeps a time-ordered holdout, reports accuracy/AUC and writes `data/models/signal_filter.cbm`. Enable only after reviewing the out-of-sample result:

```text
USE_ML_FILTER=true
ML_THRESHOLD=0.55
```

CatBoost is a meta-label filter for rule candidates, not a neural network and not a guarantee of profitable predictions. The model must be retrained when the strategy, symbols, features or risk model changes.

## Verification

```powershell
python -m pytest
python -m ruff check .
```

The repository intentionally ignores `.venv/`, `*.egg-info/`, `data/` and `.env`.
