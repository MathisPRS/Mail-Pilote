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
