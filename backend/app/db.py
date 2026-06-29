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

    with SessionLocal() as db:
        if db.get(models.AppSettings, 1) is None:
            db.add(
                models.AppSettings(
                    id=1,
                    setup_complete=False,
                    setup_mode="managed",
                    theme="light",
                    active_models=[],
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
                        "main_reasoner": "qwen2.5:14b",
                        "summarizer": "phi3.5",
                        "utility": "llama3.2:3b",
                    },
                )
            )
        db.commit()
