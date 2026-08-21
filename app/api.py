import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Alert, Balance, PaperTrade, Watchlist, utc_now
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
        "exchange": alert.exchange,
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


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    timeframe: str = "1m",
    limit: int = 100,
    request: Request = None
) -> dict:
    """Get OHLCV candles for a symbol."""
    if request is None:
        raise HTTPException(status_code=500, detail="Request context not available")
    
    service = request.app.state.market_service
    symbol = symbol.upper()
    
    if symbol not in service.candles:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    
    try:
        candles = service.candles[symbol].get_candles(timeframe, limit)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    status: str | None = None,
    request: Request | None = None,
    session: AsyncSession = Depends(get_session)
) -> list[dict]:
    limit = min(max(limit, 1), 200)
    query = select(PaperTrade)
    if status:
        query = query.where(PaperTrade.status == status)
    query = query.order_by(desc(PaperTrade.opened_at)).limit(limit)
    result = await session.execute(query)
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


@router.get("/stats/pnl")
async def pnl_stats(session: AsyncSession = Depends(get_session)) -> dict:
    """Get PnL statistics for paper trading."""
    result = await session.execute(
        select(PaperTrade).where(PaperTrade.status == "closed")
    )
    closed_trades = list(result.scalars())
    
    if not closed_trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
        }
    
    total_trades = len(closed_trades)
    winning_trades = [t for t in closed_trades if t.pnl and t.pnl > 0]
    losing_trades = [t for t in closed_trades if t.pnl and t.pnl <= 0]
    
    total_pnl = sum(t.pnl for t in closed_trades if t.pnl)
    total_wins = sum(t.pnl for t in winning_trades if t.pnl)
    total_losses = abs(sum(t.pnl for t in losing_trades if t.pnl))
    
    return {
        "total_trades": total_trades,
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate": len(winning_trades) / total_trades if total_trades > 0 else 0.0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / total_trades if total_trades > 0 else 0.0,
        "avg_win": total_wins / len(winning_trades) if winning_trades else 0.0,
        "avg_loss": total_losses / len(losing_trades) if losing_trades else 0.0,
        "profit_factor": total_wins / total_losses if total_losses > 0 else 0.0,
        "largest_win": max((t.pnl for t in winning_trades if t.pnl), default=0.0),
        "largest_loss": min((t.pnl for t in losing_trades if t.pnl), default=0.0),
    }


@router.get("/watchlist")
async def get_watchlist(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Get user watchlist."""
    result = await session.execute(
        select(Watchlist).where(Watchlist.enabled == 1).order_by(desc(Watchlist.priority), Watchlist.symbol)
    )
    return [
        {
            "id": w.id,
            "exchange": w.exchange,
            "symbol": w.symbol,
            "priority": w.priority,
            "added_at": w.added_at.isoformat(),
            "notes": w.notes,
        }
        for w in result.scalars()
    ]


@router.post("/watchlist", status_code=201)
async def add_to_watchlist(payload: dict, session: AsyncSession = Depends(get_session)) -> dict:
    """Add symbol to watchlist."""
    try:
        symbol = str(payload["symbol"]).upper()
        exchange = str(payload.get("exchange", "bybit")).lower()
    except (KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail="symbol is required") from error
    
    # Check if already exists
    result = await session.execute(
        select(Watchlist).where(Watchlist.symbol == symbol, Watchlist.exchange == exchange)
    )
    existing = result.scalar_one_or_none()
    if existing:
        if not existing.enabled:
            existing.enabled = 1
            await session.commit()
        return {"id": existing.id, "symbol": existing.symbol, "exchange": existing.exchange}
    
    watchlist_item = Watchlist(
        symbol=symbol,
        exchange=exchange,
        priority=payload.get("priority", 0),
        notes=payload.get("notes"),
    )
    session.add(watchlist_item)
    await session.commit()
    await session.refresh(watchlist_item)
    return {"id": watchlist_item.id, "symbol": watchlist_item.symbol, "exchange": watchlist_item.exchange}


@router.delete("/watchlist/{watchlist_id}")
async def remove_from_watchlist(watchlist_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    """Remove symbol from watchlist."""
    item = await session.get(Watchlist, watchlist_id)
    if item is None:
        raise HTTPException(status_code=404, detail="watchlist item not found")
    item.enabled = 0
    await session.commit()
    return {"status": "removed"}
