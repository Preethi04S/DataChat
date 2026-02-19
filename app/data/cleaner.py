"""Data Cleaning & Outlier Handling Module — Detects misaligned columns,
fixes shifted rows, handles outliers, and produces a clean dataset.

Aligned with Akaike Technologies' BYOB data quality pipeline.
"""
from __future__ import annotations
import re
import pandas as pd
import numpy as np
from app.core.logging import get_logger
from app.data.schema import DatasetSchema

logger = get_logger(__name__)


class CleaningReport:
    """Tracks all cleaning actions applied to the dataset."""

    def __init__(self):
        self.actions: list[dict] = []
        self.rows_fixed: int = 0
        self.rows_flagged: int = 0
        self.outliers_found: int = 0
        self.original_row_count: int = 0
        self.clean_row_count: int = 0

    def add_action(self, action_type: str, description: str,
                   rows_affected: int, details: list[dict] | None = None):
        self.actions.append({
            "type": action_type,
            "description": description,
            "rows_affected": rows_affected,
            "details": details or [],
        })

    def to_dict(self) -> dict:
        return {
            "original_row_count": self.original_row_count,
            "clean_row_count": self.clean_row_count,
            "rows_fixed": self.rows_fixed,
            "rows_flagged": self.rows_flagged,
            "outliers_found": self.outliers_found,
            "total_actions": len(self.actions),
            "actions": self.actions,
        }


def clean_dataset(df: pd.DataFrame, schema: DatasetSchema) -> tuple[pd.DataFrame, CleaningReport]:
    """Run full data cleaning pipeline on the dataset.

    Pipeline stages:
      1. Detect and fix shifted/misaligned columns
      2. Fix type mismatches (text in numeric columns, etc.)
      3. Handle logical inconsistencies (rating with 0 reviews, etc.)
      4. Detect and handle outliers (IQR method)
      5. Fix placeholder/invalid descriptions
      6. Remove exact duplicate rows
      7. Standardize text columns (trim whitespace, normalize)

    Returns the cleaned DataFrame and a detailed report.
    """
    report = CleaningReport()
    report.original_row_count = len(df)
    cleaned = df.copy()

    # Stage 1: Detect and fix shifted/misaligned columns
    cleaned = _fix_shifted_columns(cleaned, schema, report)

    # Stage 2: Fix type mismatches
    cleaned = _fix_type_mismatches(cleaned, schema, report)

    # Stage 3: Fix logical inconsistencies
    cleaned = _fix_logical_inconsistencies(cleaned, schema, report)

    # Stage 4: Detect and handle outliers
    cleaned = _handle_outliers(cleaned, schema, report)

    # Stage 5: Fix placeholder descriptions
    cleaned = _fix_placeholder_descriptions(cleaned, schema, report)

    # Stage 6: Remove exact duplicates
    cleaned = _remove_duplicates(cleaned, report)

    # Stage 7: Standardize text
    cleaned = _standardize_text(cleaned, schema, report)

    report.clean_row_count = len(cleaned)
    logger.info(f"Data cleaning complete: {report.rows_fixed} rows fixed, "
                f"{report.outliers_found} outliers handled, "
                f"{report.rows_flagged} rows flagged")
    return cleaned, report


