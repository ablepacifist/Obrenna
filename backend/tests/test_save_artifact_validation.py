"""Tests for LOW-018: artifact specs are validated against the canonical
schema before being persisted.

Before the fix, ``_save_artifact`` wrote whatever dict a builder produced
straight to the DB with no schema check — nothing caught a spec that had
drifted from ``schemas/artifact.py`` (e.g. a builder bug producing a
malformed chart) before it reached the frontend renderer as a confusing
runtime error. The fix calls ``validate_artifact`` and logs a warning on
failure (log-and-continue, since builders are a trusted deterministic path
today — this is a safety net, not a hard boundary against untrusted input).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Artifact
from app.services.csv_profiler import load_csv, profile_dataframe
from app.services.dashboard_builder import build_dashboard

SAMPLE = Path(__file__).parents[2] / "sample-data" / "sales.csv"


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    local_session = sessionmaker(bind=engine)
    return local_session()


@pytest.fixture(scope="module")
def real_dashboard_spec():
    df = load_csv(str(SAMPLE))
    profile = profile_dataframe(df)
    return build_dashboard(df, profile, file_id="test123", filename="sales.csv")


class TestSaveArtifactValidatesRealSpecs:
    def test_real_dashboard_spec_passes_validation_and_saves(self, db, real_dashboard_spec):
        from app.routers.chat import _save_artifact

        record = _save_artifact(real_dashboard_spec, db)

        assert isinstance(record, Artifact)
        assert record.id == real_dashboard_spec["id"]
        assert record.artifact_type == "dashboard"


class TestSaveArtifactLogsOnValidationFailure:
    def test_invalid_spec_still_saves_but_logs_a_warning(self, db, caplog):
        import logging
        from app.routers.chat import _save_artifact

        # Missing required "spec.cards"/"spec.charts"/etc keys that
        # DashboardSpec requires — this should fail ArtifactAdapter validation.
        malformed = {
            "id": "bad-artifact-1",
            "artifact_type": "dashboard",
            "title": "Broken",
            "created_at": "2025-01-01T00:00:00Z",
            "spec": {"not_a_real_field": True},
        }

        with caplog.at_level(logging.WARNING, logger="app.routers.chat"):
            record = _save_artifact(malformed, db)

        # Log-and-continue: still saves (builders are trusted internally;
        # this is a safety net, not a hard gate).
        assert record.id == "bad-artifact-1"
        assert any("schema validation" in msg for msg in caplog.messages)

    def test_valid_spec_does_not_log_a_warning(self, db, caplog, real_dashboard_spec):
        import logging
        from app.routers.chat import _save_artifact

        with caplog.at_level(logging.WARNING, logger="app.routers.chat"):
            _save_artifact(real_dashboard_spec, db)

        assert not any("schema validation" in msg for msg in caplog.messages)
