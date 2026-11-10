import sqlite3

from app import db as db_module


def test_init_db_adds_run_progress_columns_to_existing_base(settings):
    path = settings.data_dir / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE analysis_runs (id INTEGER PRIMARY KEY, kind VARCHAR NOT NULL, trigger VARCHAR NOT NULL, "
        "status VARCHAR NOT NULL, started_at DATETIME NOT NULL, finished_at DATETIME, mails_count INTEGER NOT NULL, error TEXT)"
    )
    con.execute("INSERT INTO analysis_runs VALUES (1,'full','manual','ok','2026-01-01 00:00:00',NULL,5,NULL)")
    con.commit()
    con.close()
    db_module.configure(f"sqlite:///{path}")
    try:
        db_module.init_db()
        db_module.init_db()  # idempotent
        from app.models import AnalysisRun

        with db_module.SessionLocal() as s:
            r = s.get(AnalysisRun, 1)
            assert r.step is None and r.total == 0 and r.mails_count == 5
    finally:
        db_module.dispose()


def test_init_db_adds_activity_columns_to_existing_base(settings):
    path = settings.data_dir / "old2.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(100) NOT NULL, password_hash VARCHAR NOT NULL, "
        "display_name VARCHAR NOT NULL, created_at DATETIME NOT NULL)"
    )
    con.execute("INSERT INTO users VALUES (1,'m','h','M','2026-01-01 00:00:00')")
    con.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, folder_id INTEGER NOT NULL, "
        "uid INTEGER NOT NULL, created_at DATETIME NOT NULL)"
    )
    con.commit()
    con.close()
    db_module.configure(f"sqlite:///{path}")
    try:
        db_module.init_db()
        db_module.init_db()  # idempotent
        from app.models import User

        with db_module.SessionLocal() as s:
            assert s.get(User, 1).activity_seen_at is None
        cols = {r[1] for r in db_module.get_engine().connect().exec_driver_sql("PRAGMA table_info(messages)")}
        assert "classified_at" in cols
    finally:
        db_module.dispose()
