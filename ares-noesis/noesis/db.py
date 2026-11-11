import random
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


def retry_locked(fn, attempts: int = 10):
    """SQLite reports 'database is locked' immediately when a deferred transaction cannot upgrade to a write lock (the busy timeout is
    not consulted, to avoid deadlock). The correct response is to retry the whole unit of work with jitter. No-op for other errors."""
    for i in range(attempts):
        try:
            return fn()
        except OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            time.sleep(random.random() * 0.02 * (2 ** min(i, 6)) + 0.005)
    return fn()


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kw: dict = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False, "timeout": 30}     # wait for locks instead of failing immediately
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kw["poolclass"] = StaticPool
    eng = create_engine(url, future=True, **kw)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(eng, "connect")
        def _no_implicit_begin(dbapi_con, _):      # SQLAlchemy's documented fix so SAVEPOINT works with pysqlite
            dbapi_con.isolation_level = None
            if ":memory:" not in url and url not in ("sqlite://", "sqlite:///"):
                cur = dbapi_con.cursor()
                cur.execute("PRAGMA busy_timeout=30000")
                try:
                    cur.execute("PRAGMA journal_mode=WAL")    # persistent; readers then do not block the writer
                except Exception:
                    pass                                      # another connection holds the DB; WAL is already/will be set by it
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()

        @event.listens_for(eng, "begin")
        def _begin(conn):
            if not conn.connection.dbapi_connection.in_transaction:   # shared in-memory connections may already be inside one
                conn.exec_driver_sql("BEGIN")
    return eng


def make_session_factory(engine):
    from . import models  # noqa: F401
    from .migrate import ensure_schema
    retry_locked(lambda: ensure_schema(engine, Base))
    return sessionmaker(engine, expire_on_commit=False)
