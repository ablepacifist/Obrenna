"""Playwright-based PDF export. Builds self-contained HTML from an artifact spec.

Charts are rendered as inline SVG approximations (bar/area) so no dev server or
CDN is required. The HTML is written to a temp file, loaded file://, then printed.
"""
from __future__ import annotations

import html as _html
import json
import math
import tempfile
from pathlib import Path
from typing import Any


def _esc(value: Any) -> str:
    """HTML-escape any value before interpolating it into the export template.

    Card labels, table cells, titles, and report paragraphs originate from
    arbitrary CSV/user content and were previously interpolated unescaped
    into HTML rendered by a real headless Chromium (page.goto(file://...)).
    A crafted cell like ``</style><script>...</script>`` would execute in
    that context — this closes that hole for every interpolation site below.
    """
    return _html.escape(str(value), quote=True)


# ---------------------------------------------------------------------------
# Tiny SVG chart builders — deterministic, no Recharts needed.
# ---------------------------------------------------------------------------

def _bar_svg(x: list[str], series: list[dict], width: int = 560, height: int = 220) -> str:
    if not series or not x:
        return ""
    data = series[0]["data"]
    n = len(data)
    if n == 0:
        return ""
    max_val = max(data) if max(data) != 0 else 1
    pad_l, pad_r, pad_t, pad_b = 40, 10, 20, 40
    chart_w = width - pad_l - pad_r
    chart_h = height - pad_t - pad_b
    bar_w = max(4, chart_w // n - 4)
    step = chart_w / n
    bars = []
    for i, (label, val) in enumerate(zip(x, data)):
        bh = int(chart_h * val / max_val)
        bx = pad_l + int(i * step + (step - bar_w) / 2)
        by = pad_t + chart_h - bh
        bars.append(
            f'<rect x="{bx}" y="{by}" width="{bar_w}" height="{bh}" fill="#2D5A5F" rx="2"/>'
        )
        lx = bx + bar_w // 2
        ly = pad_t + chart_h + 16
        short = label[:8] + "…" if len(label) > 8 else label
        bars.append(
            f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="9" fill="#6B6762">{_esc(short)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(bars) + "</svg>"
    )


def _area_svg(x: list[str], series: list[dict], width: int = 560, height: int = 180) -> str:
    if not series or not x:
        return ""
    data = series[0]["data"]
    n = len(data)
    if n < 2:
        return _bar_svg(x, series, width, height)
    max_val = max(data) if max(data) != 0 else 1
    pad_l, pad_r, pad_t, pad_b = 40, 10, 20, 40
    chart_w = width - pad_l - pad_r
    chart_h = height - pad_t - pad_b
    step = chart_w / (n - 1)

    def pt(i: int) -> tuple[float, float]:
        px = pad_l + i * step
        py = pad_t + chart_h * (1 - data[i] / max_val)
        return px, py

    pts = [pt(i) for i in range(n)]
    poly = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    area_pts = (
        f"{pad_l:.1f},{pad_t + chart_h:.1f} "
        + poly
        + f" {pad_l + chart_w:.1f},{pad_t + chart_h:.1f}"
    )
    labels = "".join(
        f'<text x="{pts[i][0]:.1f}" y="{pad_t + chart_h + 16}" '
        f'text-anchor="middle" font-size="9" fill="#6B6762">{_esc(x[i][:8])}</text>'
        for i in range(0, n, max(1, n // 6))
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<polygon points="{area_pts}" fill="#2D5A5F" fill-opacity="0.15"/>'
        f'<polyline points="{poly}" fill="none" stroke="#2D5A5F" stroke-width="2"/>'
        + labels + "</svg>"
    )


def _chart_svg(chart: dict) -> str:
    t = chart.get("type", "bar")
    x = chart.get("x", [])
    series = chart.get("series", [])
    if t == "area":
        return _area_svg(x, series)
    return _bar_svg(x, series)


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_STYLE = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       font-size: 13px; color: #1F1D1B; background: #FAF9F7; margin: 0; padding: 24px 32px; }
h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; }
.summary { color: #6B6762; margin: 0 0 24px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.card { background: #fff; border: 1px solid #E8E5E0; border-radius: 8px;
        padding: 14px 18px; min-width: 130px; flex: 1; }
.card-label { font-size: 11px; color: #6B6762; text-transform: uppercase; letter-spacing: .03em; }
.card-value { font-size: 22px; font-weight: 600; margin: 4px 0 0; }
.card-desc { font-size: 11px; color: #A39E96; }
.section { margin-bottom: 28px; }
.section h2 { font-size: 14px; font-weight: 600; margin: 0 0 10px; color: #1F1D1B; }
.chart-box { background: #fff; border: 1px solid #E8E5E0; border-radius: 8px;
             padding: 16px; margin-bottom: 16px; }
.chart-title { font-size: 13px; font-weight: 500; margin: 0 0 10px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; padding: 6px 10px; background: #F4F2EE;
     border-bottom: 1px solid #E8E5E0; font-weight: 500; color: #6B6762; }
td { padding: 6px 10px; border-bottom: 1px solid #F4F2EE; }
.insights ul { margin: 0; padding: 0 0 0 18px; color: #6B6762; }
.insights li { margin-bottom: 4px; }
.md { line-height: 1.6; }
.badge-ok { color: #4A7A52; } .badge-warn { color: #A67535; } .badge-err { color: #A5453A; }
"""

def _cards_html(cards: list[dict]) -> str:
    items = []
    for c in cards:
        items.append(
            f'<div class="card">'
            f'<div class="card-label">{_esc(c.get("label",""))}</div>'
            f'<div class="card-value">{_esc(c.get("value",""))}</div>'
            f'<div class="card-desc">{_esc(c.get("description",""))}</div>'
            f'</div>'
        )
    return f'<div class="cards">{"".join(items)}</div>'


def _table_html(table: dict) -> str:
    cols = table.get("columns", [])
    rows = table.get("rows", [])
    ths = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    trs = "".join(
        "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    title = f'<div class="chart-title">{_esc(table.get("title",""))}</div>' if table.get("title") else ""
    return f'{title}<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>'


def _dashboard_html(spec: dict, title: str, summary: str) -> str:
    cards_h = _cards_html(spec.get("cards", []))
    charts_h = ""
    for ch in spec.get("charts", []):
        svg = _chart_svg(ch)
        charts_h += (
            f'<div class="chart-box">'
            f'<div class="chart-title">{_esc(ch.get("title",""))}</div>'
            f'{svg}'
            f'</div>'
        )
    tables_h = ""
    for t in spec.get("tables", []):
        tables_h += f'<div class="chart-box">{_table_html(t)}</div>'
    insights = spec.get("insights", [])
    insights_h = (
        '<div class="section insights"><h2>Insights</h2><ul>'
        + "".join(f"<li>{_esc(i)}</li>" for i in insights)
        + "</ul></div>"
    ) if insights else ""
    return (
        f'<h1>{_esc(title)}</h1><p class="summary">{_esc(summary)}</p>'
        f'{cards_h}'
        f'<div class="section"><h2>Charts</h2>{charts_h}</div>'
        f'<div class="section"><h2>Tables</h2>{tables_h}</div>'
        f'{insights_h}'
    )


def _report_html(spec: dict, title: str, summary: str) -> str:
    meta = []
    if spec.get("prepared"):
        meta.append(f"Prepared: {_esc(spec['prepared'])}")
    if spec.get("prepared_for"):
        meta.append(f"For: {_esc(spec['prepared_for'])}")
    if spec.get("prepared_by"):
        meta.append(f"By: {_esc(spec['prepared_by'])}")
    meta_h = f'<p class="summary">{" &nbsp;·&nbsp; ".join(meta)}</p>' if meta else ""
    secs = ""
    for s in spec.get("sections", []):
        paras = "".join(f"<p>{_esc(p)}</p>" for p in s.get("paragraphs", []))
        tbl = f'<div style="margin-top:8px">{_table_html(s["table"])}</div>' if s.get("table") else ""
        secs += f'<div class="section"><h2>{_esc(s.get("heading",""))}</h2>{paras}{tbl}</div>'
    return f'<h1>{_esc(title)}</h1>{meta_h}{secs}'


def _chart_html(spec: dict, title: str, summary: str) -> str:
    ch = spec.get("chart", {})
    svg = _chart_svg(ch)
    return (
        f'<h1>{_esc(title)}</h1><p class="summary">{_esc(summary)}</p>'
        f'<div class="chart-box">{svg}</div>'
    )


def _table_only_html(spec: dict, title: str, summary: str) -> str:
    t = spec.get("table", {})
    return (
        f'<h1>{_esc(title)}</h1><p class="summary">{_esc(summary)}</p>'
        f'<div class="chart-box">{_table_html(t)}</div>'
    )


def _document_html(spec: dict, title: str, summary: str) -> str:
    md = spec.get("markdown", "")
    # Minimal markdown → HTML (bold, headings, bullets).
    lines = []
    for line in md.split("\n"):
        if line.startswith("## "):
            lines.append(f"<h2>{_html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h2>{_html.escape(line[2:])}</h2>")
        elif line.startswith("- "):
            content = line[2:]
            content = _html.escape(content)
            content = content.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            lines.append(f"<li>{content}</li>")
        elif line.strip() == "":
            lines.append("<br>")
        else:
            escaped = _html.escape(line)
            escaped = escaped.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            lines.append(f"<p>{escaped}</p>")
    return (
        f'<h1>{_esc(title)}</h1><p class="summary">{_esc(summary)}</p>'
        f'<div class="md">{"".join(lines)}</div>'
    )


def _build_html(artifact: dict) -> str:
    at = artifact.get("artifact_type", "document")
    title = artifact.get("title", "Artifact")
    summary = artifact.get("summary", "")
    spec = artifact.get("spec", {})

    if at == "dashboard":
        body = _dashboard_html(spec, title, summary)
    elif at == "report":
        body = _report_html(spec, title, summary)
    elif at == "chart":
        body = _chart_html(spec, title, summary)
    elif at == "table":
        body = _table_only_html(spec, title, summary)
    else:
        body = _document_html(spec, title, summary)

    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{_STYLE}</style></head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# Public export function
# ---------------------------------------------------------------------------

def export_artifact_pdf(artifact: dict, output_path: Path) -> None:
    """Render artifact to PDF at output_path. Playwright must be installed."""
    from playwright.sync_api import sync_playwright

    html = _build_html(artifact)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        tmp_path = Path(f.name)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(tmp_path.as_uri())
            page.pdf(
                path=str(output_path),
                format="A4",
                margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"},
                print_background=True,
            )
            browser.close()
    finally:
        tmp_path.unlink(missing_ok=True)