def _fix_shifted_columns(df: pd.DataFrame, schema: DatasetSchema,
                         report: CleaningReport) -> pd.DataFrame:
    """Detect rows where column values appear shifted/misaligned and fix them.

    Detection strategy:
    - For each row, check if numeric columns contain non-numeric text
    - Check if text-only columns contain pure numbers where they shouldn't
    - Check if values match the pattern of an adjacent column better
    - Attempt to realign by shifting values left or right
    """
    numeric_cols = schema.numeric_columns
    string_cols = schema.string_columns
    fixed_rows = []

    for idx, row in df.iterrows():
        shift_detected = False
        issues = []

        # Check numeric columns for text values
        for col in numeric_cols:
            if col not in df.columns:
                continue
            val = row[col]
            if pd.notna(val) and isinstance(val, str):
                # Numeric column has a string — likely shifted
                try:
                    float(val)
                except (ValueError, TypeError):
                    shift_detected = True
                    issues.append(f"{col} contains text: '{str(val)[:50]}'")

        # Check if ISBN column contains non-ISBN data
        isbn_col = next((c for c in df.columns if "isbn" in c.lower()), None)
        if isbn_col and pd.notna(row.get(isbn_col)):
            isbn_val = str(row[isbn_col])
            if not re.match(r'^\d{10,13}$', isbn_val.strip()):
                shift_detected = True
                issues.append(f"{isbn_col} contains non-ISBN value: '{isbn_val[:30]}'")

        if shift_detected:
            fixed_row = _try_realign_row(row, df.columns.tolist(), schema)
            if fixed_row is not None:
                df.loc[idx] = fixed_row
                fixed_rows.append({"row": int(idx), "issues": issues, "status": "fixed"})
                report.rows_fixed += 1
            else:
                fixed_rows.append({"row": int(idx), "issues": issues, "status": "flagged"})
                report.rows_flagged += 1

    if fixed_rows:
        report.add_action(
            "shifted_column_fix",
            f"Detected {len(fixed_rows)} rows with potential column shifts. "
            f"Fixed {sum(1 for r in fixed_rows if r['status'] == 'fixed')}, "
            f"flagged {sum(1 for r in fixed_rows if r['status'] == 'flagged')}.",
            len(fixed_rows),
            fixed_rows[:20],
        )

    return df


def _try_realign_row(row: pd.Series, columns: list[str],
                     schema: DatasetSchema) -> pd.Series | None:
    """Attempt to realign a shifted row by trying 1-position left/right shifts."""
    values = row.values.tolist()
    n = len(values)

    # Try shift right by 1 (insert None at start, drop last)
    for shift in [1, -1]:
        candidate = [None] * n
        for i in range(n):
            src = i - shift
            if 0 <= src < n:
                candidate[i] = values[src]

        if _row_matches_schema(candidate, columns, schema):
            return pd.Series(candidate, index=columns)

    return None


def _row_matches_schema(values: list, columns: list[str],
                        schema: DatasetSchema) -> bool:
    """Check if a list of values matches the expected schema types."""
    score = 0
    total = 0
    for val, col in zip(values, columns):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        total += 1
        if col in schema.numeric_columns:
            try:
                float(val)
                score += 1
            except (ValueError, TypeError):
                pass
        elif col in schema.string_columns:
            if isinstance(val, str):
                score += 1
    return total > 0 and score / total > 0.8


def _fix_type_mismatches(df: pd.DataFrame, schema: DatasetSchema,
                         report: CleaningReport) -> pd.DataFrame:
    """Coerce numeric columns to proper types, replacing unparseable values with NaN."""
    fixes = []
    for col in schema.numeric_columns:
        if col not in df.columns:
            continue
        original_na = df[col].isna().sum()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        new_na = df[col].isna().sum()
        coerced = int(new_na - original_na)
        if coerced > 0:
            fixes.append({"column": col, "values_coerced_to_nan": coerced})
            report.rows_fixed += coerced

    if fixes:
        total_fixed = sum(f["values_coerced_to_nan"] for f in fixes)
        report.add_action(
            "type_mismatch_fix",
            f"Coerced {total_fixed} non-numeric values to NaN across {len(fixes)} columns.",
            total_fixed,
            fixes,
        )
    return df


