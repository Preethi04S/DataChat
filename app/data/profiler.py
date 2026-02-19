"""Data Quality Profiler — Automated data profiling, anomaly detection,
quality scoring, and distribution analysis.

Aligned with Akaike Technologies' BYOB (Build Your Own Brain) analytics platform.
Implements enterprise-grade data quality assessment for DataOps pipelines.
"""
from __future__ import annotations
import math
from typing import Any
import pandas as pd
import numpy as np
from app.data.schema import DatasetSchema
from app.core.config import DATA_QUALITY_THRESHOLDS
from app.core.logging import get_logger

logger = get_logger(__name__)


class DataQualityReport:
    """Comprehensive data quality assessment report."""

    def __init__(self):
        self.overall_score: float = 0.0
        self.completeness_score: float = 0.0
        self.consistency_score: float = 0.0
        self.uniqueness_score: float = 0.0
        self.validity_score: float = 0.0
        self.column_profiles: list[dict] = []
        self.warnings: list[dict] = []
        self.anomalies: list[dict] = []
        self.correlations: list[dict] = []
        self.distributions: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 1),
            "dimensions": {
                "completeness": round(self.completeness_score, 1),
                "consistency": round(self.consistency_score, 1),
                "uniqueness": round(self.uniqueness_score, 1),
                "validity": round(self.validity_score, 1),
            },
            "column_profiles": self.column_profiles,
            "warnings": self.warnings,
            "anomalies": self.anomalies,
            "correlations": self.correlations,
            "distributions": self.distributions,
        }


def profile_dataset(df: pd.DataFrame, schema: DatasetSchema) -> DataQualityReport:
    """Run full data quality profiling on the dataset.

    Implements the 4 dimensions of data quality:
    1. Completeness - missing value analysis
    2. Consistency - type consistency & format checks
    3. Uniqueness - duplicate detection
    4. Validity - range & distribution validation
    """
    report = DataQualityReport()
    thresholds = DATA_QUALITY_THRESHOLDS

    total_cells = len(df) * len(df.columns)
    missing_cells = int(df.isna().sum().sum())

    # ── Completeness Score ──
    if total_cells > 0:
        report.completeness_score = round((1 - missing_cells / total_cells) * 100, 1)
    else:
        report.completeness_score = 100.0

    # ── Uniqueness Score ──
    duplicate_rows = int(df.duplicated().sum())
    if len(df) > 0:
        report.uniqueness_score = round((1 - duplicate_rows / len(df)) * 100, 1)
    else:
        report.uniqueness_score = 100.0

    if duplicate_rows > 0:
        report.warnings.append({
            "level": "warning",
            "category": "uniqueness",
            "message": f"{duplicate_rows} duplicate rows detected ({round(duplicate_rows / len(df) * 100, 1)}%)",
        })

    # ── Per-Column Profiling ──
    consistency_scores = []
    validity_scores = []

    for col_info in schema.columns:
        col_name = col_info.name
        if col_name not in df.columns:
            continue
        series = df[col_name]
        profile = _profile_column(series, col_info, thresholds, report)
        report.column_profiles.append(profile)
        consistency_scores.append(profile.get("consistency", 100.0))
        validity_scores.append(profile.get("validity", 100.0))

    report.consistency_score = round(
        sum(consistency_scores) / max(len(consistency_scores), 1), 1
    )
    report.validity_score = round(
        sum(validity_scores) / max(len(validity_scores), 1), 1
    )

    # ── Correlation Analysis (numeric columns) ──
    numeric_cols = schema.numeric_columns
    if len(numeric_cols) >= 2:
        report.correlations = _compute_correlations(df, numeric_cols)

    # ── Distribution Analysis ──
    for col in numeric_cols[:5]:
        if col in df.columns:
            dist = _compute_distribution(df[col], col)
            if dist:
                report.distributions.append(dist)

    # ── Overall Score (weighted average) ──
    report.overall_score = round(
        report.completeness_score * 0.30
        + report.consistency_score * 0.25
        + report.uniqueness_score * 0.20
        + report.validity_score * 0.25,
        1,
    )

    logger.info(f"Data quality profile: score={report.overall_score}, "
                f"warnings={len(report.warnings)}, anomalies={len(report.anomalies)}")
    return report


