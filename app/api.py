import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Alert, AlertOutcome, PaperTrade, Watchlist, utc_now
from app.db.session import get_session
from app.exchanges import EXCHANGES
from app.ml.filter import FEATURE_COLUMNS

router = APIRouter(prefix="/api")
settings = get_settings()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _features(alert: Alert) -> dict:
    try:
        return json.loads(alert.features_json or "{}")
    except json.JSONDecodeError:
        return {}


def _current_prices(request: Request) -> dict[str, float]:
    service = request.app.state.market_service
    return {
        symbol: float(features["mid_price"])
        for symbol, features in service.latest.items()
        if features.get("mid_price") is not None
    }


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
    unrealized = _trade_pnl(trade, current_price) if trade.status == "open" else None
    return {
        "id": trade.id,
        "alert_id": trade.alert_id,
        "symbol": trade.symbol,
        "direction": trade.direction,
        "status": trade.status,
        "opened_at": trade.opened_at.isoformat(),
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "current_price": current_price if trade.status == "open" else None,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "notional": trade.notional,
        "leverage": trade.leverage,
        "fees": trade.fees,
        "pnl": trade.pnl,
        "unrealized_pnl": unrealized,
        "exit_reason": trade.exit_reason,
    }


def alert_json(alert: Alert, outcome: AlertOutcome | None = None) -> dict:
    now = utc_now()
    expires_at = _aware(alert.expires_at)
    remaining = max(0.0, (expires_at - now).total_seconds())
    return {
        "id": alert.id,
        "created_at": _aware(alert.created_at).isoformat(),
        "expires_at": expires_at.isoformat(),
        "remaining_seconds": remaining,
        "expired": remaining <= 0,
        "symbol": alert.symbol,
        "market": alert.market,
        "exchange": alert.exchange,
        "direction": alert.direction,
        "status": alert.status,
        "outcome_type": alert.outcome_type,
        "entry_low": alert.entry_low,
        "entry_high": alert.entry_high,
        "reference_price": alert.reference_price,
        "stop_loss": alert.stop_loss,
        "take_profit": alert.take_profit,
        "risk_amount": alert.risk_amount,
        "position_notional": alert.position_notional,
        "leverage": alert.leverage,
        "score": alert.score,
        "reason": alert.reason,
        "features": _features(alert),
        "ml_probability": alert.ml_probability,
        "ml_passed_filter": alert.ml_passed_filter,
        "outcome": outcome_json(outcome) if outcome else None,
    }


def outcome_json(outcome: AlertOutcome | None) -> dict | None:
    if outcome is None:
        return None
    return {
        "id": outcome.id,
        "outcome_type": outcome.outcome_type,
        "outcome_timestamp": _aware(outcome.outcome_timestamp).isoformat(),
        "paper_trade_id": outcome.paper_trade_id,
        "time_to_action_seconds": outcome.time_to_action_seconds,
        "price_at_outcome": outcome.price_at_outcome,
        "hypothetical_pnl": outcome.hypothetical_pnl,
        "reached_target": outcome.reached_target,
        "hit_stop": outcome.hit_stop,
        "ml_probability": outcome.ml_probability,
        "ml_passed_filter": outcome.ml_passed_filter,
    }


async def latest_outcomes(alert_ids: list[int], session: AsyncSession) -> dict[int, AlertOutcome]:
    if not alert_ids:
        return {}
    result = await session.execute(
        select(AlertOutcome)
        .where(AlertOutcome.alert_id.in_(alert_ids))
        .order_by(desc(AlertOutcome.created_at))
    )
    latest: dict[int, AlertOutcome] = {}
    for outcome in result.scalars():
        latest.setdefault(outcome.alert_id, outcome)
    return latest


@router.get("/health")
async def health(request: Request) -> dict:
    service = request.app.state.market_service
    model_path = Path(settings.ml_model_path)
    return {
        "status": "ok",
        "mode": settings.trading_mode,
        "live_trading_enabled": settings.live_trading_enabled,
        "exchange": service.exchange.name,
        "symbols": settings.tracked_symbols,
        "stream_connected": bool(service._task and not service._task.done()),
        "books_ready": {symbol: book.ready for symbol, book in service.books.items()},
        "ml_filter": {
            "enabled": settings.use_ml_filter,
            "model_exists": model_path.exists(),
            "active": bool(service.ml_filter and service.ml_filter.model),
            "threshold": settings.ml_threshold,
        },
    }


@router.get("/exchanges")
async def exchanges() -> dict:
    return {"current": settings.default_exchange, "available": list(EXCHANGES)}


@router.get("/market")
async def market(request: Request) -> dict:
    service = request.app.state.market_service
    return {"exchange": service.exchange.name, "symbols": service.latest}


