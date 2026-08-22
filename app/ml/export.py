"""Export alert outcomes and paper trades to training-ready Parquet data."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Alert, AlertOutcome, PaperTrade
from app.db.session import session_factory
from app.ml.labels import labeled_alert_rows

settings = get_settings()


def _features(alert: Alert) -> dict[str, float]:
    try:
        return json.loads(alert.features_json or "{}")
    except json.JSONDecodeError:
        return {}


async def export_training_to_parquet(output_dir: Path = Path("data/history")) -> dict:
    """Build one deduplicated dataset from every alert with a measured outcome."""
    output_dir.mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        alerts = list((await session.execute(select(Alert).order_by(Alert.created_at))).scalars())
        outcomes = list((await session.execute(select(AlertOutcome))).scalars())
        trades = list((await session.execute(select(PaperTrade))).scalars())

    labels = labeled_alert_rows(alerts, outcomes, trades, settings.paper_fee_rate)
    if not labels:
        raise ValueError("No alerts with a measured result found")
    rows = []
    for item in labels:
        alert = item["alert"]
        row = {
            "alert_id": alert.id,
            "created_at": alert.created_at,
            "symbol": alert.symbol,
            "market": alert.market,
            "exchange": alert.exchange,
            "source_key": alert.source_key,
            "direction": alert.direction,
            "rule_score": alert.score,
            "reference_price": alert.reference_price,
            "stop_loss": alert.stop_loss,
            "take_profit": alert.take_profit,
            "pnl": item["pnl"],
            "label": item["label"],
            "label_source": item["label_source"],
        }
        row.update(_features(alert))
        rows.append(row)
    dataset = pd.DataFrame(rows).sort_values("created_at")
    output_path = output_dir / "training.parquet"
    dataset.to_parquet(output_path, index=False, compression="snappy")
    result = {
        "path": str(output_path),
        "labeled_alerts": int(len(dataset)),
        "paper_trade_labels": int((dataset["label_source"] == "paper_trade").sum()),
        "expiry_mark_labels": int((dataset["label_source"] == "expiry_mark").sum()),
    }
    print(f"Exported {result['labeled_alerts']} labeled alerts to {output_path}")
    return result


async def export_alerts_to_parquet(output_dir: Path = Path("data/history")) -> None:
    """Export the complete alert archive for inspection."""
    output_dir.mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        alerts = list((await session.execute(select(Alert).order_by(Alert.created_at))).scalars())
    if not alerts:
        print("No alerts to export")
        return
    rows = []
    for alert in alerts:
        row = {
            "alert_id": alert.id,
            "created_at": alert.created_at,
            "symbol": alert.symbol,
            "market": alert.market,
            "exchange": alert.exchange,
            "source_key": alert.source_key,
            "direction": alert.direction,
            "status": alert.status,
            "outcome_type": alert.outcome_type,
            "rule_score": alert.score,
            "reference_price": alert.reference_price,
            "stop_loss": alert.stop_loss,
            "take_profit": alert.take_profit,
        }
        row.update(_features(alert))
        rows.append(row)
    output_path = output_dir / f"alerts_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet"
    pd.DataFrame(rows).to_parquet(output_path, index=False, compression="snappy")
    print(f"Exported {len(rows)} alerts to {output_path}")


async def export_trades_to_parquet(output_dir: Path = Path("data/history")) -> None:
    """Export the paper-trade archive for inspection."""
    output_dir.mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        trades = list((await session.execute(select(PaperTrade).order_by(PaperTrade.opened_at))).scalars())
    if not trades:
        print("No trades to export")
        return
    rows = [
        {
            "trade_id": trade.id,
            "alert_id": trade.alert_id,
            "symbol": trade.symbol,
            "market": trade.market,
            "exchange": trade.exchange,
            "source_key": trade.source_key,
            "direction": trade.direction,
            "status": trade.status,
            "opened_at": trade.opened_at,
            "closed_at": trade.closed_at,
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
        for trade in trades
    ]
    output_path = output_dir / f"trades_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet"
    pd.DataFrame(rows).to_parquet(output_path, index=False, compression="snappy")
    print(f"Exported {len(rows)} trades to {output_path}")


if __name__ == "__main__":
    asyncio.run(export_alerts_to_parquet())
    asyncio.run(export_trades_to_parquet())
    asyncio.run(export_training_to_parquet())
