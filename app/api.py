import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Alert, PaperTrade, utc_now
from app.db.session import get_session

router = APIRouter(prefix="/api")
settings = get_settings()


def alert_json(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "created_at": alert.created_at.isoformat(),
        "expires_at": alert.expires_at.isoformat(),
        "symbol": alert.symbol,
        "market": alert.market,
        "direction": alert.direction,
        "status": alert.status,
        "entry_low": alert.entry_low,
        "entry_high": alert.entry_high,
        "reference_price": alert.reference_price,
        "stop_loss": alert.stop_loss,
        "take_profit": alert.take_profit,
        "position_notional": alert.position_notional,
        "leverage": alert.leverage,
        "risk_amount": alert.risk_amount,
        "score": alert.score,
        "reason": alert.reason,
        "features": json.loads(alert.features_json),
    }


def trade_json(trade: PaperTrade, current_price: float | None = None) -> dict:
    result = {
        "id": trade.id,
        "alert_id": trade.alert_id,
        "symbol": trade.symbol,
        "direction": trade.direction,
        "status": trade.status,
        "opened_at": trade.opened_at.isoformat(),
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "notional": trade.notional,
        "leverage": trade.leverage,
        "fees": trade.fees,
        "pnl": trade.pnl,
        "exit_reason": trade.exit_reason,
    }
    
    # Calculate unrealized PnL for open trades
    if trade.status == "open" and current_price is not None:
        gross = ((current_price - trade.entry_price) / trade.entry_price) * trade.notional
        if trade.direction == "SHORT":
            gross *= -1
        fees = trade.notional * settings.paper_fee_rate * 2
        unrealized_pnl = gross - fees
        result["current_price"] = current_price
        result["unrealized_pnl"] = unrealized_pnl
    
    return result


@router.get("/health")
async def health(request: Request) -> dict:
    service = request.app.state.market_service
    return {
        "status": "ok",
        "mode": settings.trading_mode,
        "live_trading_enabled": settings.live_trading_enabled,
        "symbols": settings.tracked_symbols,
        "stream_connected": bool(service._task and not service._task.done()),
        "books_ready": {symbol: book.ready for symbol, book in service.books.items()},
    }


@router.get("/market")
async def market(request: Request) -> dict:
    return request.app.state.market_service.latest


@router.get("/alerts")
async def alerts(limit: int = 50, session: AsyncSession = Depends(get_session)) -> list[dict]:
    limit = min(max(limit, 1), 200)
    result = await session.execute(select(Alert).order_by(desc(Alert.created_at)).limit(limit))
    return [alert_json(alert) for alert in result.scalars()]


@router.post("/alerts/{alert_id}/paper", status_code=201)
async def open_paper_trade(alert_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    now = datetime.now(timezone.utc)
    expires_at = alert.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise HTTPException(status_code=409, detail="alert is expired")
    if alert.status == "paper_opened":
        raise HTTPException(status_code=409, detail="paper trade already opened")
    trade = PaperTrade(
        alert_id=alert.id,
        symbol=alert.symbol,
        direction=alert.direction,
        entry_price=alert.reference_price,
        stop_loss=alert.stop_loss,
        take_profit=alert.take_profit,
        notional=alert.position_notional,
        leverage=alert.leverage,
    )
    alert.status = "paper_opened"
    session.add(trade)
    await session.commit()
    await session.refresh(trade)
    return trade_json(trade)


@router.get("/paper-trades")
async def paper_trades(
    limit: int = 50,
    request: Request | None = None,
    session: AsyncSession = Depends(get_session)
) -> list[dict]:
    limit = min(max(limit, 1), 200)
    result = await session.execute(select(PaperTrade).order_by(desc(PaperTrade.opened_at)).limit(limit))
    trades = list(result.scalars())
    
    # Get current prices for unrealized PnL calculation
    current_prices = {}
    if request:
        service = request.app.state.market_service
        for symbol, features in service.latest.items():
            current_prices[symbol] = features.get("mid_price")
    
    return [trade_json(trade, current_prices.get(trade.symbol)) for trade in trades]


@router.post("/paper-trades/{trade_id}/close")
async def close_paper_trade(trade_id: int, payload: dict, session: AsyncSession = Depends(get_session)) -> dict:
    trade = await session.get(PaperTrade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="paper trade not found")
    if trade.status != "open":
        raise HTTPException(status_code=409, detail="paper trade is already closed")
    try:
        exit_price = float(payload["exit_price"])
    except (KeyError, TypeError, ValueError) as error:
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
    await session.commit()
    return trade_json(trade)
