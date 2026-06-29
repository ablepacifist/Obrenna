"""Deterministic CSV profiling with pandas. No LLM involved."""
from __future__ import annotations

from typing import Any

import pandas as pd


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def _is_datetime_like(s: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(s):
        return False
    non_null = s.dropna()
    if non_null.empty:
        return False
    sample = non_null.head(50)
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return parsed.notna().mean() >= 0.8


def column_kind(df: pd.DataFrame, col: str) -> str:
    s = df[col]
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if _is_datetime_like(s):
        return "datetime"
    return "categorical"


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Produce a deterministic profile: counts, numeric summaries, top categoricals, missing."""
    kinds = {col: column_kind(df, col) for col in df.columns}

    columns: list[dict[str, Any]] = []
    numeric: dict[str, Any] = {}
    categorical: dict[str, Any] = {}
    datetime_cols: dict[str, Any] = {}

    for col in df.columns:
        kind = kinds[col]
        missing = int(df[col].isna().sum())
        columns.append({"name": col, "kind": kind, "missing": missing})

        if kind == "numeric":
            s = pd.to_numeric(df[col], errors="coerce")
            numeric[col] = {
                "count": int(s.notna().sum()),
                "mean": _f(s.mean()),
                "min": _f(s.min()),
                "max": _f(s.max()),
                "sum": _f(s.sum()),
                "std": _f(s.std()),
                "missing": missing,
            }
        elif kind == "datetime":
            parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
            datetime_cols[col] = {
                "count": int(parsed.notna().sum()),
                "min": _s(parsed.min()),
                "max": _s(parsed.max()),
            }
        else:
            counts = df[col].astype("string").value_counts().head(8)
            categorical[col] = {
                "unique": int(df[col].nunique(dropna=True)),
                "missing": missing,
                "top": [[str(idx), int(cnt)] for idx, cnt in counts.items()],
            }

    return {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "columns": columns,
        "numeric": numeric,
        "categorical": categorical,
        "datetime": datetime_cols,
        "missing_total": int(df.isna().sum().sum()),
    }


def _f(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _s(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)
