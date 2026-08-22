"""Research endpoints for measured labels, model training and public instrument discovery."""
import asyncio
import json
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Alert, AlertOutcome, PaperTrade
from app.db.session import get_session
from app.ml.export import export_training_to_parquet
from app.ml.labels import label_summary, labeled_alert_rows
from app.ml.train import load_training_data, train_catboost

router = APIRouter(prefix="/api")
settings = get_settings()


async def _label_state(session: AsyncSession) -> dict:
    alerts = list((await session.execute(select(Alert))).scalars())
    outcomes = list((await session.execute(select(AlertOutcome))).scalars())
    trades = list((await session.execute(select(PaperTrade))).scalars())
    rows = labeled_alert_rows(alerts, outcomes, trades, settings.paper_fee_rate)
    summary = label_summary(rows, len(alerts))
    summary["training_ready"] = summary["labeled_alerts"] >= 50 and summary["winning_labels"] > 0 and summary["losing_labels"] > 0
    return summary


@router.get("/ml/dataset")
async def ml_dataset(session: AsyncSession = Depends(get_session)) -> dict:
    summary = await _label_state(session)
    metrics_path = Path(settings.ml_model_path).with_suffix(".metrics.json")
    metrics = None
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metrics = None
    return {
        **summary,
        "label_policy": "closed paper PnL first; otherwise expiry mark PnL after estimated round-trip fees",
        "metrics": metrics,
    }


@router.post("/ml/export")
async def ml_export(session: AsyncSession = Depends(get_session)) -> dict:
    summary = await _label_state(session)
    if not summary["training_ready"]:
        raise HTTPException(status_code=422, detail="Need at least 50 labeled alerts with both positive and negative outcomes")
    result = await export_training_to_parquet()
    return {**summary, "export": result}


@router.post("/ml/train")
async def ml_train(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    summary = await _label_state(session)
    if not summary["training_ready"]:
        raise HTTPException(status_code=422, detail="Need at least 50 labeled alerts with both positive and negative outcomes")
    try:
        dataset = await asyncio.to_thread(load_training_data)
        metrics = await asyncio.to_thread(train_catboost, dataset)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.app.state.market_service.refresh_ml_filter()
    return {**summary, "metrics": metrics, "model_path": settings.ml_model_path}


@router.get("/strategy")
async def strategy_state() -> dict:
    return {
        "type": "short-horizon order-flow candidate",
        "inputs": {
            "order_book": "weighted bid/ask liquidity across top 20 levels",
            "tape": "aggressor buy/sell volume during the last 3 seconds",
            "microprice": "best-level liquidity imbalance",
        },
        "entry_conditions": {
            "max_spread_bps": 8.0,
            "min_trades_3s": 2,
            "long": "book imbalance >= 0.22, tape delta >= 0.18, microprice above mid",
            "short": "book imbalance <= -0.22, tape delta <= -0.18, microprice below mid",
        },
        "risk": {
            "mode": settings.risk_mode,
            "value": settings.risk_value,
            "notional_usdt": settings.paper_notional_usdt,
            "reward_risk_ratio": settings.reward_risk_ratio,
            "signal_ttl_seconds": settings.signal_ttl_seconds,
            "fee_rate": settings.paper_fee_rate,
        },
        "boundaries": {
            "arrows_are_trades": False,
            "paper_trade_requires_open_paper": True,
            "live_execution": False,
        },
    }


@router.get("/markets/{provider}/{market_type}/symbols")
async def market_symbols(provider: str, market_type: str) -> dict:
    provider = provider.lower()
    market_type = "linear" if market_type.lower() == "futures" else market_type.lower()
    if provider not in {"bybit", "binance"} or market_type not in {"spot", "linear"}:
        raise HTTPException(status_code=422, detail="provider must be bybit/binance and market must be spot/futures")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            if provider == "binance":
                url = "https://fapi.binance.com/fapi/v1/exchangeInfo" if market_type == "linear" else "https://api.binance.com/api/v3/exchangeInfo"
                payload = (await client.get(url)).json()
                symbols = [
                    item["symbol"] for item in payload.get("symbols", [])
                    if item.get("status") == "TRADING" and item.get("quoteAsset") == "USDT"
                ]
            else:
                category = "linear" if market_type == "linear" else "spot"
                payload = (await client.get(
                    "https://api.bybit.com/v5/market/instruments-info",
                    params={"category": category, "limit": 1000},
                )).json()
                symbols = [
                    item["symbol"] for item in payload.get("result", {}).get("list", [])
                    if item.get("status") == "Trading" and item.get("quoteCoin") == "USDT"
                ]
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise HTTPException(status_code=503, detail="Could not load public instrument list") from error
    return {"provider": provider, "market_type": market_type, "quote": "USDT", "symbols": sorted(set(symbols))}
