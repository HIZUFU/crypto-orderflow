import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Alert, AlertOutcome, ExchangeConnection, PaperTrade, Watchlist, utc_now
from app.db.session import get_session, save_runtime_settings
from app.exchanges import EXCHANGES
from app.ml.filter import FEATURE_COLUMNS
from app.security import decrypt_secret, encrypt_secret, mask_secret

router = APIRouter(prefix="/api")
settings = get_settings()
RUNTIME_KEYS = {
    "initial_paper_balance", "paper_notional_usdt", "risk_mode", "risk_value",
    "reward_risk_ratio", "signal_ttl_seconds", "ml_threshold", "use_ml_filter",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _features(alert: Alert) -> dict:
    try:
        return json.loads(alert.features_json or "{}")
    except json.JSONDecodeError:
        return {}


def _prices(request: Request) -> dict[str, float]:
    service = request.app.state.market_service
    return {
        key: float(value["mid_price"])
        for key, value in service.latest.items()
        if value.get("mid_price") is not None
    }


def _source_price(request: Request, trade: PaperTrade) -> float | None:
    service = request.app.state.market_service
    source = service.resolve_source(trade.symbol, trade.source_key)
    return _prices(request).get(source) if source else None


def _trade_pnl(trade: PaperTrade, current_price: float | None = None) -> float | None:
    price = trade.exit_price if trade.status == "closed" else current_price
    if price is None:
        return None
    gross = ((price - trade.entry_price) / trade.entry_price) * trade.notional
    if trade.direction == "SHORT":
        gross *= -1
    fees = trade.fees if trade.status == "closed" else trade.notional * settings.paper_fee_rate * 2
    return gross - fees


def trade_json(trade: PaperTrade, current_price: float | None = None) -> dict:
    return {
        "id": trade.id, "alert_id": trade.alert_id, "symbol": trade.symbol,
        "market": trade.market, "exchange": trade.exchange, "source_key": trade.source_key,
        "direction": trade.direction, "status": trade.status,
        "opened_at": _aware(trade.opened_at).isoformat(),
        "closed_at": _aware(trade.closed_at).isoformat() if trade.closed_at else None,
        "entry_price": trade.entry_price, "exit_price": trade.exit_price,
        "current_price": current_price if trade.status == "open" else None,
        "stop_loss": trade.stop_loss, "take_profit": trade.take_profit,
        "notional": trade.notional, "leverage": trade.leverage, "fees": trade.fees,
        "pnl": trade.pnl,
        "unrealized_pnl": _trade_pnl(trade, current_price) if trade.status == "open" else None,
        "exit_reason": trade.exit_reason,
    }


def outcome_json(outcome: AlertOutcome | None) -> dict | None:
    if outcome is None:
        return None
    return {
        "id": outcome.id, "outcome_type": outcome.outcome_type,
        "outcome_timestamp": _aware(outcome.outcome_timestamp).isoformat(),
        "paper_trade_id": outcome.paper_trade_id,
        "time_to_action_seconds": outcome.time_to_action_seconds,
        "price_at_outcome": outcome.price_at_outcome,
        "hypothetical_pnl": outcome.hypothetical_pnl,
        "reached_target": outcome.reached_target, "hit_stop": outcome.hit_stop,
        "ml_probability": outcome.ml_probability, "ml_passed_filter": outcome.ml_passed_filter,
    }


def alert_json(alert: Alert, outcome: AlertOutcome | None = None) -> dict:
    expires_at = _aware(alert.expires_at)
    return {
        "id": alert.id, "created_at": _aware(alert.created_at).isoformat(),
        "expires_at": expires_at.isoformat(),
        "remaining_seconds": max(0.0, (expires_at - utc_now()).total_seconds()),
        "expired": expires_at <= utc_now(), "symbol": alert.symbol, "market": alert.market,
        "exchange": alert.exchange, "source_key": alert.source_key,
        "connection_id": alert.connection_id, "direction": alert.direction,
        "status": alert.status, "outcome_type": alert.outcome_type,
        "entry_low": alert.entry_low, "entry_high": alert.entry_high,
        "reference_price": alert.reference_price, "stop_loss": alert.stop_loss,
        "take_profit": alert.take_profit, "risk_amount": alert.risk_amount,
        "position_notional": alert.position_notional, "leverage": alert.leverage,
        "score": alert.score, "reason": alert.reason, "features": _features(alert),
        "ml_probability": alert.ml_probability, "ml_passed_filter": alert.ml_passed_filter,
        "outcome": outcome_json(outcome),
    }


async def latest_outcomes(ids: list[int], session: AsyncSession) -> dict[int, AlertOutcome]:
    if not ids:
        return {}
    result = await session.execute(
        select(AlertOutcome).where(AlertOutcome.alert_id.in_(ids)).order_by(desc(AlertOutcome.created_at))
    )
    latest: dict[int, AlertOutcome] = {}
    for outcome in result.scalars():
        latest.setdefault(outcome.alert_id, outcome)
    return latest


def _masked_credential(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return mask_secret(decrypt_secret(ciphertext))
    except InvalidToken:
        return "unavailable"


def connection_json(connection: ExchangeConnection) -> dict:
    return {
        "id": connection.id, "label": connection.label, "provider": connection.provider,
        "market_type": connection.market_type, "symbols": json.loads(connection.symbols_json or "[]"),
        "enabled": connection.enabled, "ws_url": connection.ws_url,
        "has_api_key": bool(connection.api_key_ciphertext),
        "api_key_masked": _masked_credential(connection.api_key_ciphertext),
        "has_api_secret": bool(connection.api_secret_ciphertext),
        "api_secret_masked": _masked_credential(connection.api_secret_ciphertext),
        "created_at": _aware(connection.created_at).isoformat(),
    }


def _connection_payload(payload: dict) -> tuple[str, str, list[str]]:
    provider = str(payload.get("provider", "")).lower()
    market_type = str(payload.get("market_type", "linear")).lower()
    if market_type == "futures":
        market_type = "linear"
    raw_symbols = payload.get("symbols", [])
    if isinstance(raw_symbols, str):
        raw_symbols = raw_symbols.split(",")
    symbols = sorted({str(value).strip().upper() for value in raw_symbols if str(value).strip()})
    if provider not in EXCHANGES:
        raise HTTPException(status_code=422, detail=f"provider must be one of: {', '.join(EXCHANGES)}")
    if market_type not in {"spot", "linear"}:
        raise HTTPException(status_code=422, detail="market_type must be spot or futures")
    if not symbols:
        raise HTTPException(status_code=422, detail="at least one symbol is required")
    return provider, market_type, symbols


@router.get("/health")
async def health(request: Request) -> dict:
    service = request.app.state.market_service
    model_path = Path(settings.ml_model_path)
    return {
        "status": "ok", "mode": settings.trading_mode,
        "live_trading_enabled": settings.live_trading_enabled, "exchange": settings.default_exchange,
        "symbols": settings.tracked_symbols, "stream_connected": service.stream_connected,
        "sources": list(service.sources.values()),
        "books_ready": {key: book.ready for key, book in service.books.items()},
        "ml_filter": {
            "enabled": settings.use_ml_filter, "model_exists": model_path.exists(),
            "active": bool(service.ml_filter and service.ml_filter.model),
            "threshold": settings.ml_threshold,
        },
    }


@router.get("/settings")
async def get_settings_state() -> dict:
    return {
        "paper": {
            "initial_paper_balance": settings.initial_paper_balance,
            "paper_notional_usdt": settings.paper_notional_usdt,
            "risk_mode": settings.risk_mode, "risk_value": settings.risk_value,
            "reward_risk_ratio": settings.reward_risk_ratio,
            "signal_ttl_seconds": settings.signal_ttl_seconds,
        },
        "ml": {"enabled": settings.use_ml_filter, "threshold": settings.ml_threshold, "model_path": settings.ml_model_path},
        "security": {
            "trading_mode": settings.trading_mode,
            "live_trading_enabled": settings.live_trading_enabled,
            "public_market_data": True,
        },
    }


@router.patch("/settings")
async def update_settings(payload: dict, request: Request) -> dict:
    values = {key: payload[key] for key in RUNTIME_KEYS if key in payload}
    positive = {
        "initial_paper_balance": "initial paper balance",
        "paper_notional_usdt": "paper position size",
        "risk_value": "risk value",
        "reward_risk_ratio": "reward/risk ratio",
        "signal_ttl_seconds": "signal lifetime",
    }
    try:
        for key, label in positive.items():
            if key in values and float(values[key]) <= 0:
                raise HTTPException(status_code=422, detail=f"{label} must be positive")
        if "risk_mode" in values and values["risk_mode"] not in {"percent_notional", "fixed_usdt"}:
            raise HTTPException(status_code=422, detail="risk_mode must be percent_notional or fixed_usdt")
        if "ml_threshold" in values and not 0 <= float(values["ml_threshold"]) <= 1:
            raise HTTPException(status_code=422, detail="ml threshold must be between 0 and 1")
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="numeric settings must be valid numbers") from error
    if "use_ml_filter" in values:
        values["use_ml_filter"] = _as_bool(values["use_ml_filter"])
    await save_runtime_settings(values, settings)
    if "use_ml_filter" in values:
        request.app.state.market_service.refresh_ml_filter()
    return await get_settings_state()


@router.get("/connections")
async def get_connections(session: AsyncSession = Depends(get_session)) -> list[dict]:
    result = await session.execute(
        select(ExchangeConnection).order_by(
            ExchangeConnection.provider, ExchangeConnection.market_type, ExchangeConnection.label
        )
    )
    return [connection_json(item) for item in result.scalars()]


@router.post("/connections", status_code=201)
async def add_connection(payload: dict, request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    provider, market_type, symbols = _connection_payload(payload)
    item = ExchangeConnection(
        label=str(payload.get("label") or f"{provider} {market_type}")[:64], provider=provider,
        market_type=market_type, ws_url=payload.get("ws_url") or None,
        symbols_json=json.dumps(symbols), enabled=_as_bool(payload.get("enabled", True)),
        api_key_ciphertext=encrypt_secret(payload.get("api_key")),
        api_secret_ciphertext=encrypt_secret(payload.get("api_secret")),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await request.app.state.market_service.reload_connections()
    return connection_json(item)


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: int, payload: dict, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    item = await session.get(ExchangeConnection, connection_id)
    if item is None:
        raise HTTPException(status_code=404, detail="connection not found")
    if "provider" in payload or "market_type" in payload or "symbols" in payload:
        merged = {
            "provider": payload.get("provider", item.provider),
            "market_type": payload.get("market_type", item.market_type),
            "symbols": payload.get("symbols", json.loads(item.symbols_json or "[]")),
        }
        provider, market_type, symbols = _connection_payload(merged)
        item.provider = provider
        item.market_type = market_type
        item.symbols_json = json.dumps(symbols)
    if "label" in payload:
        label = str(payload["label"]).strip()
        if not label:
            raise HTTPException(status_code=422, detail="label is required")
        item.label = label[:64]
    if "ws_url" in payload:
        item.ws_url = payload["ws_url"] or None
    if "enabled" in payload:
        item.enabled = _as_bool(payload["enabled"])
    if payload.get("api_key"):
        item.api_key_ciphertext = encrypt_secret(payload["api_key"])
    if payload.get("api_secret"):
        item.api_secret_ciphertext = encrypt_secret(payload["api_secret"])
    await session.commit()
    await session.refresh(item)
    await request.app.state.market_service.reload_connections()
    return connection_json(item)


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    item = await session.get(ExchangeConnection, connection_id)
    if item is None:
        raise HTTPException(status_code=404, detail="connection not found")
    await session.delete(item)
    await session.commit()
    await request.app.state.market_service.reload_connections()
    return {"status": "removed"}


@router.get("/exchanges")
async def exchanges() -> dict:
    return {"available": list(EXCHANGES)}


@router.get("/market")
async def market(request: Request) -> dict:
    service = request.app.state.market_service
    values = {key: {**info, "features": service.latest.get(key, {})} for key, info in service.sources.items()}
    return {"sources": values}


@router.get("/orderbook/{symbol}")
async def orderbook(
    symbol: str, request: Request, source_key: str | None = None, levels: int = 20
) -> dict:
    service = request.app.state.market_service
    key = service.resolve_source(symbol.upper(), source_key)
    if key is None or key not in service.books:
        raise HTTPException(status_code=404, detail="symbol or source not tracked")
    book = service.books[key]
    if not book.ready:
        raise HTTPException(status_code=503, detail="order book is not ready")
    bids, asks = book.top(min(max(levels, 1), 50))
    best = book.best_bid_ask()
    return {
        **service.sources[key], "ready": True, "timestamp_ms": book.exchange_timestamp_ms,
        "bids": [{"price": float(x.price), "size": float(x.quantity)} for x in bids],
        "asks": [{"price": float(x.price), "size": float(x.quantity)} for x in asks],
        "best_bid": float(best[0].price) if best else None,
        "best_ask": float(best[1].price) if best else None,
    }


@router.get("/candles/{symbol}")
async def candles(
    symbol: str, request: Request, source_key: str | None = None, timeframe: str = "1m", limit: int = 200
) -> dict:
    service = request.app.state.market_service
    key = service.resolve_source(symbol.upper(), source_key)
    if key is None or key not in service.candles:
        raise HTTPException(status_code=404, detail="symbol or source not tracked")
    try:
        values = service.candles[key].get_candles(timeframe, min(max(limit, 1), 500))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {**service.sources[key], "timeframe": timeframe, "candles": values}


@router.get("/alerts")
async def alerts(limit: int = 100, session: AsyncSession = Depends(get_session)) -> list[dict]:
    result = await session.execute(select(Alert).order_by(desc(Alert.created_at)).limit(min(max(limit, 1), 500)))
    values = list(result.scalars())
    outcomes = await latest_outcomes([item.id for item in values], session)
    return [alert_json(alert, outcomes.get(alert.id)) for alert in values]


@router.get("/alerts/analytics")
async def alert_analytics(session: AsyncSession = Depends(get_session)) -> dict:
    alerts_list = list((await session.execute(select(Alert))).scalars())
    outcomes = list((await session.execute(select(AlertOutcome))).scalars())
    by_type: dict[str, int] = {}
    for outcome in outcomes:
        by_type[outcome.outcome_type] = by_type.get(outcome.outcome_type, 0) + 1
    hypothetical = [item.hypothetical_pnl for item in outcomes if item.hypothetical_pnl is not None]
    opened = sum(alert.status == "paper_opened" for alert in alerts_list)
    return {
        "total_alerts": len(alerts_list),
        "pending": sum(alert.outcome_type == "pending" for alert in alerts_list),
        "by_outcome": by_type,
        "conversion_rate": opened / len(alerts_list) if alerts_list else 0.0,
        "realized_alerts": sum(item.outcome_type in {"take_profit", "stop_loss", "manual"} for item in outcomes),
        "hypothetical_pnl": sum(hypothetical),
        "hypothetical_positive_rate": sum(item > 0 for item in hypothetical) / len(hypothetical) if hypothetical else 0.0,
    }


@router.get("/alerts/{alert_id}")
async def alert_detail(alert_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    outcomes = await latest_outcomes([alert.id], session)
    trades = list((await session.execute(
        select(PaperTrade).where(PaperTrade.alert_id == alert.id).order_by(desc(PaperTrade.opened_at))
    )).scalars())
    return {"alert": alert_json(alert, outcomes.get(alert.id)), "trades": [trade_json(trade) for trade in trades]}


@router.post("/alerts/{alert_id}/skip")
async def skip_alert(alert_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status == "paper_opened" or alert.outcome_type != "pending":
        raise HTTPException(status_code=409, detail="alert already has an action")
    alert.status = "skipped"
    alert.outcome_type = "manual_skip"
    session.add(AlertOutcome(
        alert_id=alert.id, outcome_type="manual_skip", ml_probability=alert.ml_probability,
        ml_passed_filter=alert.ml_passed_filter,
    ))
    await session.commit()
    return alert_json(alert)


@router.post("/alerts/{alert_id}/paper", status_code=201)
async def open_paper_trade(
    alert_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if _aware(alert.expires_at) <= utc_now():
        raise HTTPException(status_code=409, detail="alert is expired; only active alerts can be opened")
    if alert.status != "new" or alert.outcome_type != "pending":
        raise HTTPException(status_code=409, detail="alert already has an action")
    trade = PaperTrade(
        alert_id=alert.id, symbol=alert.symbol, market=alert.market, exchange=alert.exchange,
        source_key=alert.source_key, direction=alert.direction, entry_price=alert.reference_price,
        stop_loss=alert.stop_loss, take_profit=alert.take_profit,
        notional=alert.position_notional, leverage=alert.leverage,
    )
    session.add(trade)
    await session.flush()
    alert.status = "paper_opened"
    alert.outcome_type = "paper_opened"
    opened_at = utc_now()
    session.add(AlertOutcome(
        alert_id=alert.id, paper_trade_id=trade.id, outcome_type="paper_opened",
        outcome_timestamp=opened_at,
        time_to_action_seconds=max(0.0, (opened_at - _aware(alert.created_at)).total_seconds()),
        price_at_outcome=alert.reference_price, ml_probability=alert.ml_probability,
        ml_passed_filter=alert.ml_passed_filter,
    ))
    await session.commit()
    await session.refresh(trade)
    return trade_json(trade, _source_price(request, trade))


@router.get("/paper-trades")
async def paper_trades(
    request: Request, limit: int = 100, status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    query = select(PaperTrade)
    if status:
        query = query.where(PaperTrade.status == status)
    query = query.order_by(desc(PaperTrade.opened_at)).limit(min(max(limit, 1), 500))
    trades = list((await session.execute(query)).scalars())
    return [trade_json(trade, _source_price(request, trade)) for trade in trades]


@router.post("/paper-trades/{trade_id}/close")
async def close_paper_trade(
    trade_id: int, payload: dict, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    trade = await session.get(PaperTrade, trade_id)
    if trade is None or trade.status != "open":
        raise HTTPException(status_code=409, detail="paper trade is not open")
    try:
        exit_price = float(payload.get("exit_price"))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="exit_price must be a number") from error
    gross = ((exit_price - trade.entry_price) / trade.entry_price) * trade.notional
    if trade.direction == "SHORT":
        gross *= -1
    trade.fees = trade.notional * settings.paper_fee_rate * 2
    trade.pnl = gross - trade.fees
    trade.exit_price = exit_price
    trade.exit_reason = str(payload.get("reason", "manual"))[:32]
    trade.closed_at = utc_now()
    trade.status = "closed"
    alert = await session.get(Alert, trade.alert_id)
    if alert:
        alert.outcome_type = trade.exit_reason or "manual"
        session.add(AlertOutcome(
            alert_id=alert.id, paper_trade_id=trade.id, outcome_type=trade.exit_reason or "manual",
            outcome_timestamp=trade.closed_at, price_at_outcome=exit_price,
            ml_probability=alert.ml_probability, ml_passed_filter=alert.ml_passed_filter,
        ))
    await session.commit()
    return trade_json(trade, _source_price(request, trade))


@router.get("/stats/pnl")
async def pnl_stats(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    trades = list((await session.execute(select(PaperTrade).order_by(PaperTrade.closed_at))).scalars())
    closed = [trade for trade in trades if trade.status == "closed" and trade.pnl is not None]
    opened = [trade for trade in trades if trade.status == "open"]
    realized = sum(float(trade.pnl) for trade in closed)
    unrealized = sum(_trade_pnl(trade, _source_price(request, trade)) or 0.0 for trade in opened)
    wins = [trade for trade in closed if trade.pnl > 0]
    losses = [trade for trade in closed if trade.pnl <= 0]
    gross_wins = sum(trade.pnl for trade in wins)
    gross_losses = abs(sum(trade.pnl for trade in losses))
    equity = settings.initial_paper_balance
    curve = [{"time": utc_now().isoformat(), "equity": equity, "pnl": 0.0}]
    for trade in closed:
        equity += trade.pnl
        curve.append({"time": _aware(trade.closed_at).isoformat(), "equity": equity, "pnl": trade.pnl, "trade_id": trade.id})
    peak = settings.initial_paper_balance
    max_drawdown = 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        max_drawdown = min(max_drawdown, point["equity"] - peak)
    return {
        "initial_balance": settings.initial_paper_balance, "realized_pnl": realized,
        "unrealized_pnl": unrealized, "equity": equity + unrealized,
        "closed_trades": len(closed), "open_trades": len(opened),
        "winning_trades": len(wins), "losing_trades": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses else 0.0,
        "max_drawdown": max_drawdown, "curve": curve,
    }


@router.get("/watchlist")
async def get_watchlist(session: AsyncSession = Depends(get_session)) -> list[dict]:
    items = list((await session.execute(
        select(Watchlist).where(Watchlist.enabled.is_(True)).order_by(desc(Watchlist.priority), Watchlist.symbol)
    )).scalars())
    return [{"id": item.id, "exchange": item.exchange, "symbol": item.symbol, "priority": item.priority, "notes": item.notes} for item in items]


@router.post("/watchlist", status_code=201)
async def add_watchlist(payload: dict, session: AsyncSession = Depends(get_session)) -> dict:
    symbol = str(payload.get("symbol", "")).strip().upper()
    exchange = str(payload.get("exchange", settings.default_exchange)).strip().lower()
    if not symbol or exchange not in EXCHANGES:
        raise HTTPException(status_code=422, detail="valid symbol and exchange are required")
    result = await session.execute(select(Watchlist).where(Watchlist.symbol == symbol, Watchlist.exchange == exchange))
    item = result.scalars().first()
    if item:
        item.enabled = True
    else:
        item = Watchlist(symbol=symbol, exchange=exchange, priority=int(payload.get("priority", 0)), notes=payload.get("notes"))
        session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "symbol": item.symbol, "exchange": item.exchange, "priority": item.priority}


@router.delete("/watchlist/{item_id}")
async def remove_watchlist(item_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(Watchlist, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="watchlist item not found")
    item.enabled = False
    await session.commit()
    return {"status": "removed"}


@router.get("/ml/status")
async def ml_status(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    service = request.app.state.market_service
    model_path = Path(settings.ml_model_path)
    if settings.use_ml_filter and model_path.exists() and not (service.ml_filter and service.ml_filter.model):
        service.refresh_ml_filter()
    closed = list((await session.execute(select(PaperTrade).where(PaperTrade.status == "closed"))).scalars())
    outcomes = list((await session.execute(select(AlertOutcome))).scalars())
    return {
        "enabled": settings.use_ml_filter,
        "active": bool(service.ml_filter and service.ml_filter.model),
        "model_path": str(model_path), "model_exists": model_path.exists(),
        