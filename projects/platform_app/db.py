from __future__ import annotations

from contextlib import contextmanager

from flask import current_app
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


_engines: dict[str, object] = {}
_sessions: dict[str, scoped_session] = {}


def engine():
    url = current_app.config["DATABASE_URL"]
    if url not in _engines:
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engines[url] = create_engine(url, **kwargs)
        _sessions[url] = scoped_session(sessionmaker(bind=_engines[url], expire_on_commit=False))
        if url.startswith("sqlite"):
            @event.listens_for(_engines[url], "connect")
            def _set_sqlite_pragma(dbapi_conn, _record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
    return _engines[url]


def db_session():
    engine()
    return _sessions[current_app.config["DATABASE_URL"]]


@contextmanager
def transaction():
    session = db_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


def init_database(app):
    with app.app_context():
        from . import models  # noqa: F401
        from .schema_migrations import migrate_schema

        Base.metadata.create_all(engine())
        migrate_schema(engine())
        app.teardown_appcontext(lambda _exc: db_session().remove())


def ready() -> bool:
    try:
        db_session().execute(text("SELECT 1"))
        return True
    except Exception:
        return False
