"""FastAPI application entry point for Giraffe QC Model."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.qc_router import router as qc_router
from src.api.sku_router import router as sku_router
from src.db.session import init_db


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

app.include_router(qc_router)
app.include_router(sku_router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
