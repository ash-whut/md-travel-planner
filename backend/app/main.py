"""FastAPI app: CORS for the Vite dev server and all routers under /api.

Run from the repo root: uvicorn app.main:app --reload --app-dir backend
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health

app = FastAPI(title="md-travel-planner API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
