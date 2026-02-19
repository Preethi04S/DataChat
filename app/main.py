from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.core.logging import setup_logging
from app.core.config import BOOKS_CSV_PATH, ENABLE_CORS, CORS_ORIGINS
from app.core.security import SecurityHeadersMiddleware
from app.core.metrics import pipeline_metrics
from app.data.loader import load_dataset
from app.api.routes import router

setup_logging()

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dataset(BOOKS_CSV_PATH)
    pipeline_metrics.set_gauge("dataset_loaded", 1)
    yield


app = FastAPI(
    title="DataChat — Enterprise AI Analytics",
    description=(
        "Proof-carrying CSV chatbot with verifiable, audit-ready answers. "
        "Built with multi-stage ETL pipeline, Agentic AI data profiling, "
        "and enterprise-grade security. Powered by Akaike-aligned architecture."
    ),
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_CORS else None,
    redoc_url=None,
)

# ── Enterprise Security Middleware ──
app.add_middleware(SecurityHeadersMiddleware)

# ── CORS Configuration ──
if ENABLE_CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-Id"],
        expose_headers=["X-Response-Time", "X-Request-Id"],
    )

app.include_router(router)

if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")

    @app.get("/", include_in_schema=False)
    def serve_ui():
        return FileResponse(str(UI_DIR / "index.html"))
