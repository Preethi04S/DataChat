from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import re


@dataclass
class ColumnInfo:
    name: str
    dtype: str  # "string", "number", "date", "bool"
    missing_count: int = 0
    missing_pct: float = 0.0
    sample_values: list = field(default_factory=list)
    unique_count: int = 0


@dataclass
class DatasetSchema:
    columns: list[ColumnInfo] = field(default_factory=list)
    row_count: int = 0
    display_column: str = ""

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def numeric_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.dtype == "number"]

    @property
    def string_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.dtype == "string"]

    def get_column(self, name: str) -> ColumnInfo | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    def has_column(self, name: str) -> bool:
        return name in self.column_names

    def to_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "display_column": self.display_column,
            "columns": [
                {
                    "name": c.name,
                    "dtype": c.dtype,
                    "missing_count": c.missing_count,
                    "missing_pct": round(c.missing_pct, 2),
                    "sample_values": c.sample_values,
                    "unique_count": c.unique_count,
                }
                for c in self.columns
            ],
        }


def _infer_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if len(non_null) == 0:
        return "string"

    if pd.api.types.is_bool_dtype(series):
        return "bool"

    if pd.api.types.is_numeric_dtype(series):
        return "number"

    sample = non_null.head(50).astype(str)
    date_pattern = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")
    date_matches = sample.apply(lambda x: bool(date_pattern.match(x))).sum()
    if date_matches > len(sample) * 0.7:
        return "date"

    try:
        pd.to_numeric(non_null.head(100))
        return "number"
    except (ValueError, TypeError):
        pass

    return "string"


def _pick_display_column(schema: DatasetSchema) -> str:
    title_patterns = ["title", "book", "name", "book_title", "book_name"]
    for pattern in title_patterns:
        for col in schema.columns:
            if col.dtype == "string" and pattern in col.name.lower():
                return col.name

    best_col = ""
    best_uniqueness = 0.0
    for col in schema.columns:
        if col.dtype == "string" and col.unique_count > 0:
            uniqueness = col.unique_count / max(1, schema.row_count - col.missing_count)
            if uniqueness > best_uniqueness:
                best_uniqueness = uniqueness
                best_col = col.name

    return best_col or (schema.columns[0].name if schema.columns else "")


def infer_schema(df: pd.DataFrame) -> DatasetSchema:
    schema = DatasetSchema(row_count=len(df))

    for col_name in df.columns:
        series = df[col_name]
        dtype = _infer_type(series)

        if dtype == "number":
            df[col_name] = pd.to_numeric(series, errors="coerce")

        missing = int(series.isna().sum())
        non_null = series.dropna()
        sample_vals = non_null.head(5).tolist()

        col_info = ColumnInfo(
            name=col_name,
            dtype=dtype,
            missing_count=missing,
            missing_pct=(missing / len(df) * 100) if len(df) > 0 else 0.0,
            sample_values=[str(v) for v in sample_vals],
            unique_count=int(non_null.nunique()),
        )
        schema.columns.append(col_info)

    schema.display_column = _pick_display_column(schema)
    return schema
