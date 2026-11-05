"""Verrou d'écriture SQLite : une écriture en attente ne doit ni déconnecter l'utilisateur ni perdre une action."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import db as db_module
from app.auth import service
from app.models import KV, Session, utcnow


def short_engine(settings):
    """Moteur au délai d'attente court : reproduit « database is locked » sans attendre 30 s."""
    return db_module.make_engine(f"sqlite:///{settings.data_dir / 'test.db'}", timeout=0.2)


def hold_write_lock(settings) -> DbSession:
    """Session gardant une écriture flushée (verrou d'écriture SQLite tenu jusqu'au rollback)."""
    blocker = DbSession(db_module.make_engine(f"sqlite:///{settings.data_dir / 'test.db'}"))
    blocker.add(KV(key="blocker", value_json="1"))
    blocker.flush()
    return blocker


def test_engine_waits_30s_for_lock(monkeypatch):
    seen = {}
    real = db_module.create_engine

    def spy(url, **kw):
        seen.update(kw)
        return real(url, **kw)

    monkeypatch.setattr(db_module, "create_engine", spy)
    db_module.make_engine("sqlite://")
    assert seen["connect_args"] == {"check_same_thread": False, "timeout": 30}


def test_session_refresh_is_best_effort_under_write_lock(db, settings):
    user = service.create_user(db, "mathis", "correct horse battery", "M")
    token = service.create_session(db, user, None)
    row = db.scalar(select(Session))
    row.last_seen_at = utcnow() - timedelta(minutes=5)
    db.commit()

    blocker = hold_write_lock(settings)
    try:
        with DbSession(short_engine(settings)) as s:
            resolved = service.resolve_session(s, token)
            assert resolved is not None and resolved[0].username == "mathis"
            assert not s.in_transaction() or not s.dirty
    finally:
        blocker.rollback()
        blocker.close()
