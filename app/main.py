import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.db.session import init_db, session_factory
from app.market.service import MarketService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    service = MarketService(settings, session_factory)
    app.state.market_service = service
    await service.start()
    try:
        yield
    finally:
        await service.stop()


app = FastAPI(title="Orderflow Lab", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
