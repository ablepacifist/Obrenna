"""Database engine, session, and one-time initialization (SQLAlchemy 2.0)."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL, DEFAULT_BASE_URL, ensure_dirs

ensure_dirs()

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables and ensure singleton rows for settings exist."""
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(engine)

    # Run idempotent schema migrations (new tables, columns, backfill).
    from .services import migrations
    with SessionLocal() as db:
        migrations.run_migrations(db)

    with SessionLocal() as db:
        if db.get(models.AppSettings, 1) is None:
            db.add(
                models.AppSettings(
                    id=1,
                    setup_complete=False,
                    setup_mode="managed",
                    theme="light",
                    active_models=[],
                    managed_plan={},
                )
            )
        if db.get(models.ModelEndpoint, 1) is None:
            db.add(
                models.ModelEndpoint(
                    id=1,
                    provider="openai_compatible",
                    base_url=DEFAULT_BASE_URL,
                    api_key="",
                    models={
                        "orchestrator": "qwen3.5-9b-claude-opus-reasoning-distilled",
                        "summarizer": "granite4.0-h-micro-3b",
                        "utility": "qwen3.5-0.8b",
                    },
                )
            )
        db.commit()
