from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(16), default="linear")
    exchange: Mapped[str] = mapped_column(String(16), default="bybit")
    source_key: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("exchange_connections.id"), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    entry_low: Mapped[float] = mapped_column(Float)
    entry_high: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    position_notional: Mapped[float] = mapped_column(Float)
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    risk_amount: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    strategy_version: Mapped[str] = mapped_column(String(32), default="ofm-v0.1")
    features_json: Mapped[str] = mapped_column(Text, default="{}")
    chart_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    ml_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_passed_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome_type: Mapped[str] = mapped_column(String(24), default="pending")


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(16), default="linear")
    exchange: Mapped[str] = mapped_column(String(16), default="bybit")
    source_key: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AlertOutcome(Base):
    __tablename__ = "alert_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    outcome_type: Mapped[str] = mapped_column(String(24), index=True)
    outcome_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    paper_trade_id: Mapped[int | None] = mapped_column(ForeignKey("paper_trades.id"), nullable=True)
    time_to_action_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_at_outcome: Mapped[float | None] = mapped_column(Float, nullable=True)
    hypothetical_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    reached_target: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hit_stop: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ml_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_passed_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExchangeConnection(Base):
    """A user-configured public market stream and optional private read-only credentials."""
    __tablename__ = "exchange_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(16), index=True)
    market_type: Mapped[str] = mapped_column(String(16), default="linear")
    ws_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    symbols_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Balance(Base):
    __tablename__ = "balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    paper_balance: Mapped[float] = mapped_column(Float, default=10000.0)
    real_balance: Mapped[float] = mapped_column(Float, default=0.0)
    paper_equity: Mapped[float] = mapped_column(Float, default=10000.0)
    real_equity: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), default="bybit", index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
