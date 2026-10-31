import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

log = logging.getLogger("cx.db")


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)
_engine = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sqlite_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    eng = create_engine(url, **kwargs)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if ":memory:" not in url and url != "sqlite://":
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return eng


def mysql_connect_args(timeout: int = 10) -> dict:
    """PyMySQL connect arguments; managed MySQL-compatible services (e.g. TiDB Cloud) require verified TLS."""
    args: dict = {"connect_timeout": timeout}
    if get_settings().db_ssl_enabled:
        import ssl

        import certifi

        args["ssl"] = ssl.create_default_context(cafile=certifi.where())
    return args


def build_engine(url: str | None = None):
    s = get_settings()
    url = url or s.resolved_database_url
    if url.startswith("sqlite"):
        if ":memory:" not in url and url != "sqlite://":
            os.makedirs(os.path.dirname(os.path.abspath(url.replace("sqlite:///", "", 1))), exist_ok=True)
        return _sqlite_engine(url)
    attempts = 1 if s.db_fallback_sqlite else 30  # containers: wait for MySQL to accept connections instead of failing at once
    for attempt in range(1, attempts + 1):
        try:
            eng = create_engine(url, pool_pre_ping=True, pool_recycle=1800, connect_args=mysql_connect_args(10))
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            log.info("Connected to database %s", eng.url.render_as_string(hide_password=True))
            return eng
        except Exception as exc:  # noqa: BLE001
            if s.db_fallback_sqlite:
                log.warning("Database unreachable (%s). Falling back to SQLite at %s", exc.__class__.__name__, s.sqlite_path)
                os.makedirs(os.path.dirname(s.sqlite_path), exist_ok=True)
                return _sqlite_engine(f"sqlite:///{s.sqlite_path}")
            if attempt == attempts:
                raise
            log.warning("Database not ready (attempt %d/%d): %s", attempt, attempts, exc.__class__.__name__)
            time.sleep(2)
    raise RuntimeError("unreachable")


def init_engine(url: str | None = None):
    global _engine
    _engine = build_engine(url)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine():
    return _engine if _engine is not None else init_engine()


def get_db():
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """Transactional scope: commit on success, rollback on error."""
    get_engine()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