def _fix_logical_inconsistencies(df: pd.DataFrame, schema: DatasetSchema,
                                 report: CleaningReport) -> pd.DataFrame:
    """Fix logically impossible values in the dataset."""
    fixes = []

    # Find rating and count columns
    rating_col = next((c for c in schema.numeric_columns
                       if "rating" in c.lower() and "count" not in c.lower()), None)
    count_col = next((c for c in schema.numeric_columns
                      if "count" in c.lower() or "reviews" in c.lower()), None)
    pages_col = next((c for c in schema.numeric_columns
                      if "page" in c.lower()), None)

    # Fix: rating > 0 but count == 0 → set rating to NaN
    if rating_col and count_col:
        mask = (df[rating_col] > 0) & (df[count_col] == 0)
        affected = int(mask.sum())
        if affected > 0:
            affected_rows = df.loc[mask, [schema.display_column, rating_col, count_col]].head(10)
            details = [
                {"row": int(idx), "title": str(r.get(schema.display_column, "")),
                 "old_rating": float(r[rating_col]), "ratings_count": 0,
                 "action": "rating set to NaN (no reviews)"}
                for idx, r in affected_rows.iterrows()
            ]
            df.loc[mask, rating_col] = np.nan
            fixes.append(("rating_without_reviews", affected, details))
            report.rows_fixed += affected

    # Fix: rating == 0 and count == 0 → set both to NaN (missing data)
    if rating_col and count_col:
        mask = (df[rating_col] == 0) & (df[count_col] == 0)
        affected = int(mask.sum())
        if affected > 0:
            affected_rows = df.loc[mask, [schema.display_column]].head(10)
            details = [
                {"row": int(idx), "title": str(r[schema.display_column]),
                 "action": "rating and count set to NaN (no data)"}
                for idx, r in affected_rows.iterrows()
            ]
            df.loc[mask, rating_col] = np.nan
            df.loc[mask, count_col] = np.nan
            fixes.append(("zero_rating_zero_count", affected, details))
            report.rows_fixed += affected

    # Fix: num_pages == 0 → set to NaN
    if pages_col:
        mask = df[pages_col] == 0
        affected = int(mask.sum())
        if affected > 0:
            affected_rows = df.loc[mask, [schema.display_column, pages_col]].head(10)
            details = [
                {"row": int(idx), "title": str(r[schema.display_column]),
                 "action": "page count set to NaN (was 0)"}
                for idx, r in affected_rows.iterrows()
            ]
            df.loc[mask, pages_col] = np.nan
            fixes.append(("zero_pages", affected, details))
            report.rows_fixed += affected

    for action_type, affected, details in fixes:
        report.add_action(
            f"logical_fix_{action_type}",
            f"Fixed {affected} rows with logical inconsistency: {action_type}",
            affected,
            details,
        )

    return df


def _handle_outliers(df: pd.DataFrame, schema: DatasetSchema,
                     report: CleaningReport) -> pd.DataFrame:
    """Detect outliers using IQR method and cap them (winsorize).

    Skips identifier columns (ISBN, ID) and year/date columns since
    these are not statistical measures — outlier capping would corrupt them.
    """
    outlier_details = []

    # Columns to skip: identifiers, years, counts that are naturally skewed
    skip_patterns = ["isbn", "id", "year", "date", "count", "reviews", "page"]

    for col in schema.numeric_columns:
        if col not in df.columns:
            continue
        # Skip identifier and year columns
        col_lower = col.lower()
        if any(pattern in col_lower for pattern in skip_patterns):
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) < 10:
            continue

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        # Find outliers
        outlier_mask = (df[col].notna()) & ((df[col] < lower) | (df[col] > upper))
        outlier_count = int(outlier_mask.sum())

        if outlier_count > 0:
            # Get examples before capping
            outlier_examples = df.loc[outlier_mask, [schema.display_column, col]].head(5)
            examples = [
                {"row": int(idx), "title": str(r.get(schema.display_column, "")),
                 "column": col, "original_value": float(r[col]),
                 "lower_bound": round(float(lower), 2),
                 "upper_bound": round(float(upper), 2)}
                for idx, r in outlier_examples.iterrows()
            ]

            # Winsorize (cap) outliers at bounds
            df.loc[df[col] < lower, col] = lower
            df.loc[df[col] > upper, col] = upper

            outlier_details.append({
                "column": col,
                "outlier_count": outlier_count,
                "iqr": round(float(iqr), 2),
                "lower_bound": round(float(lower), 2),
                "upper_bound": round(float(upper), 2),
                "examples": examples,
            })
            report.outliers_found += outlier_count

    if outlier_details:
        total = sum(d["outlier_count"] for d in outlier_details)
        report.add_action(
            "outlier_winsorization",
            f"Detected {total} outliers across {len(outlier_details)} columns. "
            f"Values capped at IQR bounds (winsorized).",
            total,
            outlier_details,
        )

    return df


