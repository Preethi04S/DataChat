"""FastAPI route definitions."""
import time
from fastapi import APIRouter, Request, HTTPException
from api.models import AnalyticsRequest, AnalyticsResponse
from core.orchestrator import process_query
from tools.sql_executor import get_table_stats
from session.manager import get_history

router = APIRouter()


@router.post("/game/analytics", response_model=AnalyticsResponse)
async def game_analytics(request: Request, body: AnalyticsRequest):
    """Main analytics endpoint. Accepts a natural-language query about games."""
    state = request.app.state
    if not hasattr(state, "conn") or state.conn is None:
        raise HTTPException(status_code=503, detail="Data not loaded yet. Please wait.")

    result = process_query(
        query=body.query,
        conn=state.conn,
        df=state.df,
        schema=state.schema,
        session_id=body.session_id,
    )
    return AnalyticsResponse(**result)


@router.get("/health")
async def health(request: Request):
    state = request.app.state
    stats = get_table_stats(state.conn) if hasattr(state, "conn") else {}
    return {"status": "ok", "dataset": stats, "timestamp": time.time()}


@router.get("/game/stats")
async def dataset_stats(request: Request):
    state = request.app.state
    stats = get_table_stats(state.conn) if hasattr(state, "conn") else {}
    return stats


@router.get("/game/analytics/history")
async def query_history(session_id: str):
    history = get_history(session_id)
    return {"session_id": session_id, "history": history}
