"""Export alert outcomes and paper trades to training-ready Parquet data."""
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.db.models import Alert, AlertOutcome, PaperTrade
from app.db.session import session_factory


TERMINAL_OUTCOMES = {"expired", "take_profit", "stop_loss", "manual"}


def _features(alert: Alert) -> dict[str, float]:
    try:
        return json.loads(alert.features_json or "{}")
    except json.JSONDecodeError:
        return {}


def _training_rows(
    alerts: list[Alert], outcomes: list[AlertOutcome], trades: list[PaperTrade]
) -> list[dict]:
    outcomes_by_alert: dict[int, list[AlertOutcome]] = defaultdict(list)
    trades_by_alert: dict[int, list[PaperTrade]] = defaultdict(list)
    for outcome in outcomes:
        outcomes_by_alert[outcome.alert_id].append(outcome)
    for trade in trades:
        trades_by_alert[trade.alert_id].append(trade)

    rows: list[dict] = []
    for alert in alerts:
        pnl = None
        label_source = None
        closed = sorted(
            (trade for trade in trades_by_alert[alert.id] if trade.status == "closed" and trade.pnl is not None),
            key=lambda trade: trade.closed_at or trade.opened_at,
            reverse=True,
        )
        if closed:
            pnl = float(closed[0].pnl)
            label_source = "paper_trade"
        else:
            marked = sorted(
                (
                    outcome
                    for outcome in outcomes_by_alert[alert.id]
                    if outcome.outcome_type in TERMINAL_OUTCOMES
                    and outcome.hypothetical_pnl is not None
                ),
                key=lambda outcome: outcome.outcome_timestamp,
                reverse=True,
            )
            if marked:
                pnl = float(marked[0].hypothetical_pnl)
                label_source = "expired_mark"
        if pnl is None:
            continue

        row = {
            "alert_id": alert.id,
            "created_at": alert.created_at,
            "symbol": alert.symbol,
            "market": alert.market,
            "exchange": alert.exchange,
            "source_key": alert.source_key,
            "direction": alert.direction,
            "score": alert.score,
            "reference_price": alert.reference_price,
            "stop_loss": alert.stop_loss,
            "take_profit": alert.take_profit,
            "pnl": pnl,
            "label": int(pnl > 0),
            "label_source": label_source,
        }
        row.update(_features(alert))
        rows.append(row)
    return rows


async def export_training_to_parquet(output_dir: Path = Path("data/history")) -> None:
    """Build one deduplicated labeled dataset from all alerts with measured outcomes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        alerts = list((await session.execute(select(Alert).order_by(Alert.created_at))).scalars())
        outcomes = list((await session.execute(select(AlertOutcome))).scalars())
        trades = list((await session.execute(select(PaperTrade))).scalars())

    rows = _training_rows(alerts, outcomes, trades)
    if not rows:
        raise ValueError("No alerts with a measured outcome found")
    dataset = pd.DataFrame(rows).sort_values("created_at")
    output_path = output_dir / "training.parquet"
    dataset.to_parquet(output_path, index=False, compression="snappy")
    print(
        f"Exported {len(dataset)} labeled alerts to {output_path} "
        f"({int((dataset['label_source'] == 'paper_trade').sum())} paper, "
        f"{int((dataset['label_source'] == 'expired_mark').sum())} expired-mark)"
    )


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
            "score": alert.score,
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
