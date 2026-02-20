"""Pydantic request / response models."""
from typing import Any, Optional
from pydantic import BaseModel, Field


class AnalyticsRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language analytics question")
    session_id: Optional[str] = Field(None, description="Optional session ID for context chaining")


class AnalyticsResponse(BaseModel):
    response: str
    metadata: dict[str, Any]
