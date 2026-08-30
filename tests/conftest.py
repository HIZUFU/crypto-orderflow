"""Common fixtures and utilities for crypto-orderflow tests."""
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with isolated database."""
    return Settings(
        app_env="testing",
        database_url="sqlite+aiosqlite:///:memory:",
        symbols="BTCUSDT,ETHUSDT",
        signal_cooldown_seconds=0.1,
        signal_ttl_seconds=120.0,
        paper_notional_usdt=10.0,
        paper_leverage=1,
        paper_fee_rate=0.00055,
        enable_auto_close=True,
        position_monitor_interval_seconds=0.5,
    )


@pytest_asyncio.fixture
async def db_session_factory(test_settings: Settings) -> AsyncGenerator[async_sessionmaker, None]:
    """Create async session factory with in-memory SQLite database."""
    engine = create_async_engine(test_settings.database_url, echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_session_factory: async_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    """Create async session for individual tests."""
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def orderbook_snapshot() -> tuple[list[list[str]], list[list[str]]]:
    """Return a valid L2 snapshot for testing."""
    bids = [["100.0", "2.5"], ["99.5", "1.0"], ["99.0", "3.0"]]
    asks = [["100.5", "2.0"], ["101.0", "1.5"], ["101.5", "2.5"]]
    return bids, asks


@pytest.fixture
def base_features() -> dict[str, float]:
    """Return base features that should generate a LONG signal."""
    return {
        "mid_price": 100.0,
        "spread_bps": 2.0,
        "imbalance": 0.3,
        "microprice": 100.05,
        "microprice_offset_bps": 1.0,
        "buy_volume_3s": 5.0,
        "sell_volume_3s": 2.0,
        "delta_ratio_3s": 0.25,
        "trades_3s": 5.0,
        "trade_intensity": 1.67,
        "volatility_30s": 0.02,
        "book_depth_bid": 6.5,
        "book_depth_ask": 6.0,
    }


@pytest.fixture
def mock_catboost_model() -> MagicMock:
    """Create a mock CatBoostClassifier for testing."""
    model = MagicMock()
    model.predict_proba.return_value = [[0.4, 0.6]]  # [prob_0, prob_1]
    return model


@pytest.fixture
def temp_parquet_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for parquet files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
