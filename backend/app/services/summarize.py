"""Deterministic document + report builders (extractive; no LLM required).

If a local model is configured, chat routing may later swap in model-written prose.
For now these produce useful, deterministic artifacts directly from the data/text.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .dashboard_builder import _fmt, _primary_categorical, _primary_numeric


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


def summarize_csv(profile: dict, *, file_id: str | None, filename: str) -> dict:
    name = Path(filename).name
    cat = _primary_categorical(profile)
    num = _primary_numeric(profile)
    lines = [
        f"## Summary of {name}",
        "",
        f"- **Rows:** {profile['row_count']}",
        f"- **Columns:** {profile['column_count']}",
        f"- **Missing values:** {profile['missing_total']}",
    ]
    if num and profile["numeric"].get(num, {}).get("sum") is not None:
        st = profile["numeric"][num]
        lines.append(f"- **Total {num}:** {_fmt(st['sum'])} (avg {_fmt(st['mean'])})")
    if cat:
        top = profile["categorical"][cat]["top"]
        if top:
            joined = ", ".join(f"{v} ({c})" for v, c in top[:5])
            lines.append(f"- **Top {cat}:** {joined}")
    return _envelope(
        "document", f"Summary — {name}", "A plain-language summary of your file.",
        file_id, {"markdown": "\n".join(lines)},
    )


def summarize_text(text: str, *, file_id: str | None, filename: str) -> dict:
    name = Path(filename).name
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    lead = sentences[:5]
    body = "\n".join(f"- {s}" for s in lead) if lead else "_The file appears to be empty._"
    md = f"## Summary — {name}\n\n{body}"
    return _envelope(
        "document", f"Summary — {name}", "Key points extracted from your file.",
        file_id, {"markdown": md},
    )


def build_report_from_csv(
    df: pd.DataFrame, profile: dict, *, file_id: str | None, filename: str
) -> dict:
    name = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title() or "Data"
    cat = _primary_categorical(profile)
    num = _primary_numeric(profile)

    sections: list[dict[str, Any]] = [
        {
            "heading": "Overview",
            "paragraphs": [
                f"This report is generated from {Path(filename).name}, which contains "
                f"{profile['row_count']} records across {profile['column_count']} columns.",
            ],
        }
    ]

    if num:
        st = profile["numeric"][num]
        sections.append(
            {
                "heading": f"{num.title()} at a glance",
                "paragraphs": [
                    f"Total {num} is {_fmt(st['sum'])}, averaging {_fmt(st['mean'])} per "
                    f"record, ranging from {_fmt(st['min'])} to {_fmt(st['max'])}.",
                ],
            }
        )

    if cat:
        top = profile["categorical"][cat]["top"][:6]
        sections.append(
            {
                "heading": f"Breakdown by {cat}",
                "paragraphs": [
                    f"The leading {cat} is “{top[0][0]}”." if top else "No breakdown available."
                ],
                "table": {
                    "title": f"Top {cat}",
                    "columns": [cat, "Count"],
                    "rows": [[v, c] for v, c in top],
                },
            }
        )

    spec = {
        "prepared": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "prepared_by": "Obrenna (local)",
        "sections": sections,
    }
    return _envelope("report", f"{name} report", "An auto-generated report from your file.", file_id, spec)
