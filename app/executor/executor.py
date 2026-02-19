from __future__ import annotations
import pandas as pd
from app.planner.models import QueryPlan, FilterOp
from app.data.schema import DatasetSchema
from app.core.config import MAX_RETURN_ROWS
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExecutionError(Exception):
    pass


def execute_plan(plan: QueryPlan, df: pd.DataFrame, schema: DatasetSchema) -> list[dict]:
    result = df.copy()
    rows_scanned = len(result)

    for f in plan.filters:
        result = _apply_filter(result, f, schema)

    if plan.aggregation and (plan.aggregation.groupby or plan.aggregation.metrics):
        return _execute_aggregation(result, plan, schema)

    if plan.sort:
        col = plan.sort.column
        ascending = plan.sort.direction == "asc"
        col_info = schema.get_column(col)
        if col_info and col_info.dtype == "number":
            result = result.sort_values(col, ascending=ascending, na_position="last")
        else:
            result = result.sort_values(col, ascending=ascending, na_position="last", key=lambda s: s.str.lower() if s.dtype == object else s)

    limit = min(plan.limit, MAX_RETURN_ROWS)
    result = result.head(limit)

    if plan.select_columns:
        valid_cols = [c for c in plan.select_columns if c in result.columns]
        if valid_cols:
            result = result[valid_cols]

    records = _df_to_records(result)
    logger.info(f"Executed: scanned={rows_scanned}, returned={len(records)}")
    return records


def _apply_filter(df: pd.DataFrame, f, schema: DatasetSchema) -> pd.DataFrame:
    col = f.column
    if col not in df.columns:
        raise ExecutionError(f"Column '{col}' not found in dataframe")

    col_info = schema.get_column(col)
    series = df[col]

    if f.op == FilterOp.eq:
        if col_info and col_info.dtype == "number":
            return df[series == float(f.value)]
        return df[series.astype(str).str.lower() == str(f.value).lower()]

    elif f.op == FilterOp.ne:
        if col_info and col_info.dtype == "number":
            return df[series != float(f.value)]
        return df[series.astype(str).str.lower() != str(f.value).lower()]

    elif f.op == FilterOp.contains:
        return df[series.astype(str).str.lower().str.contains(str(f.value).lower(), na=False)]

    elif f.op == FilterOp.in_:
        if isinstance(f.value, list):
            lower_vals = [str(v).lower() for v in f.value]
            return df[series.astype(str).str.lower().isin(lower_vals)]
        return df

    elif f.op == FilterOp.gt:
        return df[pd.to_numeric(series, errors="coerce") > float(f.value)]

    elif f.op == FilterOp.gte:
        return df[pd.to_numeric(series, errors="coerce") >= float(f.value)]

    elif f.op == FilterOp.lt:
        return df[pd.to_numeric(series, errors="coerce") < float(f.value)]

    elif f.op == FilterOp.lte:
        return df[pd.to_numeric(series, errors="coerce") <= float(f.value)]

    elif f.op == FilterOp.between:
        if isinstance(f.value, list) and len(f.value) == 2:
            numeric = pd.to_numeric(series, errors="coerce")
            lo, hi = float(f.value[0]), float(f.value[1])
            return df[(numeric >= lo) & (numeric <= hi)]
        return df

    return df


def _execute_aggregation(df: pd.DataFrame, plan: QueryPlan, schema: DatasetSchema) -> list[dict]:
    agg = plan.aggregation
    if not agg:
        return []

    agg_dict = {}
    rename_map = {}

    for metric in agg.metrics:
        if metric.op == "count":
            col_to_count = metric.column or df.columns[0]
            agg_dict[col_to_count] = "count"
            rename_map[col_to_count] = f"__agg__count"
        elif metric.op in ("mean", "min", "max", "sum"):
            if metric.column:
                agg_dict[metric.column] = metric.op
                rename_map[metric.column] = f"__agg__{metric.op}_{metric.column}"

    if not agg_dict:
        return []

    if agg.groupby:
        valid_groupby = [g for g in agg.groupby if g in df.columns]
        if not valid_groupby:
            raise ExecutionError(f"No valid groupby columns")

        grouped = df.groupby(valid_groupby, dropna=False).agg(agg_dict)
        grouped.columns = [rename_map.get(c, c) for c in grouped.columns]
        grouped = grouped.reset_index()

        first_metric_col = next(
            (c for c in grouped.columns if c.startswith("__agg__")), None
        )
        if first_metric_col and plan.sort:
            ascending = plan.sort.direction == "asc"
            grouped = grouped.sort_values(first_metric_col, ascending=ascending, na_position="last")
        elif first_metric_col:
            grouped = grouped.sort_values(first_metric_col, ascending=False, na_position="last")

        limit = min(plan.limit, MAX_RETURN_ROWS)
        grouped = grouped.head(limit)
        records = _df_to_records(grouped)
    else:
        row = {}
        for metric in agg.metrics:
            if metric.op == "count":
                row["__agg__count"] = int(len(df))
            elif metric.column and metric.column in df.columns:
                series = pd.to_numeric(df[metric.column], errors="coerce")
                if metric.op == "mean":
                    row[f"__agg__mean_{metric.column}"] = round(float(series.mean()), 4)
                elif metric.op == "min":
                    row[f"__agg__min_{metric.column}"] = float(series.min())
                elif metric.op == "max":
                    row[f"__agg__max_{metric.column}"] = float(series.max())
                elif metric.op == "sum":
                    row[f"__agg__sum_{metric.column}"] = float(series.sum())
        records = [row] if row else []

    logger.info(f"Aggregation executed: {len(records)} result rows")
    return records


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        record = {}
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                record[col] = None
            elif isinstance(val, float):
                record[col] = round(val, 4) if val != int(val) else int(val)
            else:
                record[col] = val
            if isinstance(record[col], (pd.Timestamp,)):
                record[col] = str(record[col])
        records.append(record)
    return records
