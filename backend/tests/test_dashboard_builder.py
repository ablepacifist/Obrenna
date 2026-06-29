"""Tests for the dashboard builder service."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.csv_profiler import load_csv, profile_dataframe
from app.services.dashboard_builder import (
    build_chart_artifact,
    build_dashboard,
    build_table_artifact,
)

SAMPLE = Path(__file__).parents[2] / "sample-data" / "sales.csv"


@pytest.fixture(scope="module")
def df_profile():
    df = load_csv(str(SAMPLE))
    profile = profile_dataframe(df)
    return df, profile


def test_build_dashboard_structure(df_profile):
    df, profile = df_profile
    result = build_dashboard(df, profile, file_id="test123", filename="sales.csv")
    assert result["artifact_type"] == "dashboard"
    assert "id" in result
    assert "title" in result
    assert "created_at" in result
    spec = result["spec"]
    assert "cards" in spec
    assert "charts" in spec
    assert "tables" in spec
    assert "insights" in spec


def test_dashboard_cards_are_non_empty(df_profile):
    df, profile = df_profile
    result = build_dashboard(df, profile, file_id=None, filename="test.csv")
    cards = result["spec"]["cards"]
    assert len(cards) >= 2
    for card in cards:
        assert "label" in card
        assert "value" in card


def test_dashboard_charts_have_series(df_profile):
    df, profile = df_profile
    result = build_dashboard(df, profile, file_id=None, filename="test.csv")
    for chart in result["spec"]["charts"]:
        assert "type" in chart
        assert "series" in chart
        assert isinstance(chart["series"], list)
        assert len(chart["series"]) >= 1
        for s in chart["series"]:
            assert "name" in s
            assert "data" in s
            assert isinstance(s["data"], list)


def test_dashboard_tables_have_rows(df_profile):
    df, profile = df_profile
    result = build_dashboard(df, profile, file_id=None, filename="test.csv")
    for table in result["spec"]["tables"]:
        assert "columns" in table
        assert "rows" in table
        assert isinstance(table["rows"], list)


def test_dashboard_insights_are_strings(df_profile):
    df, profile = df_profile
    result = build_dashboard(df, profile, file_id=None, filename="test.csv")
    insights = result["spec"]["insights"]
    assert all(isinstance(i, str) for i in insights)


def test_build_chart_artifact(df_profile):
    df, profile = df_profile
    result = build_chart_artifact(df, profile, file_id=None, filename="sales.csv")
    assert result["artifact_type"] == "chart"
    assert "chart" in result["spec"]
    assert "series" in result["spec"]["chart"]


def test_build_table_artifact(df_profile):
    df, profile = df_profile
    result = build_table_artifact(df, profile, file_id=None, filename="sales.csv")
    assert result["artifact_type"] == "table"
    assert "table" in result["spec"]


def test_title_from_filename(df_profile):
    df, profile = df_profile
    result = build_dashboard(df, profile, file_id=None, filename="my_sales_data.csv")
    assert "My sales data" in result["title"]
