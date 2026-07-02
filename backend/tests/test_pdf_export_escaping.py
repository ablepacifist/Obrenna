"""Tests for MED-019: pdf_export HTML injection via unescaped artifact content.

Card labels, table cells, titles, and report paragraphs originate from
arbitrary CSV/user content (dashboard_builder, summarize) and were
previously interpolated into HTML via raw f-strings with no escaping. That
HTML is loaded by a real headless Chromium at a ``file://`` origin
(``export_artifact_pdf`` -> Playwright -> ``page.goto``), so a crafted CSV
cell containing ``</style><script>...</script>`` would execute as a script
in that context — local HTML/script injection with file:// origin
privileges. These tests exercise ``_build_html`` directly (no browser
needed) to confirm every interpolation site now escapes its input.
"""
from __future__ import annotations

from app.services.pdf_export import _build_html

_PAYLOAD = "</style><script>alert(1)</script>"


class TestDashboardEscaping:
    def test_card_label_is_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "Q1 numbers",
            "spec": {
                "cards": [{"label": _PAYLOAD, "value": 1, "description": ""}],
                "charts": [], "tables": [], "insights": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_card_value_and_description_are_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "",
            "spec": {
                "cards": [{"label": "Revenue", "value": _PAYLOAD, "description": _PAYLOAD}],
                "charts": [], "tables": [], "insights": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html

    def test_table_cell_is_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "",
            "spec": {
                "cards": [], "charts": [],
                "tables": [{"title": "Data", "columns": ["Name"], "rows": [[_PAYLOAD]]}],
                "insights": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html

    def test_table_column_header_is_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "",
            "spec": {
                "cards": [], "charts": [],
                "tables": [{"title": "Data", "columns": [_PAYLOAD], "rows": [["ok"]]}],
                "insights": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html

    def test_insight_text_is_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "",
            "spec": {"cards": [], "charts": [], "tables": [], "insights": [_PAYLOAD]},
        }
        html = _build_html(artifact)
        assert "<script>" not in html

    def test_chart_title_is_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "",
            "spec": {
                "cards": [],
                "charts": [{"type": "bar", "title": _PAYLOAD, "x": ["a"], "series": [{"name": "s", "data": [1]}]}],
                "tables": [], "insights": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html

    def test_chart_bar_label_is_escaped(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Sales",
            "summary": "",
            "spec": {
                "cards": [],
                "charts": [{"type": "bar", "title": "Chart", "x": [_PAYLOAD], "series": [{"name": "s", "data": [1]}]}],
                "tables": [], "insights": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html


class TestArtifactTitleAndSummaryEscaping:
    def test_top_level_title_is_escaped_for_every_artifact_type(self):
        for artifact_type, spec in [
            ("dashboard", {"cards": [], "charts": [], "tables": [], "insights": []}),
            ("report", {"sections": []}),
            ("chart", {"chart": {"type": "bar", "x": [], "series": []}}),
            ("table", {"table": {"columns": [], "rows": []}}),
            ("document", {"markdown": ""}),
        ]:
            artifact = {"artifact_type": artifact_type, "title": _PAYLOAD, "summary": "", "spec": spec}
            html = _build_html(artifact)
            assert "<script>" not in html, f"failed for artifact_type={artifact_type}"

    def test_top_level_summary_is_escaped(self):
        artifact = {
            "artifact_type": "chart",
            "title": "Chart",
            "summary": _PAYLOAD,
            "spec": {"chart": {"type": "bar", "x": [], "series": []}},
        }
        html = _build_html(artifact)
        assert "<script>" not in html


class TestReportEscaping:
    def test_prepared_by_fields_are_escaped(self):
        artifact = {
            "artifact_type": "report",
            "title": "Report",
            "summary": "",
            "spec": {
                "prepared": _PAYLOAD, "prepared_for": _PAYLOAD, "prepared_by": _PAYLOAD,
                "sections": [],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html

    def test_section_heading_and_paragraph_are_escaped(self):
        artifact = {
            "artifact_type": "report",
            "title": "Report",
            "summary": "",
            "spec": {
                "sections": [{"heading": _PAYLOAD, "paragraphs": [_PAYLOAD]}],
            },
        }
        html = _build_html(artifact)
        assert "<script>" not in html


class TestTableOnlyEscaping:
    def test_standalone_table_cells_are_escaped(self):
        artifact = {
            "artifact_type": "table",
            "title": "Table",
            "summary": "",
            "spec": {"table": {"columns": ["Name"], "rows": [[_PAYLOAD]]}},
        }
        html = _build_html(artifact)
        assert "<script>" not in html


class TestDocumentEscaping:
    def test_markdown_content_is_escaped(self):
        artifact = {
            "artifact_type": "document",
            "title": "Doc",
            "summary": "",
            "spec": {"markdown": f"# Heading\n{_PAYLOAD}\n- {_PAYLOAD}"},
        }
        html = _build_html(artifact)
        assert "<script>" not in html


class TestNormalContentStillRenders:
    """Escaping must not corrupt ordinary text."""

    def test_plain_dashboard_renders_readable_content(self):
        artifact = {
            "artifact_type": "dashboard",
            "title": "Q1 Sales",
            "summary": "Overview of Q1",
            "spec": {
                "cards": [{"label": "Revenue", "value": 1000, "description": "USD"}],
                "charts": [], "tables": [], "insights": ["Growth is up 10%"],
            },
        }
        html = _build_html(artifact)
        assert "Q1 Sales" in html
        assert "Revenue" in html
        assert "Growth is up 10%" in html
