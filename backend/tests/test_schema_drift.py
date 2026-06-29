"""Schema drift guard: validates known-good specs against the Pydantic models.

If this test fails, the Pydantic schema in app/schemas/artifact.py has drifted
from the JSON Schema in shared/artifact-schema.json. Fix the Pydantic model.
"""
from __future__ import annotations

import pytest

from app.schemas.artifact import validate_artifact


# --- known-good specs -------------------------------------------------------

DASHBOARD_SPEC = {
    "id": "abc123",
    "artifact_type": "dashboard",
    "title": "Sales dashboard",
    "summary": "A test dashboard",
    "created_at": "2024-01-01T00:00:00+00:00",
    "source_file_id": None,
    "spec": {
        "cards": [
            {"label": "Revenue", "value": "120,000", "description": "Total"},
            {"label": "Deals", "value": 42, "delta": "+5", "trend": "up"},
        ],
        "charts": [
            {
                "type": "bar",
                "title": "Revenue by region",
                "x": ["North", "South", "East"],
                "series": [{"name": "Revenue", "data": [40000.0, 35000.0, 45000.0]}],
            },
            {
                "type": "area",
                "title": "Revenue over time",
                "x": ["Jan", "Feb", "Mar"],
                "series": [{"name": "Revenue", "data": [30000.0, 40000.0, 50000.0]}],
                "stacked": False,
            },
        ],
        "tables": [
            {
                "title": "Summary",
                "columns": ["Region", "Revenue"],
                "rows": [["North", 40000], ["South", 35000]],
            }
        ],
        "insights": ["Revenue grew 25% month-over-month.", "North leads all regions."],
    },
}

REPORT_SPEC = {
    "id": "rep001",
    "artifact_type": "report",
    "title": "Q1 Report",
    "summary": "Quarterly summary",
    "created_at": "2024-01-01T00:00:00+00:00",
    "spec": {
        "prepared": "January 01, 2024",
        "prepared_by": "GrebGlob (local)",
        "sections": [
            {
                "heading": "Overview",
                "paragraphs": ["This report covers Q1 2024."],
            },
            {
                "heading": "Revenue",
                "paragraphs": ["Revenue totalled $120,000."],
                "table": {
                    "title": "Revenue breakdown",
                    "columns": ["Region", "Revenue"],
                    "rows": [["North", 40000]],
                },
            },
        ],
    },
}

CHART_SPEC = {
    "id": "cht001",
    "artifact_type": "chart",
    "title": "Revenue by region",
    "created_at": "2024-01-01T00:00:00+00:00",
    "spec": {
        "chart": {
            "type": "bar",
            "title": "Revenue by region",
            "x": ["North", "South"],
            "series": [{"name": "Revenue", "data": [40000.0, 35000.0]}],
        }
    },
}

TABLE_SPEC = {
    "id": "tbl001",
    "artifact_type": "table",
    "title": "Top regions",
    "created_at": "2024-01-01T00:00:00+00:00",
    "spec": {
        "table": {
            "title": "Top regions",
            "columns": ["Region", "Count"],
            "rows": [["North", 12], ["South", 9]],
        }
    },
}

DOCUMENT_SPEC = {
    "id": "doc001",
    "artifact_type": "document",
    "title": "Summary",
    "created_at": "2024-01-01T00:00:00+00:00",
    "spec": {
        "markdown": "## Summary\n\n- Total revenue: $120,000\n- Top region: North"
    },
}


@pytest.mark.parametrize("spec", [
    DASHBOARD_SPEC,
    REPORT_SPEC,
    CHART_SPEC,
    TABLE_SPEC,
    DOCUMENT_SPEC,
])
def test_valid_spec_passes_validation(spec):
    """Known-good specs must pass the Pydantic validator without errors."""
    validate_artifact(spec)  # raises on failure


def test_wrong_artifact_type_raises():
    bad = {**DASHBOARD_SPEC, "artifact_type": "unknown_type"}
    with pytest.raises(Exception):
        validate_artifact(bad)


def test_missing_required_field_raises():
    bad = {k: v for k, v in DASHBOARD_SPEC.items() if k != "spec"}
    with pytest.raises(Exception):
        validate_artifact(bad)


def test_chart_with_unknown_type_raises():
    bad_chart = {
        **CHART_SPEC,
        "spec": {
            "chart": {
                "type": "scatter",  # not in schema
                "title": "test",
                "x": ["a"],
                "series": [{"name": "x", "data": [1.0]}],
            }
        },
    }
    with pytest.raises(Exception):
        validate_artifact(bad_chart)
