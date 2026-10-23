"""Engine construction shared by every service and the Alembic env."""

import os

from sqlalchemy import Engine, create_engine

_DEFAULT_DATABASE_URL = "postgresql://triage:triage@localhost:5432/triage"


def database_url_from_env() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)


def engine_from_env() -> Engine:
    return create_engine(database_url_from_env())
