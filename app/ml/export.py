"""Archive alerts and trades to Parquet for model training."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Alert, PaperTrade
from app.db.session import session_factory

settings = get_settings()


async def export_alerts_to_parquet(output_dir: Path = Path("data/history")) -> None:
    """Export all alerts with their features to Parquet for offline analysis."""
    output_dir.mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        result = await session.execute(select(Alert).order_by(Alert.created_at))
        alerts = result.scalars().all()
        if not alerts:
            print("No alerts to export")
            return
        rows = []
        for alert in alerts:
            import json
            features = json.loads(alert.features_json)
            rows.append({
                "alert_id": alert.id,
                "created_at": alert.created_at,
                "symbol": alert.symbol,
                "direction": alert.direction,
                "status": alert.status,
                "score": alert.score,
                "reference_price": alert.reference_price,
                "stop_loss": alert.stop_loss,
                "take_profit": alert.take_profit,
                **features,
            })
        df = pd.DataFrame(rows)
        output_path = output_dir / f"alerts_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet"
        df.to_parquet(output_path, index=False, compression="snappy")
        print(f"Exported {len(df)} alerts to {output_path}")


async def export_trades_to_parquet(output_dir: Path = Path("data/history")) -> None:
    """Export all paper trades with outcomes to Parquet for training labels."""
    output_dir.mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        result = await session.execute(select(PaperTrade).order_by(PaperTrade.opened_at))
        trades = result.scalars().all()
        if not trades:
            print("No trades to export")
            return
        rows = []
        for trade in trades:
            rows.append({
                "trade_id": trade.id,
                "alert_id": trade.alert_id,
                "symbol": trade.symbol,
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
            })
        df = pd.DataFrame(rows)
        output_path = output_dir / f"trades_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet"
        df.to_parquet(output_path, index=False, compression="snappy")
        print(f"Exported {len(df)} trades to {output_path}")


if __name__ == "__main__":
    asyncio.run(export_alerts_to_parquet())
    asyncio.run(export_trades_to_parquet())
