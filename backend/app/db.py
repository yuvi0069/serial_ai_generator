"""SQLAlchemy engine + session helpers. Works with Supabase Postgres (psycopg3) and SQLite (tests)."""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


def normalize_db_url(url: str) -> str:
    """Force the psycopg3 driver for any postgres URL (Supabase gives plain postgresql://)."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def raw_pg_url(url: str) -> str:
    """Plain libpq URL for psycopg / the LangGraph checkpointer."""
    return normalize_db_url(url).replace("postgresql+psycopg://", "postgresql://", 1)


IS_SQLITE = settings.database_url.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    # prepare_threshold=None disables server-side prepared statements -> safe behind Supabase poolers.
    engine = create_engine(
        normalize_db_url(settings.database_url),
        pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
        connect_args={"prepare_threshold": None},
    )

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for graph nodes / background jobs: commit on success, rollback on error."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
