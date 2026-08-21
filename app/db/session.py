from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base

settings = get_settings()
if settings.database_url.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

_ALERT_COLUMNS = {
    "exchange": "VARCHAR(16) DEFAULT 'bybit'",
    "chart_snapshot": "TEXT",
    "ml_probability": "FLOAT",
    "ml_passed_filter": "BOOLEAN DEFAULT 0",
    "outcome_type": "VARCHAR(24) DEFAULT 'pending'",
    "source_key": "VARCHAR(96)",
    "connection_id": "INTEGER",
}
_TRADE_COLUMNS = {"market": "VARCHAR(16) DEFAULT 'linear'", "exchange": "VARCHAR(16) DEFAULT 'bybit'", "source_key": "VARCHAR(96)"}


def _migrate_existing_schema(connection) -> None:
    Base.metadata.create_all(connection)
    inspector = inspect(connection)
    for table, columns in (("alerts", _ALERT_COLUMNS), ("paper_trades", _TRADE_COLUMNS)):
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
    connection.execute(text("UPDATE alerts SET exchange = 'bybit' WHERE exchange IS NULL"))
    connection.execute(text("UPDATE alerts SET outcome_type = 'pending' WHERE outcome_type IS NULL"))
    connection.execute(text("UPDATE alerts SET ml_passed_filter = 0 WHERE ml_passed_filter IS NULL"))
    connection.execute(text("UPDATE paper_trades SET exchange = 'bybit' WHERE exchange IS NULL"))
    connection.execute(text("UPDATE paper_trades SET market = 'linear' WHERE market IS NULL"))


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_migrate_existing_schema)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
