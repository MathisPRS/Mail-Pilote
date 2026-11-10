from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """Datetime stocké en UTC naïf dans SQLite, restitué timezone-aware (UTC)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime naïf refusé : utiliser un datetime timezone-aware")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
SessionLocal: sessionmaker[Session] = sessionmaker(autoflush=False, expire_on_commit=False)


# Attente maximale d'un verrou d'écriture SQLite (s) : la synchro et les actions écrivent par
# transactions courtes, une écriture concurrente patiente au lieu d'échouer.
LOCK_TIMEOUT = 30


def make_engine(url: str, timeout: float = LOCK_TIMEOUT) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": timeout})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def configure(url: str | None = None) -> Engine:
    """(Re)lie le moteur et SessionLocal. Sans url : DATA_DIR/mail-pilot.db."""
    global _engine
    if url is None:
        data_dir = get_settings().data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{data_dir / 'mail-pilot.db'}"
    dispose()
    _engine = make_engine(url)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    return _engine if _engine is not None else configure()


def dispose() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
        SessionLocal.configure(bind=None)


# colonnes ajoutées après coup : create_all ne modifie pas une table existante
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "mail_accounts": {
        "auth_type": "VARCHAR NOT NULL DEFAULT 'password'",
        "oauth_refresh_enc": "VARCHAR",
        "oauth_access_enc": "VARCHAR",
        "oauth_expires_at": "DATETIME",
    },
    "users": {"activity_seen_at": "DATETIME"},
    "messages": {"classified_at": "DATETIME"},
    "analysis_runs": {
        "step": "VARCHAR",
        "total": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _add_missing_columns(conn) -> None:
    for table, columns in ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    from app import models  # noqa: F401  (enregistre les tables)

    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _add_missing_columns(conn)
        # appli mono-utilisateur : un second compte est refusé par la base elle-même
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS users_single_row BEFORE INSERT ON users "
            "WHEN (SELECT COUNT(*) FROM users) > 0 "
            "BEGIN SELECT RAISE(ABORT, 'un seul compte'); END"
        )


def get_db() -> Iterator[Session]:
    get_engine()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
