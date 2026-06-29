"""Pydantic mirror of shared/artifact-schema.json (the canonical artifact contract).

Hand-authored for clean discriminated-union types; kept in sync with the JSON Schema
by tests/test_schema_drift.py. The frontend's TS types are generated from the same
JSON Schema (see scripts/codegen.mjs).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Scalar = Union[str, int, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- shared building blocks -------------------------------------------------

class Card(_Strict):
    label: str
    value: Scalar
    delta: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    description: str | None = None


class Series(_Strict):
    name: str
    data: list[float]


class Chart(_Strict):
    type: Literal["bar", "line", "area", "pie"]
    title: str
    x: list[str]
    series: list[Series]
    stacked: bool | None = None
    note: str | None = None


class Table(_Strict):
    title: str
    columns: list[str]
    rows: list[list[Scalar]]


class ReportSection(_Strict):
    heading: str
    paragraphs: list[str]
    table: Table | None = None


# --- per-type spec bodies ---------------------------------------------------

class DashboardSpec(_Strict):
    cards: list[Card]
    charts: list[Chart]
    tables: list[Table]
    insights: list[str]


class ReportSpec(_Strict):
    prepared: str | None = None
    prepared_for: str | None = None
    prepared_by: str | None = None
    sections: list[ReportSection]


class ChartSpec(_Strict):
    chart: Chart


class TableSpec(_Strict):
    table: Table


class DocumentSpec(_Strict):
    markdown: str


# --- artifact envelopes (discriminated on artifact_type) --------------------

class _ArtifactBase(_Strict):
    id: str
    title: str
    summary: str | None = None
    created_at: str
    source_file_id: str | None = None


class DashboardArtifact(_ArtifactBase):
    artifact_type: Literal["dashboard"] = "dashboard"
    spec: DashboardSpec


class ReportArtifact(_ArtifactBase):
    artifact_type: Literal["report"] = "report"
    spec: ReportSpec


class ChartArtifact(_ArtifactBase):
    artifact_type: Literal["chart"] = "chart"
    spec: ChartSpec


class TableArtifact(_ArtifactBase):
    artifact_type: Literal["table"] = "table"
    spec: TableSpec


class DocumentArtifact(_ArtifactBase):
    artifact_type: Literal["document"] = "document"
    spec: DocumentSpec


Artifact = Annotated[
    Union[
        DashboardArtifact,
        ReportArtifact,
        ChartArtifact,
        TableArtifact,
        DocumentArtifact,
    ],
    Field(discriminator="artifact_type"),
]

ArtifactAdapter: TypeAdapter[Artifact] = TypeAdapter(Artifact)


def validate_artifact(data: dict) -> "Artifact":
    """Validate a raw dict against the artifact union. Raises ValidationError."""
    return ArtifactAdapter.validate_python(data)
