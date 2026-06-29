"""Deterministically turn a profiled CSV into a DashboardArtifact spec. No LLM.

Produces the same generic structure the mock renders (KPI cards, charts, a table,
insights) from arbitrary CSV columns. The content comes entirely from the data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

MAX_CATEGORIES = 6


def build_dashboard(
    df: pd.DataFrame,
    profile: dict[str, Any],
    *,
    file_id: str | None,
    filename: str,
    instruction: str | None = None,
) -> dict[str, Any]:
    title = _title_from_filename(filename)

    numeric_cols = list(profile["numeric"].keys())
    categorical_cols = list(profile["categorical"].keys())
    datetime_cols = list(profile["datetime"].keys())

    primary_num = _primary_numeric(profile)
    primary_cat = _primary_categorical(profile)

    cards = _build_cards(profile, primary_num)
    charts = _build_charts(df, profile, primary_num, primary_cat, datetime_cols)
    tables = _build_tables(df, profile, primary_num, primary_cat)
    insights = _build_insights(profile, primary_num, primary_cat, datetime_cols)

    return {
        "id": uuid.uuid4().hex,
        "artifact_type": "dashboard",
        "title": title,
        "summary": _summary(profile, primary_num, primary_cat),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file_id": file_id,
        "spec": {
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "insights": insights,
        },
    }


# --- pieces -----------------------------------------------------------------

def _build_cards(profile: dict, primary_num: str | None) -> list[dict]:
    cards: list[dict] = [
        {"label": "Rows", "value": profile["row_count"], "description": "Records in the file"},
        {"label": "Columns", "value": profile["column_count"], "description": "Fields detected"},
    ]
    if primary_num:
        stats = profile["numeric"][primary_num]
        if stats.get("sum") is not None:
            cards.append(
                {
                    "label": f"Total {primary_num}",
                    "value": _fmt(stats["sum"]),
                    "description": f"Sum across {stats['count']} values",
                }
            )
        if stats.get("mean") is not None:
            cards.append(
                {
                    "label": f"Average {primary_num}",
                    "value": _fmt(stats["mean"]),
                    "description": "Mean per record",
                }
            )
    missing = profile["missing_total"]
    cards.append(
        {
            "label": "Missing values",
            "value": missing,
            "trend": "flat" if missing == 0 else "down",
            "description": "Empty cells across all columns",
        }
    )
    return cards[:5]


def _build_charts(
    df: pd.DataFrame,
    profile: dict,
    primary_num: str | None,
    primary_cat: str | None,
    datetime_cols: list[str],
) -> list[dict]:
    charts: list[dict] = []

    # Trend over time, if we have a date column and a numeric measure.
    if datetime_cols and primary_num:
        dt = datetime_cols[0]
        chart = _time_series_chart(df, dt, primary_num)
        if chart:
            charts.append(chart)

    # Measure (or counts) by the leading categorical column.
    if primary_cat:
        if primary_num:
            charts.append(_measure_by_category(df, primary_cat, primary_num))
        else:
            charts.append(_counts_by_category(profile, primary_cat))

    return charts


def _build_tables(
    df: pd.DataFrame,
    profile: dict,
    primary_num: str | None,
    primary_cat: str | None,
) -> list[dict]:
    tables: list[dict] = []

    if profile["numeric"]:
        rows = []
        for col, st in profile["numeric"].items():
            rows.append(
                [
                    col,
                    st["count"],
                    _fmt(st["mean"]),
                    _fmt(st["min"]),
                    _fmt(st["max"]),
                    _fmt(st["sum"]),
                ]
            )
        tables.append(
            {
                "title": "Numeric summary",
                "columns": ["Column", "Count", "Mean", "Min", "Max", "Sum"],
                "rows": rows,
            }
        )

    if primary_cat:
        top = profile["categorical"][primary_cat]["top"][:MAX_CATEGORIES]
        tables.append(
            {
                "title": f"Top {primary_cat}",
                "columns": [primary_cat, "Count"],
                "rows": [[v, c] for v, c in top],
            }
        )

    return tables


def _build_insights(
    profile: dict,
    primary_num: str | None,
    primary_cat: str | None,
    datetime_cols: list[str],
) -> list[str]:
    out = [
        f"The file has {profile['row_count']} rows across {profile['column_count']} columns."
    ]
    if primary_cat:
        top = profile["categorical"][primary_cat]["top"]
        if top:
            out.append(
                f"The most common {primary_cat} is “{top[0][0]}” "
                f"({top[0][1]} records)."
            )
    if primary_num:
        st = profile["numeric"][primary_num]
        if st.get("sum") is not None:
            out.append(
                f"Total {primary_num} is {_fmt(st['sum'])}, averaging "
                f"{_fmt(st['mean'])} per record."
            )
    if datetime_cols:
        dt = profile["datetime"][datetime_cols[0]]
        if dt.get("min") and dt.get("max"):
            out.append(f"Records span {dt['min'][:10]} to {dt['max'][:10]}.")
    if profile["missing_total"]:
        out.append(
            f"There are {profile['missing_total']} missing values to be aware of."
        )
    else:
        out.append("No missing values were found.")
    return out


# --- chart builders ---------------------------------------------------------

def _time_series_chart(df: pd.DataFrame, dt_col: str, num_col: str) -> dict | None:
    parsed = pd.to_datetime(df[dt_col], errors="coerce", format="mixed")
    values = pd.to_numeric(df[num_col], errors="coerce")
    frame = pd.DataFrame({"period": parsed.dt.to_period("M"), "value": values}).dropna()
    if frame.empty:
        return None
    grouped = frame.groupby("period")["value"].sum().sort_index()
    single_year = grouped.index.year.nunique() == 1
    labels = [p.strftime("%b" if single_year else "%Y-%m") for p in grouped.index]
    return {
        "type": "area",
        "title": f"{num_col} over time",
        "x": labels,
        "series": [{"name": num_col, "data": [round(float(v), 2) for v in grouped.values]}],
    }


def _measure_by_category(df: pd.DataFrame, cat_col: str, num_col: str) -> dict:
    values = pd.to_numeric(df[num_col], errors="coerce")
    frame = pd.DataFrame({"cat": df[cat_col].astype("string"), "value": values}).dropna()
    grouped = frame.groupby("cat")["value"].sum().sort_values(ascending=False).head(MAX_CATEGORIES)
    return {
        "type": "bar",
        "title": f"{num_col} by {cat_col}",
        "x": [str(i) for i in grouped.index],
        "series": [{"name": num_col, "data": [round(float(v), 2) for v in grouped.values]}],
    }


def _counts_by_category(profile: dict, cat_col: str) -> dict:
    top = profile["categorical"][cat_col]["top"][:MAX_CATEGORIES]
    return {
        "type": "bar",
        "title": f"Records by {cat_col}",
        "x": [str(v) for v, _ in top],
        "series": [{"name": "Count", "data": [float(c) for _, c in top]}],
    }


# --- helpers ----------------------------------------------------------------

def _primary_numeric(profile: dict) -> str | None:
    best, best_sum = None, None
    for col, st in profile["numeric"].items():
        s = st.get("sum")
        if s is None:
            continue
        if best_sum is None or abs(s) > abs(best_sum):
            best, best_sum = col, s
    return best


def _primary_categorical(profile: dict) -> str | None:
    # Prefer a column with a small-ish number of distinct values (a real category).
    candidates = sorted(
        profile["categorical"].items(),
        key=lambda kv: (kv[1]["unique"] > 1, kv[1]["unique"]),
    )
    for col, st in candidates:
        if 1 < st["unique"] <= max(20, profile["row_count"] // 2 or 1):
            return col
    return next(iter(profile["categorical"]), None)


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    stem = stem[:1].upper() + stem[1:] if stem else "Data"
    return f"{stem} dashboard"


def _summary(profile: dict, primary_num: str | None, primary_cat: str | None) -> str:
    bits = [f"{profile['row_count']} rows, {profile['column_count']} columns"]
    if primary_num:
        bits.append(f"keyed on {primary_num}")
    if primary_cat:
        bits.append(f"broken down by {primary_cat}")
    return ", ".join(bits) + "."


def _fmt(value: float | int | None) -> str | int | float:
    if value is None:
        return "—"
    if isinstance(value, (int,)) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value):,}"
    return f"{value:,.2f}"


# --- single-artifact derivations (used by chat routing) ---------------------

def _envelope(artifact_type: str, title: str, summary: str, file_id: str | None, spec: dict) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "artifact_type": artifact_type,
        "title": title,
        "summary": summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file_id": file_id,
        "spec": spec,
    }


def build_chart_artifact(
    df: pd.DataFrame, profile: dict, *, file_id: str | None, filename: str
) -> dict:
    primary_num = _primary_numeric(profile)
    primary_cat = _primary_categorical(profile)
    if primary_cat and primary_num:
        chart = _measure_by_category(df, primary_cat, primary_num)
    elif primary_cat:
        chart = _counts_by_category(profile, primary_cat)
    else:
        # Fall back to a bar of the first numeric column's first values.
        col = next(iter(profile["numeric"]), None)
        series = pd.to_numeric(df[col], errors="coerce").dropna().head(MAX_CATEGORIES) if col else []
        chart = {
            "type": "bar",
            "title": f"{col or 'Values'}",
            "x": [str(i + 1) for i in range(len(series))],
            "series": [{"name": col or "value", "data": [float(v) for v in series]}],
        }
    return _envelope("chart", chart["title"], "Generated from your file.", file_id, {"chart": chart})


def build_table_artifact(
    df: pd.DataFrame, profile: dict, *, file_id: str | None, filename: str
) -> dict:
    primary_cat = _primary_categorical(profile)
    if primary_cat:
        top = profile["categorical"][primary_cat]["top"][:MAX_CATEGORIES]
        table = {
            "title": f"Top {primary_cat}",
            "columns": [primary_cat, "Count"],
            "rows": [[v, c] for v, c in top],
        }
    else:
        head = df.head(10)
        table = {
            "title": "First rows",
            "columns": [str(c) for c in head.columns],
            "rows": [[_cell(v) for v in row] for row in head.itertuples(index=False)],
        }
    return _envelope("table", table["title"], "Generated from your file.", file_id, {"table": table})


def _cell(v: Any) -> str | int | float:
    if pd.isna(v):
        return ""
    if isinstance(v, (int, float)):
        return v
    return str(v)
