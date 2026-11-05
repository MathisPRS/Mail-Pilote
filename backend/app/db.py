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


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

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


def init_db() -> None:
    from app import models  # noqa: F401  (enregistre les tables)

    Base.metadata.create_all(get_engine())


def get_db() -> Iterator[Session]:
    get_engine()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
