"""A partial settings update must not wipe the fields it doesn't mention.

The regression this pins actually happened: posting only
``{"orchestrator_override": null}`` to /api/settings/app reset
``setup_complete`` to False, which dropped the user back into the first-run
setup wizard as though their workspace had never been configured.

The cause is subtle enough to reintroduce. Every field on AppSettingsDTO has a
default, so an omitted field arrives looking exactly like a deliberate one --
and the handler assigned all of them unconditionally. The fix keys on
``model_dump(exclude_unset=True)``, which is the only thing that distinguishes
"absent" from "explicitly set to the default".
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AppSettings
from app.routers.settings import save_app_settings
from app.schemas.api import AppSettingsDTO


@pytest.fixture
def db():
    """A fully configured workspace, as a real user would have.

    Calls the handler directly rather than going through TestClient: the
    dependency-override plumbing is incidental to what is being pinned here,
    which is how the handler treats omitted fields.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    session.add(AppSettings(
        id=1,
        setup_complete=True,
        setup_mode="byo",
        theme="dark",
        active_models=["qwen3.5:9b"],
        managed_plan={"ctx": 8192},
        workers_enabled=True,
        orchestrator_override="qwen2.5-coder-14b",
    ))
    session.commit()
    yield session
    session.close()


def post(db, raw: dict):
    """Mimic the wire: only keys actually present are 'set' on the model."""
    return save_app_settings(AppSettingsDTO(**raw), db=db).model_dump()


def test_clearing_only_the_override_preserves_everything_else(db):
    """The exact call that caused the outage."""
    body = post(db, {"orchestrator_override": None})

    # The one field asked for did change.
    assert body["orchestrator_override"] is None
    # Nothing else did. setup_complete is the one that locked the user out.
    assert body["setup_complete"] is True
    assert body["setup_mode"] == "byo"
    assert body["theme"] == "dark"
    assert body["active_models"] == ["qwen3.5:9b"]
    assert body["managed_plan"] == {"ctx": 8192}


def test_changing_one_field_leaves_the_override_alone(db):
    body = post(db, {"theme": "light"})
    assert body["theme"] == "light"
    assert body["orchestrator_override"] == "qwen2.5-coder-14b"
    assert body["setup_complete"] is True


def test_explicit_false_is_honoured_not_treated_as_absent(db):
    """The flip side: a caller that really means False must still win, or
    'exclude_unset' would just trade one silent-wrong-value bug for another."""
    assert post(db, {"setup_complete": False})["setup_complete"] is False


def test_full_payload_still_replaces_everything(db):
    """The settings screen posts the whole object; that must keep working."""
    body = post(db, {
        "setup_complete": True,
        "setup_mode": "managed",
        "theme": "light",
        "active_models": ["a"],
        "managed_plan": {"ctx": 4096},
        "workers_enabled": False,
        "orchestrator_override": "some-model",
    })
    assert body["setup_mode"] == "managed"
    assert body["workers_enabled"] is False
    assert body["orchestrator_override"] == "some-model"


def test_empty_payload_changes_nothing(db):
    body = post(db, {})
    assert body["setup_complete"] is True
    assert body["setup_mode"] == "byo"
    assert body["orchestrator_override"] == "qwen2.5-coder-14b"
