from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class FilterOp(str, Enum):
    eq = "eq"
    ne = "ne"
    contains = "contains"
    in_ = "in"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    between = "between"


class Intent(str, Enum):
    lookup = "lookup"
    rank = "rank"
    filter = "filter"
    aggregate = "aggregate"
    unknown = "unknown"


class FilterClause(BaseModel):
    column: str
    op: FilterOp
    value: str | float | int | list | None = None


class SortClause(BaseModel):
    column: str
    direction: str = Field(default="desc", pattern=r"^(asc|desc)$")


class AggMetric(BaseModel):
    op: str = Field(..., pattern=r"^(count|mean|min|max|sum)$")
    column: Optional[str] = None


class Aggregation(BaseModel):
    groupby: list[str] = Field(default_factory=list)
    metrics: list[AggMetric] = Field(default_factory=list)


class QueryPlan(BaseModel):
    select_columns: Optional[list[str]] = None
    filters: list[FilterClause] = Field(default_factory=list)
    sort: Optional[SortClause] = None
    limit: int = Field(default=20, ge=1, le=50)
    aggregation: Optional[Aggregation] = None
    intent: Intent = Intent.unknown


QUERY_PLAN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "select_columns": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": ["eq", "ne", "contains", "in", "gt", "gte", "lt", "lte", "between"],
                    },
                    "value": {},
                },
                "required": ["column", "op", "value"],
            },
        },
        "sort": {
            "type": ["object", "null"],
            "properties": {
                "column": {"type": "string"},
                "direction": {"type": "string", "enum": ["asc", "desc"]},
            },
        },
        "limit": {"type": "integer"},
        "aggregation": {
            "type": ["object", "null"],
            "properties": {
                "groupby": {"type": "array", "items": {"type": "string"}},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["count", "mean", "min", "max", "sum"],
                            },
                            "column": {"type": ["string", "null"]},
                        },
                        "required": ["op", "column"],
                    },
                },
            },
        },
        "intent": {
            "type": "string",
            "enum": ["lookup", "rank", "filter", "aggregate", "unknown"],
        },
    },
    "required": ["filters", "limit", "intent"],
}
