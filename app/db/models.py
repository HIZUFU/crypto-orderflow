from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
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


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
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
