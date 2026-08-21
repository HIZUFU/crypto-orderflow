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
}


def _migrate_existing_schema(connection) -> None:
    Base.metadata.create_all(connection)
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("alerts")}
    for name, definition in _ALERT_COLUMNS.items():
        if name not in columns:
            connection.execute(text(f"ALTER TABLE alerts ADD COLUMN {name} {definition}"))
    connection.execute(text("UPDATE alerts SET exchange = 'bybit' WHERE exchange IS NULL"))
    connection.execute(text("UPDATE alerts SET outcome_type = 'pending' WHERE outcome_type IS NULL"))
    connection.execute(text("UPDATE alerts SET ml_passed_filter = 0 WHERE ml_passed_filter IS NULL"))


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_migrate_existing_schema)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
