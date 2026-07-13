"""FastAPI application entry point for Giraffe QC Model."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from src.api.pad_router import router as pad_router
from src.api.qc_router import router as qc_router
from src.api.qc_intake_router import router as qc_intake_router
from src.api.qc_inspection_router import router as qc_inspection_router
from src.api.qc_learning_router import router as qc_learning_router
from src.api.qc_model_router import router as qc_model_router
from src.api.qc_authoring_router import router as qc_authoring_router
from src.api.qc_incident_router import router as qc_incident_router
from src.api.qc_production_router import router as qc_production_router
from src.api.qc_qualification_router import router as qc_qualification_router
from src.api.qc_readiness_router import router as qc_readiness_router
from src.api.qc_sample_learning_router import router as qc_sample_learning_router
from src.api.qc_source_router import router as qc_source_router
from src.api.qc_bundle_router import router as qc_bundle_router
from src.api.qc_verdict_router import router as qc_verdict_router
from src.api.qc_probation_router import router as qc_probation_router
from src.api.qc_studio_router import router as qc_studio_router
from src.api.edge_cv_router import router as edge_cv_router
from src.api.jetson_router import router as jetson_router
from src.api.sample_admin_router import router as sample_admin_router
from src.api.sku_router import router as sku_router
from src.api.web_shell_router import router as web_shell_router
from src.api.admin_login_router import router as admin_login_router
from src.api.authz import AuthTenantMiddleware
from src.api.startup import session_secret, validate_startup_config
from src.db.session import init_db

_STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: validate config, then initialize the database."""
    validate_startup_config()
    init_db()
    yield


app = FastAPI(
    title="Giraffe QC Model API",
    description="Quality Control inspection API for Giraffe QC Model",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware order matters: the LAST added runs OUTERMOST. SessionMiddleware
# must decode the cookie session BEFORE the auth gate reads it, so the auth
# gate is added first (inner) and SessionMiddleware second (outer).
app.add_middleware(AuthTenantMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(admin_login_router)
app.include_router(web_shell_router)
app.include_router(pad_router)
app.include_router(qc_router)
app.include_router(sku_router)
app.include_router(sample_admin_router)
app.include_router(qc_intake_router)
app.include_router(qc_inspection_router)
app.include_router(qc_model_router)
app.include_router(qc_learning_router)
app.include_router(qc_source_router)
app.include_router(qc_authoring_router)
app.include_router(qc_sample_learning_router)
app.include_router(qc_readiness_router)
app.include_router(qc_production_router)
app.include_router(qc_qualification_router)
app.include_router(qc_incident_router)
app.include_router(qc_bundle_router)
app.include_router(qc_verdict_router)
app.include_router(qc_probation_router)
app.include_router(qc_studio_router)
app.include_router(edge_cv_router)
app.include_router(jetson_router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
