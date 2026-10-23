"""Pytest configuration and fixtures for db tests."""

import uuid

import pytest
from db.models import Base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)
