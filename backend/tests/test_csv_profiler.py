"""Tests for the CSV profiler service."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from app.services.csv_profiler import column_kind, load_csv, profile_dataframe

SAMPLE = Path(__file__).parents[2] / "sample-data" / "sales.csv"


@pytest.fixture
def sales_df():
    return load_csv(str(SAMPLE))


def test_load_csv_returns_dataframe(sales_df):
    assert isinstance(sales_df, pd.DataFrame)
    assert len(sales_df) > 0


def test_profile_row_count(sales_df):
    profile = profile_dataframe(sales_df)
    assert profile["row_count"] == len(sales_df)


def test_profile_column_count(sales_df):
    profile = profile_dataframe(sales_df)
    assert profile["column_count"] == len(sales_df.columns)


def test_profile_has_numeric_stats(sales_df):
    profile = profile_dataframe(sales_df)
    assert isinstance(profile["numeric"], dict)
    # sales.csv has numeric columns (revenue, deals, units).
    assert len(profile["numeric"]) > 0
    col = next(iter(profile["numeric"]))
    stats = profile["numeric"][col]
    for key in ("count", "mean", "min", "max", "sum", "missing"):
        assert key in stats, f"Missing key '{key}' in numeric stats for '{col}'"


def test_profile_has_categorical_stats(sales_df):
    profile = profile_dataframe(sales_df)
    assert isinstance(profile["categorical"], dict)
    assert len(profile["categorical"]) > 0
    col = next(iter(profile["categorical"]))
    stats = profile["categorical"][col]
    assert "unique" in stats
    assert "top" in stats
    assert isinstance(stats["top"], list)


def test_profile_missing_total_is_int(sales_df):
    profile = profile_dataframe(sales_df)
    assert isinstance(profile["missing_total"], int)


def test_column_kind_numeric():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    assert column_kind(df, "x") == "numeric"


def test_column_kind_categorical():
    df = pd.DataFrame({"cat": ["a", "b", "a", "c"]})
    assert column_kind(df, "cat") == "categorical"


def test_column_kind_datetime():
    df = pd.DataFrame({"dt": pd.to_datetime(["2024-01-01", "2024-02-01"])})
    assert column_kind(df, "dt") == "datetime"
