from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret_key: str = "development-only-change-me"
    database_url: str = "sqlite+aiosqlite:///./data/orderflow.db"
    bybit_ws_url: str = "wss://stream.bybit.com/v5/public/linear"
    symbols: str = "BTCUSDT,ETHUSDT"
    orderbook_depth: int = 50
    reconnect_delay_seconds: float = 5.0
    signal_cooldown_seconds: float = 15.0
    signal_ttl_seconds: float = 8.0
    trading_mode: str = "paper"
    live_trading_enabled: bool = False
    paper_notional_usdt: float = 10.0
    paper_leverage: int = 1
    paper_fee_rate: float = 0.00055

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def tracked_symbols(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.symbols.split(",") if symbol.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
