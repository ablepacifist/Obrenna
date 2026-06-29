import os
import sqlite3
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.services.migrations import run_migrations
from app import models

def test_managed_plan_migration(tmp_path):
    # 1. Setup a temp database
    db_file = tmp_path / "test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(db_url)
    
    # 2. Manually create the table WITHOUT the managed_plan column
    # We use a raw connection to simulate an old state
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE settings_app (
                id INTEGER PRIMARY KEY,
                setup_complete BOOLEAN,
                setup_mode TEXT,
                theme TEXT,
                active_models JSON
            )
        """))
        conn.commit()

    # 2.5 Ensure other tables exist (as init_db would call create_all)
    Base.metadata.create_all(engine)

    # 3. Verify column is missing
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA table_info(settings_app)")).fetchall()
        columns = [r[1] for r in res]
        assert "managed_plan" not in columns

    # 4. Run migrations
    Session = sessionmaker(bind=engine)
    with Session() as session:
        run_migrations(session)

    # 5. Verify column is NOW present
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA table_info(settings_app)")).fetchall()
        columns = [r[1] for r in res]
        assert "managed_plan" in columns
