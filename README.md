# Crypto Orderflow

Private, paper-only order-flow analytics and alerting platform for crypto markets.

## ✨ Key Features (v0.2)

- **Real-time Market Data**: Bybit public WebSocket (order book + trades)
- **Order Flow Analytics**: Imbalance, microprice, delta, spread, volatility
- **Smart Alerts**: Rule-based strategy with configurable thresholds
- **Paper Trading**: Full position tracking with auto-close by stop/target
- **Unrealized PnL**: Live profit/loss tracking for open positions
- **PnL Statistics**: Win rate, profit factor, average win/loss
- **Watchlist Management**: Dynamic symbol tracking via API
- **Extended Models**: Balance tracking and equity curve (prepared for future)

**Real order execution is not implemented.** `LIVE_TRADING_ENABLED=false` is a hard product boundary. Do not add exchange write permissions until the paper engine, tests, and risk controls have been independently validated.

## 🎯 What's New in v0.2

### Backend Improvements
- ✅ **Auto-close positions** by stop-loss/take-profit (every 1 second)
- ✅ **Unrealized PnL** calculation for open trades
- ✅ **Extended config**: risk increased to 50 USDT, TTL to 120s
- ✅ **New endpoints**: `/api/stats/pnl`, `/api/watchlist`
- ✅ **New models**: Balance, Watchlist tables for future features
- ✅ **Enhanced API**: Status filter for trades, current price in response

### Frontend Improvements
- ✅ **Close button** for manual trade exit
- ✅ **Current price** and **unrealized PnL** columns
- ✅ **Improved styling**: button variants, transitions
- ✅ **Better UX**: confirmation dialogs, error handling
- ✅ **Reason display**: full alert reason in table tooltip

## 🚀 Quick Start

### Local Installation on D:

```powershell
New-Item -ItemType Directory -Force D:\Projects
cd D:\Projects

git clone https://github.com/HIZUFU/crypto-orderflow.git
cd crypto-orderflow

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
Copy-Item .env.example .env

# Run tests
pytest

# Start server
uvicorn app.main:app --reload
```

Open browser: `http://127.0.0.1:8000`

### Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

## 📊 API Endpoints

### Market Data
- `GET /api/health` - System status
- `GET /api/market` - Current market features (BTCUSDT, ETHUSDT)

### Alerts
- `GET /api/alerts?limit=50` - Recent alerts
- `POST /api/alerts/{alert_id}/paper` - Open paper trade from alert

### Paper Trading
- `GET /api/paper-trades?status=open` - List trades (filter by status)
- `POST /api/paper-trades/{trade_id}/close` - Manual close
  ```json
  {"exit_price": 77050.0, "reason": "manual"}
  ```

### Statistics
- `GET /api/stats/pnl` - Performance metrics
  ```json
  {
    "total_trades": 42,
    "win_rate": 0.62,
    "total_pnl": 125.50,
    "profit_factor": 2.15
  }
  ```

### Watchlist (Future)
- `GET /api/watchlist` - User symbols
- `POST /api/watchlist` - Add symbol
- `DELETE /api/watchlist/{id}` - Remove symbol

## ⚙️ Configuration

Key settings in `.env`:

```bash
# Increased defaults for realistic testing
PAPER_NOTIONAL_USDT=50        # Was 10
SIGNAL_TTL_SECONDS=120         # Was 8

# Auto-close positions
ENABLE_AUTO_CLOSE=true
POSITION_MONITOR_INTERVAL_SECONDS=1.0

# ML filter (not yet integrated)
USE_ML_FILTER=false
ML_MODEL_PATH=data/models/signal_filter.cbm
```

## 📈 Position Auto-Close

Paper trades automatically close when:
- **LONG**: current_price <= stop_loss OR current_price >= take_profit
- **SHORT**: current_price >= stop_loss OR current_price <= take_profit

Check interval: 1 second (configurable via `POSITION_MONITOR_INTERVAL_SECONDS`)

Disable: `ENABLE_AUTO_CLOSE=false`

## 🧪 Testing

```powershell
# Run all tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Specific test
pytest tests/test_strategy.py -v

# Linting
ruff check .
```

## 🗂️ Project Structure

```
app/
├── api.py              # FastAPI endpoints (extended with stats, watchlist)
├── config.py           # Settings (auto-close, ML filter)
├── main.py
├── db/
│   ├── models.py       # Alert, PaperTrade, Balance, Watchlist
│   └── session.py
├── market/
│   ├── service.py      # WebSocket + position monitor
│   ├── orderbook.py
│   └── features.py
├── strategy/
│   └── orderflow.py    # Rule-based signals
└── ml/                 # ML pipeline (train, filter, export)
    ├── train.py
    ├── filter.py
    └── export.py

static/
├── index.html
├── app.js              # UI with close button, unrealized PnL
└── app.css             # Enhanced styling

tests/                  # Order book, features, strategy, PnL
docs/                   # Architecture, ML, security, fees
```

## 🔮 Roadmap

### Phase 2: Charts & Visualization (Next)
- [ ] Lightweight-charts integration
- [ ] OHLCV aggregation from trades
- [ ] Chart view with alerts overlay
- [ ] Order book heatmap

### Phase 3: Multiple Exchanges
- [ ] Exchange abstraction layer
- [ ] Binance WebSocket adapter
- [ ] Exchange selector in UI
- [ ] Unified symbol format

### Phase 4: Advanced UI
- [ ] PnL dashboard with equity curve
- [ ] Watchlist sidebar with quick stats
- [ ] Alert detail cards with feature breakdown
- [ ] Browser notifications
- [ ] Sound alerts

### Phase 5: ML Integration
- [ ] Connect SignalFilter to MarketService
- [ ] Fix train.py labeling (NaN pnl handling)
- [ ] Live filtering with CatBoost
- [ ] Model performance tracking

## 📝 Notes

- **Quantitative stack**: NumPy + CatBoost + Parquet (not deep learning)
- **Paper only**: No real funds, no exchange API keys required
- **Public data**: Bybit WebSocket needs no authentication
- **SQLite by default**: PostgreSQL in Docker Compose
- **Tests included**: Order book reconstruction, features, strategy, PnL

See:
- [docs/ml.md](docs/ml.md) - ML training pipeline
- [docs/testing.md](docs/testing.md) - Test scenarios
- [docs/architecture.md](docs/architecture.md) - System design
- [docs/security.md](docs/security.md) - Safety boundaries

## 🔒 Security

- Never commit `.env`, API keys, tokens, or database dumps
- Public WebSocket streams only (no private data)
- Future live trading requires read-only API keys (no withdrawals)
- Paper mode is enforced at config level

---

**This is research software, not financial advice.**