def _fix_placeholder_descriptions(df: pd.DataFrame, schema: DatasetSchema,
                                  report: CleaningReport) -> pd.DataFrame:
    """Replace placeholder/invalid descriptions with NaN."""
    desc_col = next((c for c in schema.string_columns
                     if "descri" in c.lower()), None)
    if not desc_col or desc_col not in df.columns:
        return df

    placeholder_patterns = [
        r'^No Marketing Blurb$',
        r'^See:?$',
        r'^N/?A$',
        r'^None$',
        r'^TBD$',
        r'^TODO$',
        r'^\.\.\.$',
    ]
    combined = re.compile("|".join(placeholder_patterns), re.IGNORECASE)

    mask = df[desc_col].astype(str).str.match(combined)
    short_mask = df[desc_col].astype(str).str.len() < 10
    full_mask = mask | (short_mask & df[desc_col].notna())

    affected = int(full_mask.sum())
    if affected > 0:
        examples = df.loc[full_mask, [schema.display_column, desc_col]].head(10)
        details = [
            {"row": int(idx), "title": str(r.get(schema.display_column, "")),
             "old_description": str(r[desc_col])[:60],
             "action": "description set to NaN (placeholder)"}
            for idx, r in examples.iterrows()
        ]
        df.loc[full_mask, desc_col] = np.nan
        report.rows_fixed += affected
        report.add_action(
            "placeholder_description_fix",
            f"Replaced {affected} placeholder/minimal descriptions with NaN.",
            affected,
            details,
        )

    return df


def _remove_duplicates(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Remove exact duplicate rows (keep first occurrence)."""
    dup_mask = df.duplicated(keep="first")
    dup_count = int(dup_mask.sum())
    if dup_count > 0:
        report.add_action(
            "duplicate_removal",
            f"Removed {dup_count} exact duplicate rows.",
            dup_count,
        )
        df = df[~dup_mask].reset_index(drop=True)
    return df


def _standardize_text(df: pd.DataFrame, schema: DatasetSchema,
                      report: CleaningReport) -> pd.DataFrame:
    """Strip leading/trailing whitespace from text columns."""
    fixes = 0
    for col in schema.string_columns:
        if col not in df.columns:
            continue
        mask = df[col].notna()
        original = df.loc[mask, col].astype(str)
        stripped = original.str.strip()
        changed = (original != stripped).sum()
        if changed > 0:
            df.loc[mask, col] = stripped
            fixes += int(changed)

    # Fix duplicate subtitle == title
    title_col = schema.display_column
    subtitle_col = next((c for c in schema.string_columns if "subtitle" in c.lower()), None)
    if title_col and subtitle_col and subtitle_col in df.columns:
        mask = (df[title_col].notna() & df[subtitle_col].notna() &
                (df[title_col] == df[subtitle_col]))
        dup_count = int(mask.sum())
        if dup_count > 0:
            details = [
                {"row": int(idx), "title": str(df.loc[idx, title_col]),
                 "action": "subtitle cleared (was duplicate of title)"}
                for idx in df[mask].index[:10]
            ]
            df.loc[mask, subtitle_col] = np.nan
            fixes += dup_count
            report.add_action(
                "duplicate_subtitle_fix",
                f"Cleared {dup_count} subtitle fields that duplicated the title.",
                dup_count,
                details,
            )

    if fixes > 0:
        report.rows_fixed += fixes
        report.add_action(
            "text_standardization",
            f"Standardized whitespace in {fixes} text values.",
            fixes,
        )

    return df
