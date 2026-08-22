# Orderflow Lab v1.1

Paper-only order-flow analytics with a multi-exchange market dashboard, source-aware alert journal, paper PnL and CatBoost research pipeline.

## Included

- Public Bybit and Binance adapters for spot and linear futures market data.
- Multiple saved connections, each with its own exchange, market type and symbol list.
- Public WebSocket streams without API keys, independent order books and feature engines per source.
- Settings UI for connections, symbols, paper balance, position notional, risk mode, alert lifetime and ML threshold.
- Optional local encrypted storage for API key and secret fields. Credentials are masked in API responses and are not used for orders or private account requests in this release.
- Transparent features: weighted book imbalance, microprice, spread, trade delta, intensity and volatility.
- Rule-based LONG/SHORT candidates with explicit evidence, risk, stop and target.
- Paper execution only with automatic stop/target closure and live unrealized PnL.
- Alert journal: every alert is tracked as pending, opened, skipped, expired or completed and can be filtered by source.
- PnL analytics with realized/unrealized PnL, win rate, profit factor, drawdown and source-aware trade journal.
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

Open `http://127.0.0.1:8000`. The startup migration preserves existing alerts and trades. Do not delete `data/orderflow.db` unless a fresh paper journal is intentional.

## Settings Workflow

Open `/settings.html` and use:

- `Overview` for stream, source, order book and CatBoost status.
- `API / Connections` to add Bybit or Binance, choose `Spot` or `Futures / linear`, enter comma-separated symbols, enable/disable a connection or edit/delete it.
- `Paper & Risk` to change paper balance, position notional, percent-of-notional risk or fixed-USDT risk, reward/risk ratio, alert lifetime and the ML threshold.

Connections reload public streams after every save. A custom connection source is identified by `connection_id:SYMBOL`, so the same symbol on two exchanges remains isolated in charts, alerts, paper pricing and PnL.

Credentials are optional. They are encrypted with the local `APP_SECRET_KEY`, never returned in plaintext and currently serve only as preparation for a future read-only private account adapter. Do not paste them into chat.

## Pages

- `/` - Trading desk with live market pressure, source labels, active alerts and open paper positions.
- `/chart.html` - Source selector, candles, order book depth, feature snapshot and source-filtered alert markers.
- `/alerts.html` - Full alert journal with source, symbol, direction and outcome filters.
- `/pnl.html` - Paper PnL, equity curve and source-aware trade journal.
- `/ml.html` - CatBoost model status and training readiness.
- `/settings.html` - Connections, runtime paper controls and ML toggle.

## API Checks

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/market
Invoke-RestMethod http://127.0.0.1:8000/api/connections
Invoke-RestMethod http://127.0.0.1:8000/api/settings
Invoke-RestMethod http://127.0.0.1:8000/api/alerts/analytics
Invoke-RestMethod http://127.0.0.1:8000/api/stats/pnl
Invoke-RestMethod http://127.0.0.1:8000/api/ml/status
```

## CatBoost And `model missing`

`model missing` means `data/models/signal_filter.cbm` has not been created yet. The file appears only after at least 50 closed paper trades, export and training:

```powershell
python -m app.ml.export
python -m app.ml.train
```

The training command uses completed trades, keeps a time-ordered holdout, reports accuracy/AUC and writes the model. Enable it from Settings or with `USE_ML_FILTER=true` after reviewing the out-of-sample result. `ML_THRESHOLD=0.55` is the default gate.

CatBoost is a meta-label filter, not a price predictor. The rule engine first creates a candidate. When the model is loaded and `ml_probability < ML_THRESHOLD`, the candidate is rejected and no Alert row is created. When the model is missing or disabled, rule-based candidates continue and their ML probability remains empty. Rule score and ML probability are separate values in the alert report.

## Verification

```powershell
python -m pytest
python -m ruff check .
```

The repository intentionally ignores `.venv/`, `*.egg-info/`, `data/` and `.env`. Local tests and live exchange WebSocket scenarios must be run on the D: machine; they were not executed in this agent session.
