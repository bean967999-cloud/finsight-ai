from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings

settings = get_settings()

# pool_pre_ping checks a pooled connection before reuse so a restarted database
# does not leave the application holding an obviously stale connection.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_timeout=3 if settings.app_env == "deploy" else 30,
    connect_args={"connect_timeout": 3} if settings.app_env == "deploy" else {},
)

# Disabling expire_on_commit keeps committed values readable while response
# models are built, without forcing an unexpected query after every commit.
SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db_session() -> Generator[Session, None, None]:
    """Provide one database session for one FastAPI request."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transaction boundary for scripts and background jobs."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
