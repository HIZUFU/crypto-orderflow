# Crypto Orderflow - Final Version

## 🎯 Что готово

### ✅ **Phase 1: Core Infrastructure**
- Автоматическое закрытие paper trades по stop/target
- Unrealized PnL в реальном времени
- Кнопка ручного закрытия позиций
- Увеличен риск (50 USDT) и TTL (120 сек)
- API для статистики `/api/stats/pnl`

### ✅ **Phase 2: Charts & Visualization**
- OHLCV агрегатор (1m, 5m, 15m, 1h)
- Chart View с TradingView lightweight-charts
- PnL Dashboard с equity curve
- Навигация: Dashboard / Charts / PnL

### ✅ **Phase 3: Multi-Exchange**
- Exchange abstraction layer
- Bybit + Binance adapters
- Exchange badge в UI
- API `/api/exchanges`

### ✅ **Phase 4: ML Integration**
- ✅ Исправлен критический баг в `train.py` (NaN labels)
- ✅ ML filter подключён к MarketService
- ✅ ML status в `/api/health`
- ✅ Новый endpoint `/api/orderbook/{symbol}`

---

## 🚀 Быстрый старт

```powershell
cd D:\Projects\crypto-orderflow
git checkout feature/final-polish-and-ml
.\.venv\Scripts\Activate.ps1

# Копировать .env
Copy-Item .env.example .env

# Запустить
uvicorn app.main:app --reload
```

Открыть: `http://127.0.0.1:8000`

---

## 🧠 ML Pipeline

### 1. Сбор данных (автоматически)
Работай с приложением, открывай/закрывай paper trades. Данные сохраняются в БД.

### 2. Экспорт в Parquet
```powershell
python -m app.ml.export
```
Создаёт `data/history/alerts_*.parquet` и `trades_*.parquet`

### 3. Обучение CatBoost
```powershell
python -m app.ml.train
```
Требует минимум 50 закрытых сделок. Создаёт `data/models/signal_filter.cbm`

### 4. Включить фильтр
В `.env`:
```bash
USE_ML_FILTER=true
ML_THRESHOLD=0.55  # Вероятность ≥55% для прохождения
```

### 5. Перезапустить
```powershell
uvicorn app.main:app --reload
```

Теперь алертов будет меньше, но качественнее!

---

## 📊 API Endpoints

### Основные
- `GET /api/health` — статус + ML filter info
- `GET /api/exchanges` — доступные биржи
- `GET /api/market` — текущие признаки (imbalance, delta, etc.)

### Order Book
- `GET /api/orderbook/{symbol}?levels=20` — стакан в реальном времени

### Графики
- `GET /api/candles/{symbol}?timeframe=1m&limit=100` — OHLCV свечи

### Alerts
- `GET /api/alerts?limit=50` — последние алерты
- `POST /api/alerts/{id}/paper` — открыть paper trade

### Trading
- `GET /api/paper-trades?status=open` — открытые позиции
- `POST /api/paper-trades/{id}/close` — закрыть позицию

### Statistics
- `GET /api/stats/pnl` — win rate, profit factor, etc.

---

## ⚙️ Конфигурация

### Биржа
```bash
DEFAULT_EXCHANGE=bybit  # или binance
```

### Символы
```bash
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT  # добавляй через запятую
```

### Риск
```bash
PAPER_NOTIONAL_USDT=50  # номинал на сделку
SIGNAL_TTL_SECONDS=120   # время жизни алерта
```

### ML Filter
```bash
USE_ML_FILTER=false      # true для включения
ML_MODEL_PATH=data/models/signal_filter.cbm
ML_THRESHOLD=0.55        # порог вероятности
```

---

## 📈 Стратегия

### Признаки (Features)
- **imbalance** — дисбаланс bid/ask volume (>0.55 = покупатели сильнее)
- **delta** — разница buy/sell trades за 3 сек
- **microprice** — взвешенная mid цена с учётом глубины
- **spread** — разница bid/ask в bps
- **volatility** — стандартное отклонение цены

### Сигналы
**LONG**:
- imbalance > 0.55
- delta > 0.6
- microprice offset > 0 bps

**SHORT**:
- imbalance < 0.45
- delta < -0.6
- microprice offset < 0 bps

### Risk Management
- Stop loss: 0.5% от entry
- Take profit: 0.3% от entry
- Risk per trade: 0.5% от nominal (фиксированный)

---

## 🧪 Тестирование

### 1. Базовый запуск
```powershell
# Запустить
uvicorn app.main:app --reload

# В другом окне
pytest
```

### 2. Проверить API
```powershell
# Health
Invoke-RestMethod http://127.0.0.1:8000/api/health

# Order book
Invoke-RestMethod http://127.0.0.1:8000/api/orderbook/BTCUSDT

# Статистика
Invoke-RestMethod http://127.0.0.1:8000/api/stats/pnl
```

### 3. Проверить UI
- Dashboard: алерты, позиции, market state
- Charts: график цены, алерты на графике
- PnL: equity curve, статистика

---

## 📚 Математический фундамент

### Order Flow Imbalance
```python
bid_volume = sum(size for price, size in bids[:N])
ask_volume = sum(size for price, size in asks[:N])
imbalance = bid_volume / (bid_volume + ask_volume)
```
Источник: *Market Microstructure in Practice* (Lehalle & Laruelle, 2013)

### Microprice
```python
microprice = (bid_size * ask_price + ask_size * bid_price) / (bid_size + ask_size)
```
Источник: *High Frequency Trading* (Cartea, Jaimungal, Penalva, 2015)

### Trade Delta
```python
delta = buy_volume - sell_volume
delta_ratio = delta / (buy_volume + sell_volume)
```
Источник: *Algorithmic Trading and DMA* (Johnson, 2010)

### Volatility (Exponential Moving)
```python
returns = [log(p2/p1) for p1, p2 in zip(prices[:-1], prices[1:])]
vol = std(returns[-window:])
```

---

## 🔮 Будущие улучшения

### Telegram Bot (Phase 5)
- Push уведомления о новых алертах
- Команды: `/status`, `/pnl`, `/close`
- Управление подпиской

### Order Book Visualization
- Heatmap depth chart
- Real-time updates
- Bid/ask imbalance bars

### API Keys Management
- UI для добавления ключей
- Encrypted storage
- Per-exchange credentials

### i18n Support
- EN/RU интерфейс
- Language switcher
- Tooltips с объяснениями

---

## ⚠️ Важно

### Безопасность
- ✅ Только paper trading (live выключен на уровне кода)
- ✅ Публичные WebSocket (не требуют ключей)
- ✅ Нет записи в exchange (только чтение market data)

### Limitations
- Одна биржа одновременно (требуется перезапуск для смены)
- Свечи в памяти (пропадают при рестарте)
- ML модель нужно переобучать при смене стратегии

---

## 📞 Support

Все изменения в Pull Requests:
- PR #1: Phase 1 - Auto-close & Infrastructure
- PR #2: Phase 2 - Charts & PnL Dashboard  
- PR #3: Phase 3 - Multi-Exchange
- PR #4: Phase 4 - ML Integration & Polish *(текущий)*

**Готово к финальному тестированию!** 🚀
