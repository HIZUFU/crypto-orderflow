"""Integration tests for MarketService in app/market/service.py."""
import asyncio
from datetime import timedelta
from time import monotonic
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import Alert, PaperTrade, utc_now
from app.market.features import TradeEvent
from app.market.service import MarketService


class MockWebSocket:
    """Mock WebSocket connection for testing."""
    
    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages
        self.index = 0
        self.closed = False
    
    async def __aenter__(self) -> "MockWebSocket":
        return self
    
    async def __aexit__(self, *args) -> None:
        self.closed = True
    
    async def send(self, data: str) -> None:
        pass
    
    def __aiter__(self) -> "MockWebSocket":
        return self
    
    async def __anext__(self) -> str:
        if self.index >= len(self.messages):
            await asyncio.sleep(0.1)  # Wait for more messages
            raise StopAsyncIteration
        msg = self.messages[self.index]
        self.index += 1
        import json
        return json.dumps(msg)


@pytest.fixture
def mock_websocket_connect() -> MagicMock:
    """Create a mock for websockets.connect."""
    mock = MagicMock()
    mock.return_value.__aenter__.return_value = MockWebSocket([])
    mock.return_value.__aenter__.return_value.send = AsyncMock()
    return mock


class TestMarketServiceIntegration:
    """Integration tests for MarketService."""

    @pytest.mark.asyncio
    async def test_market_service_receives_snapshot_and_generates_features(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """MarketService should process snapshot and calculate features."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Manually apply a snapshot to the book
        symbol = "BTCUSDT"
        service.books[symbol].apply(
            "snapshot",
            [["50000.0", "1.0"], ["49999.0", "2.0"]],
            [["50001.0", "1.0"], ["50002.0", "2.0"]],
            1,
            int(asyncio.get_event_loop().time() * 1000)
        )
        
        # Calculate features manually
        features = service.engines[symbol].calculate()
        
        assert features is not None
        assert "mid_price" in features
        assert "imbalance" in features
        assert abs(features["mid_price"] - 50000.5) < 0.1

    @pytest.mark.asyncio
    async def test_maybe_alert_creates_alert_in_database(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """_maybe_alert should create an Alert record in the database."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Create features that should trigger a signal
        features = {
            "mid_price": 50000.0,
            "spread_bps": 2.0,
            "imbalance": 0.3,
            "microprice": 50000.5,
            "microprice_offset_bps": 1.0,
            "buy_volume_3s": 5.0,
            "sell_volume_3s": 2.0,
            "delta_ratio_3s": 0.25,
            "trades_3s": 5.0,
            "trade_intensity": 1.67,
            "volatility_30s": 0.02,
            "book_depth_bid": 3.0,
            "book_depth_ask": 3.0,
        }
        
        symbol = "BTCUSDT"
        await service._maybe_alert(symbol, features)
        
        # Check database for alert
        async with db_session_factory() as session:
            result = await session.execute(select(Alert).where(Alert.symbol == symbol))
            alerts = result.scalars().all()
            
            assert len(alerts) == 1
            alert = alerts[0]
            assert alert.direction in ("LONG", "SHORT")
            assert alert.reference_price == 50000.0
            assert alert.score > 0

    @pytest.mark.asyncio
    async def test_check_positions_closes_on_stop_loss(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """_check_positions should close position when stop_loss is hit."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Create an open LONG position
        created = utc_now()
        async with db_session_factory() as session:
            trade = PaperTrade(
                alert_id=1,
                symbol="BTCUSDT",
                direction="LONG",
                status="open",
                entry_price=50000.0,
                stop_loss=49900.0,  # Stop loss below entry
                take_profit=50200.0,
                notional=100.0,
                leverage=1,
            )
            session.add(trade)
            await session.commit()
            trade_id = trade.id
        
        # Set current price below stop_loss
        service.latest["BTCUSDT"] = {"mid_price": 49850.0}
        
        await service._check_positions()
        
        # Verify position was closed
        async with db_session_factory() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == trade_id)
            )
            trade = result.scalar_one()
            
            assert trade.status == "closed"
            assert trade.exit_reason == "stop_loss"
            assert trade.exit_price == 49850.0
            assert trade.pnl is not None

    @pytest.mark.asyncio
    async def test_check_positions_closes_on_take_profit(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """_check_positions should close position when take_profit is hit."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Create an open LONG position
        created = utc_now()
        async with db_session_factory() as session:
            trade = PaperTrade(
                alert_id=1,
                symbol="BTCUSDT",
                direction="LONG",
                status="open",
                entry_price=50000.0,
                stop_loss=49900.0,
                take_profit=50200.0,  # Take profit above entry
                notional=100.0,
                leverage=1,
            )
            session.add(trade)
            await session.commit()
            trade_id = trade.id
        
        # Set current price above take_profit
        service.latest["BTCUSDT"] = {"mid_price": 50250.0}
        
        await service._check_positions()
        
        # Verify position was closed
        async with db_session_factory() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == trade_id)
            )
            trade = result.scalar_one()
            
            assert trade.status == "closed"
            assert trade.exit_reason == "take_profit"
            assert trade.exit_price == 50250.0

    @pytest.mark.asyncio
    async def test_check_positions_short_stop_loss(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """_check_positions should close SHORT position when stop_loss is hit."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Create an open SHORT position
        async with db_session_factory() as session:
            trade = PaperTrade(
                alert_id=1,
                symbol="ETHUSDT",
                direction="SHORT",
                status="open",
                entry_price=3000.0,
                stop_loss=3050.0,  # Stop loss above entry for SHORT
                take_profit=2900.0,
                notional=100.0,
                leverage=1,
            )
            session.add(trade)
            await session.commit()
            trade_id = trade.id
        
        # Set current price above stop_loss
        service.latest["ETHUSDT"] = {"mid_price": 3060.0}
        
        await service._check_positions()
        
        # Verify position was closed
        async with db_session_factory() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == trade_id)
            )
            trade = result.scalar_one()
            
            assert trade.status == "closed"
            assert trade.exit_reason == "stop_loss"

    @pytest.mark.asyncio
    async def test_check_positions_skips_missing_price(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """_check_positions should skip positions without current price."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Create an open position
        async with db_session_factory() as session:
            trade = PaperTrade(
                alert_id=1,
                symbol="BTCUSDT",
                direction="LONG",
                status="open",
                entry_price=50000.0,
                stop_loss=49900.0,
                take_profit=50200.0,
                notional=100.0,
                leverage=1,
            )
            session.add(trade)
            await session.commit()
            trade_id = trade.id
        
        # Don't set current price for this symbol
        service.latest = {}
        
        await service._check_positions()
        
        # Position should still be open
        async with db_session_factory() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == trade_id)
            )
            trade = result.scalar_one()
            
            assert trade.status == "open"

    @pytest.mark.asyncio
    async def test_check_positions_calculates_pnl_correctly(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """_check_positions should calculate PnL correctly for LONG and SHORT."""
        from app.config import Settings
        
        service = MarketService(test_settings, db_session_factory)
        
        # Create LONG and SHORT positions
        async with db_session_factory() as session:
            long_trade = PaperTrade(
                alert_id=1,
                symbol="BTCUSDT",
                direction="LONG",
                status="open",
                entry_price=50000.0,
                stop_loss=49900.0,
                take_profit=50200.0,
                notional=100.0,
                leverage=1,
            )
            short_trade = PaperTrade(
                alert_id=2,
                symbol="ETHUSDT",
                direction="SHORT",
                status="open",
                entry_price=3000.0,
                stop_loss=3050.0,
                take_profit=2900.0,
                notional=100.0,
                leverage=1,
            )
            session.add(long_trade)
            session.add(short_trade)
            await session.commit()
        
        # Set prices to trigger take_profit for both
        service.latest["BTCUSDT"] = {"mid_price": 50200.0}
        service.latest["ETHUSDT"] = {"mid_price": 2900.0}
        
        await service._check_positions()
        
        # Verify PnL calculations
        async with db_session_factory() as session:
            result = await session.execute(select(PaperTrade).order_by(PaperTrade.id))
            trades = result.scalars().all()
            
            # LONG: price went up from 50000 to 50200 => positive PnL
            long_pnl = trades[0].pnl
            assert long_pnl is not None
            # Expected: ((50200 - 50000) / 50000) * 100 - fees
            expected_long = (200 / 50000) * 100 - (100 * 0.00055 * 2)
            assert abs(long_pnl - expected_long) < 0.01
            
            # SHORT: price went down from 3000 to 2900 => positive PnL
            short_pnl = trades[1].pnl
            assert short_pnl is not None
            # Expected: -((2900 - 3000) / 3000) * 100 - fees = positive
            expected_short = -(-100 / 3000) * 100 - (100 * 0.00055 * 2)
            assert abs(short_pnl - expected_short) < 0.01


class TestMarketServiceSignalCooldown:
    """Tests for signal cooldown logic."""

    @pytest.mark.asyncio
    async def test_signal_cooldown_prevents_duplicate_alerts(
        self, test_settings: Settings, db_session_factory: async_sessionmaker
    ) -> None:
        """Signals within cooldown period should not generate duplicate alerts."""
        from app.config import Settings
        
        # Use very short cooldown for testing
        test_settings.signal_cooldown_seconds = 1.0
        
        service = MarketService(test_settings, db_session_factory)
        
        features = {
            "mid_price": 50000.0,
            "spread_bps": 2.0,
            "imbalance": 0.3,
            "microprice": 50000.5,
            "microprice_offset_bps": 1.0,
            "buy_volume_3s": 5.0,
            "sell_volume_3s": 2.0,
            "delta_ratio_3s": 0.25,
            "trades_3s": 5.0,
            "trade_intensity": 1.67,
            "volatility_30s": 0.02,
            "book_depth_bid": 3.0,
            "book_depth_ask": 3.0,
        }
        
        symbol = "BTCUSDT"
        
        # First alert should be created
        await service._maybe_alert(symbol, features)
        
        # Second alert immediately should NOT be created (within cooldown)
        await service._maybe_alert(symbol, features)
        
        # Check database
        async with db_session_factory() as session:
            result = await session.execute(select(Alert).where(Alert.symbol == symbol))
            alerts = result.scalars().all()
            
            # Should have only 1 alert due to cooldown
            assert len(alerts) == 1
