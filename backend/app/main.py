"""FastAPI app factory. Run with: uvicorn app.main:app --reload --app-dir backend"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import bookings, chat, health, sessions
from app.db.engine import create_tables, get_engine

FRONTEND_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    create_tables(get_engine())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="md-travel-planner", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(bookings.router, prefix="/api")
    return app


app = create_app()
