# Crypto Orderflow

Private, paper-only order-flow analytics and alerting platform for crypto markets.

The first slice connects to Bybit public linear-market WebSocket streams, maintains a local L2 order book, calculates transparent order-flow features, generates experimental alerts, and records paper trades through a local web dashboard.

**Real order execution is not implemented.** `LIVE_TRADING_ENABLED=false` is a hard product boundary for this version. Do not add exchange write permissions until the paper engine, tests, and risk controls have been independently validated.

## Scope of v0.1

- Bybit linear public WebSocket: order book and public trades.
- BTCUSDT and ETHUSDT by default.
- Weighted order-book imbalance, microprice, spread, trade delta, trade intensity, and short-term volatility.
- Rule-based Order-Flow Momentum signal prototype.
- Alert history and paper-trade journal.
- FastAPI JSON API and a small browser dashboard.
- SQLite for local development; PostgreSQL service in Docker Compose.
- Tests for order-book reconstruction, features, strategy, and paper PnL.
- **Quantitative stack:** NumPy for vectorized calculations, CatBoost for meta-labeling, Parquet for feature archives.

This is research software, not financial advice and not a profit guarantee. A signal score is a screening value, not a probability until it has been calibrated against out-of-sample data.

## Architecture: quantitative stack instead of deep learning

The system uses **fast gradient boosting (CatBoost)** instead of neural networks, because:

- CatBoost predicts in microseconds on CPU, no GPU required;
- it works better with tabular financial data;
- it rarely overfits on market noise;
- rule-based strategy generates candidates, CatBoost filters weak ones (meta-labeling).

**NumPy** handles all vector calculations in compiled C speed. **Parquet** stores feature history in compressed columnar format (10–100× faster than CSV). **ClickHouse** is documented for future scale (hundreds of symbols), but not required for v0.1.

See [docs/ml.md](docs/ml.md) for the full training pipeline.

## Local run on D:

Clone the repository into a folder on `D:`. The project does not require writing to `C:`.

```powershell
New-Item -ItemType Directory -Force D:\Projects
Set-Location D:\Projects
git clone https://github.com/HIZUFU/crypto-orderflow.git
Set-Location crypto-orderflow

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
Copy-Item .env.example .env
New-Item -ItemType Directory -Force data

pytest
ruff check .
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Docker run

Configure Docker Desktop to keep its disk image on `D:` before starting it.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The Compose profile uses PostgreSQL and starts the app at `http://127.0.0.1:8000`.

## Tests

```powershell
pytest
ruff check .
```

## ML training workflow

After collecting paper trades for several days:

```powershell
pip install -e ".[ml]"
python -m app.ml.export
python -m app.ml.train
```

This exports alerts/trades to Parquet, trains a CatBoost model, and saves it to `data/models/signal_filter.cbm`. Enable the filter with `USE_ML_FILTER=true` in `.env` and restart.

Details: [docs/ml.md](docs/ml.md)

## Repository boundaries

- Never commit `.env`, exchange secrets, Telegram tokens, database dumps, raw market archives, or account screenshots.
- Public market streams need no private API key.
- Future account access must use a dedicated key with no withdrawals, transfers, or account-management permissions.
- This repository currently has no live order endpoint or live execution adapter.

See [docs/setup.md](docs/setup.md), [docs/architecture.md](docs/architecture.md), [docs/security.md](docs/security.md), [docs/fees.md](docs/fees.md), and [docs/ml.md](docs/ml.md).
