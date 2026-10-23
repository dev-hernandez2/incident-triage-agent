"""Session-scope helper shared by services that do commit-on-success,
rollback-on-exception, always-close around a unit of work."""

from collections.abc import Callable, Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def session_scope(session_factory: Callable[[], Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
