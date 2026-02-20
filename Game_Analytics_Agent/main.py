"""
NEXUS – Game Analytics Intelligence Platform
Entry point: uvicorn main:app --reload --port 8000
"""
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()  # loads .env from the project root automatically

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from data.loader import load_data, get_schema_info
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load data on startup."""
    print("NEXUS: Loading game dataset…")
    try:
        df, conn = load_data()
        schema = get_schema_info(conn)
        app.state.df = df
        app.state.conn = conn
        app.state.schema = schema
        print(f"NEXUS: Dataset ready — {len(df)} games loaded.")
    except Exception as e:
        print(f"NEXUS: WARNING — could not load data: {e}")
        app.state.df = None
        app.state.conn = None
        app.state.schema = {"columns": [], "sample": []}
    yield
    # cleanup
    if hasattr(app.state, "conn") and app.state.conn:
        app.state.conn.close()


app = FastAPI(
    title="NEXUS — Game Analytics Intelligence Platform",
    description="Agentic game analytics over Steam data via natural language.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)

# Serve static UI
ui_dir = os.path.join(os.path.dirname(__file__), "ui")
if os.path.isdir(ui_dir):
    app.mount("/static", StaticFiles(directory=ui_dir), name="static")

    @app.get("/")
    async def dashboard():
        return FileResponse(os.path.join(ui_dir, "index.html"))
else:
    @app.get("/")
    async def root():
        return {
            "name": "NEXUS Game Analytics",
            "version": "1.0.0",
            "docs": "/docs",
            "endpoint": "POST /game/analytics",
        }
