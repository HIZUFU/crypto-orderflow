from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db.models import Base, RuntimeSetting

settings = get_settings()
if settings.database_url.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

_ALERT_COLUMNS = {"exchange": "VARCHAR(16) DEFAULT 'bybit'", "chart_snapshot": "TEXT", "ml_probability": "FLOAT", "ml_passed_filter": "BOOLEAN DEFAULT 0", "outcome_type": "VARCHAR(24) DEFAULT 'pending'", "source_key": "VARCHAR(96)", "connection_id": "INTEGER"}
_TRADE_COLUMNS = {"market": "VARCHAR(16) DEFAULT 'linear'", "exchange": "VARCHAR(16) DEFAULT 'bybit'", "source_key": "VARCHAR(96)"}
_RUNTIME_FIELDS = {"initial_paper_balance": float, "paper_notional_usdt": float, "risk_mode": str, "risk_value": float, "reward_risk_ratio": float, "signal_ttl_seconds": float, "ml_threshold": float, "use_ml_filter": lambda value: value.lower() == "true"}


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


async def load_runtime_settings(target: Settings | None = None) -> None:
    target = target or get_settings()
    async with session_factory() as session:
        rows = (await session.execute(select(RuntimeSetting))).scalars()
        for row in rows:
            parser = _RUNTIME_FIELDS.get(row.key)
            if parser:
                try:
                    setattr(target, row.key, parser(row.value))
                except (TypeError, ValueError):
                    pass


async def save_runtime_settings(values: dict[str, object], target: Settings | None = None) -> None:
    target = target or get_settings()
    async with session_factory() as session:
        for key, value in values.items():
            if key not in _RUNTIME_FIELDS:
                continue
            row = await session.get(RuntimeSetting, key)
            string_value = str(value).lower() if isinstance(value, bool) else str(value)
            if row:
                row.value = string_value
            else:
                session.add(RuntimeSetting(key=key, value=string_value))
            setattr(target, key, _RUNTIME_FIELDS[key](string_value))
        await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
