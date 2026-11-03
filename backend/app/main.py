"""FastAPI app: CORS for the Vite dev server, all routers under /api, tables created on startup.

Request validation errors return 400 `{"detail": "message"}` (03-contracts §3), not FastAPI's 422.

Run from the repo root: uvicorn app.main:app --reload --app-dir backend
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, health, sessions
from app.db.engine import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="md-travel-planner API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_as_400(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """First validation error as one readable line, e.g. "content: String should have at least 1 character"."""
    error = exc.errors()[0]
    if error["type"] == "json_invalid":  # loc is ("body", <character position>), not a field
        return JSONResponse(status_code=400, content={"detail": "Request body is not valid JSON"})
    field = ".".join(part for part in error["loc"] if isinstance(part, str) and part != "body")
    return JSONResponse(status_code=400, content={"detail": f"{field}: {error['msg']}" if field else error["msg"]})


app.include_router(health.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