@router.get("/orderbook/{symbol}")
async def orderbook(symbol: str, request: Request, levels: int = 20) -> dict:
    service = request.app.state.market_service
    symbol = symbol.upper()
    levels = min(max(levels, 1), 50)
    book = service.books.get(symbol)
    if book is None:
        raise HTTPException(status_code=404, detail="symbol not tracked")
    if not book.ready:
        raise HTTPException(status_code=503, detail="order book is not ready")
    bids, asks = book.top(levels)
    best = book.best_bid_ask()
    return {
        "symbol": symbol,
        "exchange": service.exchange.name,
        "ready": book.ready,
        "timestamp_ms": book.exchange_timestamp_ms,
        "bids": [{"price": float(level.price), "size": float(level.quantity)} for level in bids],
        "asks": [{"price": float(level.price), "size": float(level.quantity)} for level in asks],
        "best_bid": float(best[0].price) if best else None,
        "best_ask": float(best[1].price) if best else None,
    }


@router.get("/candles/{symbol}")
async def candles(symbol: str, request: Request, timeframe: str = "1m", limit: int = 200) -> dict:
    service = request.app.state.market_service
    symbol = symbol.upper()
    aggregator = service.candles.get(symbol)
    if aggregator is None:
        raise HTTPException(status_code=404, detail="symbol not tracked")
    try:
        values = aggregator.get_candles(timeframe, min(max(limit, 1), 500))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"symbol": symbol, "exchange": service.exchange.name, "timeframe": timeframe, "candles": values}


@router.get("/alerts")
async def alerts(limit: int = 100, session: AsyncSession = Depends(get_session)) -> list[dict]:
    result = await session.execute(select(Alert).order_by(desc(Alert.created_at)).limit(min(max(limit, 1), 500)))
    values = list(result.scalars())
    outcomes = await latest_outcomes([alert.id for alert in values], session)
    return [alert_json(alert, outcomes.get(alert.id)) for alert in values]


@router.get("/alerts/analytics")
async def alert_analytics(session: AsyncSession = Depends(get_session)) -> dict:
    result = await session.execute(select(Alert))
    alerts_list = list(result.scalars())
    outcome_result = await session.execute(select(AlertOutcome))
    outcomes = list(outcome_result.scalars())
    by_type: dict[str, int] = {}
    for outcome in outcomes:
        by_type[outcome.outcome_type] = by_type.get(outcome.outcome_type, 0) + 1
    realized = [outcome for outcome in outcomes if outcome.outcome_type in {"take_profit", "stop_loss", "manual"}]
    hypothetical = [outcome.hypothetical_pnl for outcome in outcomes if outcome.hypothetical_pnl is not None]
    return {
        "total_alerts": len(alerts_list),
        "pending": sum(alert.outcome_type == "pending" for alert in alerts_list),
        "by_outcome": by_type,
        "conversion_rate": by_type.get("paper_opened", 0) / len(alerts_list) if alerts_list else 0.0,
        "realized_alerts": len(realized),
        "hypothetical_pnl": sum(hypothetical),
        "hypothetical_positive_rate": sum(value > 0 for value in hypothetical) / len(hypothetical) if hypothetical else 0.0,
    }


