from __future__ import annotations
from app.planner.models import QueryPlan, FilterOp
from app.data.schema import DatasetSchema
from app.core.config import MAX_RETURN_ROWS
from app.core.logging import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    pass


def validate_plan(plan: QueryPlan, schema: DatasetSchema) -> QueryPlan:
    valid_columns = set(schema.column_names)
    numeric_columns = set(schema.numeric_columns)

    if plan.select_columns:
        for col in plan.select_columns:
            if col not in valid_columns:
                resolved = _resolve_synonym(col, schema)
                if resolved:
                    plan.select_columns[plan.select_columns.index(col)] = resolved
                else:
                    raise ValidationError(f"Unknown column in select: '{col}'. Valid: {sorted(valid_columns)}")

    for f in plan.filters:
        if f.column not in valid_columns:
            resolved = _resolve_synonym(f.column, schema)
            if resolved:
                f.column = resolved
            else:
                raise ValidationError(f"Unknown column in filter: '{f.column}'. Valid: {sorted(valid_columns)}")

        col_info = schema.get_column(f.column)
        if col_info and col_info.dtype != "string" and f.op == FilterOp.contains:
            raise ValidationError(f"'contains' op is only valid for string columns, not '{f.column}' ({col_info.dtype})")

        if f.op == FilterOp.between:
            if not isinstance(f.value, list) or len(f.value) != 2:
                raise ValidationError(f"'between' op requires a list of exactly 2 values, got: {f.value}")

        if col_info and col_info.dtype == "number" and f.op in (FilterOp.gt, FilterOp.gte, FilterOp.lt, FilterOp.lte, FilterOp.eq, FilterOp.ne):
            if f.value is not None and not isinstance(f.value, list):
                try:
                    f.value = float(f.value)
                except (ValueError, TypeError):
                    raise ValidationError(f"Cannot convert filter value '{f.value}' to number for column '{f.column}'")

    if plan.sort:
        if plan.sort.column not in valid_columns:
            resolved = _resolve_synonym(plan.sort.column, schema)
            if resolved:
                plan.sort.column = resolved
            else:
                raise ValidationError(f"Unknown column in sort: '{plan.sort.column}'")

    plan.limit = min(plan.limit, MAX_RETURN_ROWS)

    if plan.aggregation:
        for col in plan.aggregation.groupby:
            if col not in valid_columns:
                resolved = _resolve_synonym(col, schema)
                if resolved:
                    idx = plan.aggregation.groupby.index(col)
                    plan.aggregation.groupby[idx] = resolved
                else:
                    raise ValidationError(f"Unknown column in groupby: '{col}'")

        for metric in plan.aggregation.metrics:
            if metric.op in ("mean", "min", "max", "sum"):
                if not metric.column:
                    raise ValidationError(f"'{metric.op}' aggregation requires a column")
                if metric.column not in valid_columns:
                    resolved = _resolve_synonym(metric.column, schema)
                    if resolved:
                        metric.column = resolved
                    else:
                        raise ValidationError(f"Unknown column in aggregation: '{metric.column}'")
                if metric.column not in numeric_columns:
                    raise ValidationError(f"'{metric.op}' requires numeric column, '{metric.column}' is not numeric")

    logger.info(f"Plan validated: intent={plan.intent}, filters={len(plan.filters)}, limit={plan.limit}")
    return plan


_SYNONYM_MAP = {
    "rating": ["average_rating", "rating", "ratings", "score"],
    "author": ["authors", "author", "writer", "by"],
    "year": ["published_year", "year", "pub_year", "publication_year"],
    "pages": ["num_pages", "pages", "page_count"],
    "genre": ["categories", "category", "genre", "genres"],
    "reviews": ["ratings_count", "reviews_count", "reviews", "num_reviews"],
    "name": ["title", "name", "book_title", "book_name"],
}


def _resolve_synonym(candidate: str, schema: DatasetSchema) -> str | None:
    candidate_lower = candidate.lower().strip()

    for col in schema.column_names:
        if col.lower() == candidate_lower:
            return col

    for col in schema.column_names:
        if candidate_lower in col.lower() or col.lower() in candidate_lower:
            return col

    for _key, synonyms in _SYNONYM_MAP.items():
        if candidate_lower in synonyms:
            for syn in synonyms:
                for col in schema.column_names:
                    if syn == col.lower():
                        return col

    return None
