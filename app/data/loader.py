from __future__ import annotations
import io
import pandas as pd
from app.core.config import BOOKS_CSV_PATH, MAX_SCAN_ROWS
from app.core.logging import get_logger
from app.data.schema import DatasetSchema, infer_schema
from app.data.fingerprint import compute_fingerprint, compute_fingerprint_bytes

logger = get_logger(__name__)

_df: pd.DataFrame | None = None
_schema: DatasetSchema | None = None
_dataset_name: str = "books.csv"
_cleaning_report: dict | None = None


def _auto_clean(df: pd.DataFrame, schema: DatasetSchema) -> tuple[pd.DataFrame, dict]:
    """Run automatic data cleaning on load."""
    from app.data.cleaner import clean_dataset
    cleaned_df, report = clean_dataset(df, schema)
    return cleaned_df, report.to_dict()


def load_dataset(csv_path: str | None = None) -> tuple[pd.DataFrame, DatasetSchema]:
    global _df, _schema, _dataset_name, _cleaning_report

    path = csv_path or BOOKS_CSV_PATH
    logger.info(f"Loading dataset from {path}")

    fingerprint = compute_fingerprint(path)
    logger.info(f"Dataset SHA-256: {fingerprint}")

    df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")

    if len(df) > MAX_SCAN_ROWS:
        raise ValueError(
            f"Dataset has {len(df)} rows, exceeding MAX_SCAN_ROWS={MAX_SCAN_ROWS}. "
            "Use filters or increase the limit."
        )

    schema = infer_schema(df)
    logger.info(f"Schema inferred: {len(schema.columns)} columns, {schema.row_count} rows")
    logger.info(f"Display column: {schema.display_column}")

    # Auto-clean on load
    df, _cleaning_report = _auto_clean(df, schema)
    schema = infer_schema(df)
    logger.info(f"Post-cleaning: {schema.row_count} rows, "
                f"{_cleaning_report['rows_fixed']} fixes, "
                f"{_cleaning_report['outliers_found']} outliers handled")

    _df = df
    _schema = schema
    _dataset_name = str(path).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return df, schema


def load_from_bytes(content: bytes, filename: str) -> tuple[pd.DataFrame, DatasetSchema]:
    global _df, _schema, _dataset_name, _cleaning_report

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    logger.info(f"Loading uploaded file: {filename} (ext={ext})")

    compute_fingerprint_bytes(content)

    if ext == "csv":
        df = pd.read_csv(io.BytesIO(content), encoding="utf-8", on_bad_lines="skip")
    elif ext in ("xls", "xlsx"):
        df = pd.read_excel(io.BytesIO(content))
    elif ext == "json":
        df = pd.read_json(io.BytesIO(content))
    elif ext == "tsv":
        df = pd.read_csv(io.BytesIO(content), sep="\t", encoding="utf-8", on_bad_lines="skip")
    elif ext == "parquet":
        df = pd.read_parquet(io.BytesIO(content))
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Supported: CSV, JSON, Excel (xls/xlsx), TSV, Parquet")

    if len(df) > MAX_SCAN_ROWS:
        raise ValueError(
            f"Dataset has {len(df)} rows, exceeding MAX_SCAN_ROWS={MAX_SCAN_ROWS}."
        )

    schema = infer_schema(df)
    logger.info(f"Schema inferred: {len(schema.columns)} columns, {schema.row_count} rows")
    logger.info(f"Display column: {schema.display_column}")

    # Auto-clean on upload
    df, _cleaning_report = _auto_clean(df, schema)
    schema = infer_schema(df)
    logger.info(f"Post-cleaning: {schema.row_count} rows, "
                f"{_cleaning_report['rows_fixed']} fixes, "
                f"{_cleaning_report['outliers_found']} outliers handled")

    _df = df
    _schema = schema
    _dataset_name = filename
    return df, schema


def get_df() -> pd.DataFrame:
    if _df is None:
        raise RuntimeError("Dataset not loaded. Call load_dataset() first.")
    return _df


def get_schema() -> DatasetSchema:
    if _schema is None:
        raise RuntimeError("Dataset not loaded. Call load_dataset() first.")
    return _schema


def get_dataset_name() -> str:
    return _dataset_name


def get_cleaning_report() -> dict | None:
    return _cleaning_report