@router.get("/alerts/{alert_id}")
async def alert_detail(alert_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    outcomes = await latest_outcomes([alert.id], session)
    trade_result = await session.execute(select(PaperTrade).where(PaperTrade.alert_id == alert.id).order_by(desc(PaperTrade.opened_at)))
    return {"alert": alert_json(alert, outcomes.get(alert.id)), "trades": [trade_json(trade) for trade in trade_result.scalars()]}


@router.post("/alerts/{alert_id}/skip")
async def skip_alert(alert_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status == "paper_opened":
        raise HTTPException(status_code=409, detail="alert already opened")
    if alert.outcome_type != "pending":
        raise HTTPException(status_code=409, detail="alert already has an outcome")
    alert.status = "skipped"
    alert.outcome_type = "manual_skip"
    session.add(AlertOutcome(alert_id=alert.id, outcome_type="manual_skip", ml_probability=alert.ml_probability, ml_passed_filter=alert.ml_passed_filter))
    await session.commit()
    return alert_json(alert)


@router.post("/alerts/{alert_id}/paper", status_code=201)
async def open_paper_trade(alert_id: int, request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if _aware(alert.expires_at) <= utc_now():
        raise HTTPException(status_code=409, detail="alert is expired; only active alerts can be opened")
    if alert.status != "new" or alert.outcome_type != "pending":
        raise HTTPException(status_code=409, detail="alert already has an action")
    trade = PaperTrade(alert_id=alert.id, symbol=alert.symbol, direction=alert.direction, entry_price=alert.reference_price, stop_loss=alert.stop_loss, take_profit=alert.take_profit, notional=alert.position_notional, leverage=alert.leverage)
    session.add(trade)
    await session.flush()
    alert.status = "paper_opened"
    alert.outcome_type = "paper_opened"
    opened_at = utc_now()
    session.add(AlertOutcome(alert_id=alert.id, paper_trade_id=trade.id, outcome_type="paper_opened", outcome_timestamp=opened_at, time_to_action_seconds=max(0.0, (opened_at - _aware(alert.created_at)).total_seconds()), price_at_outcome=alert.reference_price, ml_probability=alert.ml_probability, ml_passed_filter=alert.ml_passed_filter))
    await session.commit()
    await session.refresh(trade)
    return trade_json(trade, _current_prices(request).get(trade.symbol))


@router.get("/paper-trades")
async def paper_trades(request: Request, limit: int = 100, status: str | None = None, session: AsyncSession = Depends(get_session)) -> list[dict]:
    query = select(PaperTrade).order_by(desc(PaperTrade.opened_at)).limit(min(max(limit, 1), 500))
    if status:
        query = select(PaperTrade).where(PaperTrade.status == status).order_by(desc(PaperTrade.opened_at)).limit(min(max(limit, 1), 500))
    result = await session.execute(query)
    prices = _current_prices(request)
    return [trade_json(trade, prices.get(trade.symbol)) for trade in result.scalars()]


@router.post("/paper-trades/{trade_id}/close")
async def close_paper_trade(trade_id: int, payload: dict, request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    trade = await session.get(PaperTrade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="paper trade not found")
    if trade.status != "open":
        raise HTTPException(status_code=409, detail="paper trade is already closed")
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
    result = await session.execute(select(AlertOutcome).where(AlertOutcome.paper_trade_id == trade.id).order_by(desc(AlertOutcome.created_at)))
    outcome = result.scalars().first()
    if outcome:
        outcome.outcome_type = trade.exit_reason or "manual"
        outcome.outcome_timestamp = trade.closed_at
        outcome.price_at_outcome = exit_price
    await session.commit()
    return trade_json(trade, _current_prices(request).get(trade.symbol))


@router.get("/stats/pnl")
async def pnl_stats(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    result = await session.execute(select(PaperTrade).order_by(PaperTrade.closed_at))
    trades = list(result.scalars())
    prices = _current_prices(request)
    closed = [trade for trade in trades if trade.status == "closed" and trade.pnl is not None]
    open_trades = [trade for trade in trades if trade.status == "open"]
    realized = sum(float(trade.pnl) for trade in closed)
    unrealized = sum(_trade_pnl(trade, prices.get(trade.symbol)) or 0.0 for trade in open_trades)
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
        "initial_balance": settings.initial_paper_balance,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "equity": equity + unrealized,
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses else 0.0,
        "max_drawdown": max_drawdown,
        "curve": curve,
    }


@router.get("/watchlist")
async def get_watchlist(session: AsyncSession = Depends(get_session)) -> list[dict]:
    result = await session.execute(select(Watchlist).where(Watchlist.enabled.is_(True)).order_by(desc(Watchlist.priority), Watchlist.symbol))
    return [{"id": item.id, "exchange": item.exchange, "symbol": item.symbol, "priority": item.priority, "notes": item.notes} for item in result.scalars()]


@router.post("/watchlist", status_code=201)
async def add_watchlist(payload: dict, session: AsyncSession = Depends(get_session)) -> dict:
    symbol = str(payload.get("symbol", "")).strip().upper()
    exchange = str(payload.get("exchange", settings.default_exchange)).strip().lower()
    if not symbol or exchange not in EXCHANGES:
        raise HTTPException(status_code=422, detail="valid symbol and exchange are required")
    existing = await session.execute(select(Watchlist).where(Watchlist.symbol == symbol, Watchlist.exchange == exchange))
    item = existing.scalars().first()
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
async def ml_status(session: AsyncSession = Depends(get_session)) -> dict:
    model_path = Path(settings.ml_model_path)
    result = await session.execute(select(PaperTrade).where(PaperTrade.status == "closed"))
    closed = list(result.scalars())
    outcome_result = await session.execute(select(AlertOutcome))
    outcomes = list(outcome_result.scalars())
    return {
        "enabled": settings.use_ml_filter,
        "active": model_path.exists() and settings.use_ml_filter,
        "model_path": str(model_path),
        "model_exists": model_path.exists(),
        "threshold": settings.ml_threshold,
        "feature_columns": FEATURE_COLUMNS,
        "closed_trades": len(closed),
        "wins": sum(bool(trade.pnl and trade.pnl > 0) for trade in closed),
        "losses": sum(bool(trade.pnl is not None and trade.pnl <= 0) for trade in closed),
        "outcomes": len(outcomes),
        "training_ready": len(closed) >= 50,
    }
