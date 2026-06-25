"""FastAPI application entry point for Giraffe QC Model."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.qc_router import router as qc_router
from src.api.sample_admin_router import router as sample_admin_router
from src.api.sku_router import router as sku_router
from src.db.session import init_db

_STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize database on startup."""
    init_db()
    yield


app = FastAPI(
    title="Giraffe QC Model API",
    description="Quality Control inspection API for Giraffe QC Model",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(qc_router)
app.include_router(sku_router)
app.include_router(sample_admin_router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