def _profile_column(series: pd.Series, col_info, thresholds: dict,
                     report: DataQualityReport) -> dict:
    """Profile a single column for quality metrics."""
    col_name = col_info.name
    total = len(series)
    missing = int(series.isna().sum())
    missing_pct = round(missing / max(total, 1) * 100, 2)
    non_null = series.dropna()
    unique_count = int(non_null.nunique())

    profile: dict[str, Any] = {
        "column": col_name,
        "dtype": col_info.dtype,
        "total_count": total,
        "missing_count": missing,
        "missing_pct": missing_pct,
        "unique_count": unique_count,
        "unique_pct": round(unique_count / max(total - missing, 1) * 100, 2),
        "consistency": 100.0,
        "validity": 100.0,
    }

    # ── Missing Value Warnings ──
    if missing_pct >= thresholds["missing_pct_critical"]:
        report.warnings.append({
            "level": "critical",
            "category": "completeness",
            "column": col_name,
            "message": f"Column '{col_name}' has {missing_pct}% missing values (critical threshold: {thresholds['missing_pct_critical']}%)",
        })
        profile["validity"] -= 30
    elif missing_pct >= thresholds["missing_pct_warning"]:
        report.warnings.append({
            "level": "warning",
            "category": "completeness",
            "column": col_name,
            "message": f"Column '{col_name}' has {missing_pct}% missing values",
        })
        profile["validity"] -= 10

    # ── Numeric Column Profiling ──
    if col_info.dtype == "number" and len(non_null) > 0:
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if len(numeric) > 0:
            profile["stats"] = {
                "mean": round(float(numeric.mean()), 4),
                "median": round(float(numeric.median()), 4),
                "std": round(float(numeric.std()), 4) if len(numeric) > 1 else 0.0,
                "min": round(float(numeric.min()), 4),
                "max": round(float(numeric.max()), 4),
                "q25": round(float(numeric.quantile(0.25)), 4),
                "q75": round(float(numeric.quantile(0.75)), 4),
                "skewness": round(float(numeric.skew()), 4) if len(numeric) > 2 else 0.0,
                "kurtosis": round(float(numeric.kurtosis()), 4) if len(numeric) > 3 else 0.0,
                "zeros_count": int((numeric == 0).sum()),
                "negative_count": int((numeric < 0).sum()),
            }

            # ── Outlier Detection (IQR method) ──
            q1 = numeric.quantile(0.25)
            q3 = numeric.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                outliers = int(((numeric < lower_bound) | (numeric > upper_bound)).sum())
                profile["stats"]["outlier_count"] = outliers
                if outliers > 0:
                    outlier_pct = round(outliers / len(numeric) * 100, 1)
                    profile["stats"]["outlier_pct"] = outlier_pct
                    if outlier_pct > 5:
                        report.anomalies.append({
                            "column": col_name,
                            "type": "outliers",
                            "message": f"{outliers} outliers detected ({outlier_pct}%) in '{col_name}'",
                            "bounds": {"lower": round(float(lower_bound), 2),
                                       "upper": round(float(upper_bound), 2)},
                        })

            # ── Consistency: check coercion failures ──
            coerced = pd.to_numeric(non_null, errors="coerce")
            failed = int(coerced.isna().sum()) - int(non_null.isna().sum())
            if failed > 0:
                profile["consistency"] -= min(50, failed / max(len(non_null), 1) * 100)
                report.warnings.append({
                    "level": "warning",
                    "category": "consistency",
                    "column": col_name,
                    "message": f"{failed} values in '{col_name}' cannot be parsed as numbers",
                })

    # ── String Column Profiling ──
    elif col_info.dtype == "string" and len(non_null) > 0:
        str_vals = non_null.astype(str)
        lengths = str_vals.str.len()
        profile["stats"] = {
            "avg_length": round(float(lengths.mean()), 1),
            "min_length": int(lengths.min()),
            "max_length": int(lengths.max()),
            "empty_string_count": int((str_vals == "").sum()),
        }
        top_values = non_null.value_counts().head(5)
        profile["top_values"] = [
            {"value": str(val), "count": int(cnt)}
            for val, cnt in top_values.items()
        ]

        # ── Cardinality warnings ──
        cardinality_pct = unique_count / max(total - missing, 1) * 100
        if unique_count <= thresholds["low_cardinality_threshold"] and total > 20:
            profile["cardinality"] = "low"
        elif cardinality_pct >= thresholds["high_cardinality_pct"]:
            profile["cardinality"] = "high"
        else:
            profile["cardinality"] = "medium"

    return profile


def _compute_correlations(df: pd.DataFrame, numeric_cols: list[str]) -> list[dict]:
    """Compute pairwise Pearson correlations for numeric columns."""
    correlations = []
    numeric_df = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    corr_matrix = numeric_df.corr()

    for i, col_a in enumerate(numeric_cols):
        for col_b in numeric_cols[i + 1:]:
            val = corr_matrix.loc[col_a, col_b]
            if pd.notna(val) and not math.isnan(val):
                correlations.append({
                    "column_a": col_a,
                    "column_b": col_b,
                    "correlation": round(float(val), 4),
                    "strength": (
                        "strong" if abs(val) >= 0.7
                        else "moderate" if abs(val) >= 0.4
                        else "weak"
                    ),
                })
    correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return correlations[:10]


def _compute_distribution(series: pd.Series, col_name: str) -> dict | None:
    """Compute histogram-style distribution for a numeric column."""
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) < 2:
        return None
    try:
        counts, bin_edges = np.histogram(numeric, bins=min(20, len(numeric) // 5 + 1))
        bins = []
        for i in range(len(counts)):
            bins.append({
                "range": f"{round(float(bin_edges[i]), 2)}-{round(float(bin_edges[i + 1]), 2)}",
                "count": int(counts[i]),
            })
        return {"column": col_name, "bins": bins}
    except Exception:
        return None
