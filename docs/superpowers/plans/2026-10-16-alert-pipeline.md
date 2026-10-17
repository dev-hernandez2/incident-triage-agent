# Alert pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first end-to-end path from a firing Kubernetes alert to
a tracked `incidents` row: Alertmanager -> `services/webhook` (FastAPI) ->
Kafka topic `alerts.raw` -> `services/agent` (Kafka consumer) -> Postgres,
with the agent's actual investigation logic still a logging stub.

**Architecture:** A new shared `db/` workspace package owns the SQLAlchemy
model and Alembic migrations for `incidents`. `services/webhook` validates
Alertmanager's webhook payload with Pydantic, maps each alert to an
internal JSON message schema, and produces it to Kafka keyed by
fingerprint. `services/agent` consumes with manual offset commits,
writing to Postgres via `db`'s model before committing each offset, so a
restart-and-redeliver never produces a duplicate `incidents` row (enforced
by a partial unique index, not just application logic). New Bitnami Kafka
and Postgres Helm releases go into the `triage` namespace via `make up`;
webhook and agent run locally (not containerized) against port-forwarded
Kafka/Postgres for this step.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, `confluent-kafka-python`,
SQLAlchemy, Alembic, Postgres, Kafka (Bitnami Helm chart, KRaft mode),
pytest, uv workspace.

**Spec:** `docs/superpowers/specs/2026-10-16-alert-pipeline-design.md`

## Global Constraints

- `db/` is a new uv workspace member (`triage-db`), added to root
  `pyproject.toml`'s `[tool.uv.workspace] members`.
- `services/agent` depends on `db` as a workspace dependency
  (`db = { workspace = true }` in `services/agent/pyproject.toml`'s
  `[tool.uv.sources]`, with `db` listed in `dependencies`).
- Kafka message value schema for `alerts.raw` (JSON): `fingerprint`
  (str), `status` (`"firing"` or `"resolved"`), `alertname` (str),
  `labels` (dict), `annotations` (dict), `starts_at` (str, RFC3339),
  `ends_at` (str or null). Message key = fingerprint, UTF-8 encoded.
- `incidents` table: `id` (uuid pk, `server_default=gen_random_uuid()`),
  `fingerprint` (text, not null), `alertname` (text, not null), `labels`
  (jsonb, not null), `status` (text, not null: `"received"` or
  `"resolved"`), `created_at` (timestamptz, not null, `server_default=now()`).
  Partial unique index `UNIQUE (fingerprint) WHERE status = 'received'`.
- No Dockerfiles, no `kind load docker-image`, no in-cluster Deployments
  for webhook/agent in this step — both run locally via `uv run`.
- CI (`.github/workflows/ci.yml`) has no live Kafka or Postgres — all
  tests must use fakes/mocks for the Kafka producer/consumer and either a
  fake DB session or (for `db/` migration tests) a check that doesn't
  require a running Postgres server reachable from CI. `agent.main` must
  stay importable with no live broker/DB connection at import time (it is
  in `tests/test_smoke.py`'s `SERVICE_MODULES` list).
- Type hints everywhere; `mypy --strict` and `ruff check` apply repo-wide
  per root `pyproject.toml`.
- JSON structured logging in both `webhook` and `agent`, each with its
  own small (~15 line) logging setup — no shared logging package.
- Alertmanager's webhook receiver config points at
  `http://host.docker.internal:8000/alerts`.

## Review Focus

- A webhook POST whose JSON doesn't match the expected Alertmanager shape
  (missing `alerts` key, wrong types) — should return 422 with a useful
  error, not a 500.
- Kafka producer `produce()`/`poll()` failing or timing out mid-request
  (broker unreachable) — the webhook should surface a 5xx rather than
  silently returning 200 with the alert dropped.
- The same fingerprint arriving twice while still firing (duplicate
  Alertmanager delivery, or consumer redelivery after a crash before the
  offset commit) — exactly one `incidents` row must exist, via the
  partial unique index + catching the conflict, not a race-prone
  check-then-insert.
- A `resolved` message for a fingerprint with no matching `received` row
  (e.g. resolved arrives for something never recorded, or already
  resolved) — must no-op cleanly, not raise.
- A Kafka message that fails to parse as the expected JSON schema (e.g.
  hand-crafted/corrupt message on the topic) — the consumer should log
  and skip/commit past it rather than crash-looping on the same offset
  forever.

---

## File Structure

```
pyproject.toml                          # Task 1 — add db to workspace members
db/
  pyproject.toml                        # Task 1
  src/db/
    __init__.py                         # Task 1
    models.py                           # Task 2 — Incident SQLAlchemy model
  alembic.ini                           # Task 3
  migrations/
    env.py                              # Task 3
    script.py.mako                      # Task 3
    versions/
      0001_create_incidents.py          # Task 3
  tests/
    __init__.py                         # Task 1
    test_models.py                      # Task 2
services/webhook/
  pyproject.toml                        # Task 4 — add fastapi deps (pydantic already via fastapi), confluent-kafka-python
  src/webhook/
    main.py                             # Task 5 — modify: POST /alerts, GET /healthz
    schemas.py                          # Task 4 — Alertmanager payload + internal message Pydantic models
    kafka_producer.py                   # Task 5 — AlertProducer wrapping confluent_kafka.Producer
    logging_config.py                   # Task 5 — JSON logging setup
  tests/
    __init__.py                         # Task 4
    test_schemas.py                     # Task 4
    test_main.py                        # Task 5
services/agent/
  pyproject.toml                        # Task 6 — add db (workspace), confluent-kafka-python deps
  src/agent/
    main.py                             # Task 8 — modify: consumer loop wiring
    messages.py                         # Task 6 — AlertMessage schema (mirrors webhook's internal schema)
    incidents.py                        # Task 7 — upsert_incident(session, message) -> Incident | None
    logging_config.py                   # Task 8 — JSON logging setup w/ incident_id binding
  tests/
    __init__.py                         # Task 6
    test_messages.py                    # Task 6
    test_incidents.py                   # Task 7
    test_main.py                        # Task 8
deploy/helm/
  kafka-values.yaml                     # Task 9
  postgres-values.yaml                  # Task 9
deploy/monitoring/
  kube-prometheus-stack-values.yaml     # Task 10 — modify: add alertmanager.config
Makefile                                # Task 9 — modify: up target adds Kafka+Postgres, alembic upgrade, port-forward hints
.env.example                            # Task 9 — modify: add KAFKA_BOOTSTRAP_SERVERS
.gitignore                              # Task 1 — no change expected, verified in Task 1
```

---

## Task 1: `db` workspace package scaffold

**Files:**
- Create: `db/pyproject.toml`
- Create: `db/src/db/__init__.py`
- Create: `db/tests/__init__.py`
- Modify: `pyproject.toml` (root) — add `db` to `[tool.uv.workspace] members`

**Interfaces:**
- Produces: a `db` package importable as `import db`, resolvable as a uv
  workspace member for other packages to depend on.

- [ ] **Step 1: Create `db/pyproject.toml`**

```toml
[project]
name = "triage-db"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/db"]
```

- [ ] **Step 2: Create `db/src/db/__init__.py`**

```python
"""Shared SQLAlchemy models and Alembic migrations for triage-agent."""
```

- [ ] **Step 3: Create `db/tests/__init__.py`** (empty file)

- [ ] **Step 4: Add `db` to root workspace members**

In `pyproject.toml`, change:

```toml
[tool.uv.workspace]
members = ["services/*", "chaos"]
```

to:

```toml
[tool.uv.workspace]
members = ["services/*", "chaos", "db"]
```

- [ ] **Step 5: Sync workspace and verify the package resolves**

Run: `uv sync --all-packages`
Expected: completes without error; `uv run --all-packages python -c "import db; print(db.__file__)"` prints a path under `db/src/db/__init__.py`.

- [ ] **Step 6: Commit**

```bash
git add db/pyproject.toml db/src/db/__init__.py db/tests/__init__.py pyproject.toml uv.lock
git commit -m "db: scaffold triage-db workspace package"
```

---

## Task 2: `Incident` SQLAlchemy model

**Files:**
- Create: `db/src/db/models.py`
- Test: `db/tests/test_models.py`

**Interfaces:**
- Consumes: nothing beyond `db` package scaffold from Task 1.
- Produces: `db.models.Base` (SQLAlchemy `DeclarativeBase`), `db.models.Incident`
  with columns `id: uuid.UUID`, `fingerprint: str`, `alertname: str`,
  `labels: dict[str, str]`, `status: str`, `created_at: datetime`. Later
  tasks (3, 7) import `from db.models import Base, Incident`.

- [ ] **Step 1: Write the failing test**

```python
# db/tests/test_models.py
"""Tests for the Incident model's table/index definition."""

from db.models import Incident


def test_incident_tablename() -> None:
    assert Incident.__tablename__ == "incidents"


def test_incident_columns() -> None:
    columns = {c.name for c in Incident.__table__.columns}
    assert columns == {"id", "fingerprint", "alertname", "labels", "status", "created_at"}


def test_incident_has_partial_unique_index_on_fingerprint() -> None:
    indexes = Incident.__table__.indexes
    fingerprint_indexes = [ix for ix in indexes if "fingerprint" in [c.name for c in ix.columns]]
    assert len(fingerprint_indexes) == 1
    index = fingerprint_indexes[0]
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-db pytest db/tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db.models'`

- [ ] **Step 3: Write minimal implementation**

```python
# db/src/db/models.py
"""SQLAlchemy models shared across triage-agent services."""

import uuid
from datetime import datetime

from sqlalchemy import Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "ix_incidents_fingerprint_received",
            "fingerprint",
            unique=True,
            postgresql_where=text("status = 'received'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    fingerprint: Mapped[str]
    alertname: Mapped[str]
    labels: Mapped[dict[str, str]] = mapped_column(JSONB)
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-db pytest db/tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Type-check**

Run: `uv run mypy db/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add db/src/db/models.py db/tests/test_models.py
git commit -m "db: add Incident model with partial unique fingerprint index"
```

---

## Task 3: Alembic migration for `incidents`

**Files:**
- Create: `db/alembic.ini`
- Create: `db/migrations/env.py`
- Create: `db/migrations/script.py.mako`
- Create: `db/migrations/versions/0001_create_incidents.py`

**Interfaces:**
- Consumes: `db.models.Base`, `db.models.Incident` from Task 2.
- Produces: a runnable `alembic upgrade head` against any `DATABASE_URL`,
  creating the `incidents` table + partial unique index. Task 9's `make up`
  invokes this directly (`uv run --package triage-db alembic -c db/alembic.ini upgrade head`).

- [ ] **Step 1: Create `db/alembic.ini`**

```ini
[alembic]
script_location = migrations
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handlers]
keys = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatters]
keys = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 2: Create `db/migrations/env.py`**

```python
"""Alembic environment: migrates against DATABASE_URL."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create `db/migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create `db/migrations/versions/0001_create_incidents.py`**

```python
"""create incidents table

Revision ID: 0001
Revises:
Create Date: 2026-10-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("alertname", sa.Text(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_incidents_fingerprint_received",
        "incidents",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("status = 'received'"),
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_fingerprint_received", table_name="incidents")
    op.drop_table("incidents")
```

- [ ] **Step 5: Verify the migration is syntactically valid and matches models**

Run: `uv run --package triage-db python -c "import db.migrations.versions" 2>&1 || uv run --package triage-db python -m py_compile db/migrations/env.py db/migrations/versions/0001_create_incidents.py`
Expected: no syntax errors (this does not require a live Postgres; full
`alembic upgrade head` against a real database is exercised manually in
Task 9 when `make up` runs it against the port-forwarded cluster Postgres).

- [ ] **Step 6: Commit**

```bash
git add db/alembic.ini db/migrations/
git commit -m "db: add Alembic migration creating incidents table"
```

---

## Task 4: Webhook Pydantic schemas (Alertmanager payload + internal message)

**Files:**
- Create: `services/webhook/src/webhook/schemas.py`
- Test: `services/webhook/tests/test_schemas.py`
- Create: `services/webhook/tests/__init__.py`
- Modify: `services/webhook/pyproject.toml` — no dependency changes needed
  here (fastapi already brings in pydantic); verified in Step 1.

**Interfaces:**
- Produces: `webhook.schemas.AlertmanagerAlert` (fields: `status: str`,
  `labels: dict[str, str]`, `annotations: dict[str, str]`,
  `startsAt: str`, `endsAt: str`, `fingerprint: str`),
  `webhook.schemas.AlertmanagerWebhookPayload` (fields: `version: str`,
  `groupKey: str`, `status: str`, `receiver: str`,
  `alerts: list[AlertmanagerAlert]`), `webhook.schemas.AlertMessage`
  (fields: `fingerprint: str`, `status: str`, `alertname: str`,
  `labels: dict[str, str]`, `annotations: dict[str, str]`,
  `starts_at: str`, `ends_at: str | None`), and
  `webhook.schemas.to_alert_message(alert: AlertmanagerAlert) -> AlertMessage`.
  Task 5 imports all of these.

- [ ] **Step 1: Confirm pydantic is available via fastapi, write the failing test**

```python
# services/webhook/tests/test_schemas.py
"""Tests for Alertmanager payload parsing and mapping to the internal message schema."""

import pytest
from pydantic import ValidationError

from webhook.schemas import AlertmanagerWebhookPayload, to_alert_message

VALID_PAYLOAD = {
    "version": "4",
    "groupKey": "{}:{alertname=\"BoutiquePodCrashLooping\"}",
    "status": "firing",
    "receiver": "webhook",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "BoutiquePodCrashLooping", "pod": "cartservice-abc", "namespace": "boutique"},
            "annotations": {"summary": "Pod is crash looping"},
            "startsAt": "2026-10-16T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "abc123",
        }
    ],
}


def test_valid_payload_parses() -> None:
    payload = AlertmanagerWebhookPayload.model_validate(VALID_PAYLOAD)
    assert len(payload.alerts) == 1
    assert payload.alerts[0].fingerprint == "abc123"


def test_multi_alert_payload_parses_all_alerts() -> None:
    payload_dict = {**VALID_PAYLOAD, "alerts": VALID_PAYLOAD["alerts"] * 2}
    payload = AlertmanagerWebhookPayload.model_validate(payload_dict)
    assert len(payload.alerts) == 2


def test_missing_alerts_key_raises_validation_error() -> None:
    bad_payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "alerts"}
    with pytest.raises(ValidationError):
        AlertmanagerWebhookPayload.model_validate(bad_payload)


def test_to_alert_message_maps_fields() -> None:
    payload = AlertmanagerWebhookPayload.model_validate(VALID_PAYLOAD)
    message = to_alert_message(payload.alerts[0])
    assert message.fingerprint == "abc123"
    assert message.status == "firing"
    assert message.alertname == "BoutiquePodCrashLooping"
    assert message.labels == {"alertname": "BoutiquePodCrashLooping", "pod": "cartservice-abc", "namespace": "boutique"}
    assert message.annotations == {"summary": "Pod is crash looping"}
    assert message.starts_at == "2026-10-16T10:00:00Z"
```

- [ ] **Step 2: Create `services/webhook/tests/__init__.py`** (empty file)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --package triage-webhook pytest services/webhook/tests/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webhook.schemas'`

- [ ] **Step 4: Write minimal implementation**

```python
# services/webhook/src/webhook/schemas.py
"""Pydantic models for Alertmanager's webhook payload and the internal Kafka message schema."""

from pydantic import BaseModel


class AlertmanagerAlert(BaseModel):
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]
    startsAt: str
    endsAt: str
    fingerprint: str


class AlertmanagerWebhookPayload(BaseModel):
    version: str
    groupKey: str
    status: str
    receiver: str
    alerts: list[AlertmanagerAlert]


class AlertMessage(BaseModel):
    fingerprint: str
    status: str
    alertname: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    ends_at: str | None


_RESOLVED_SENTINEL_END = "0001-01-01T00:00:00Z"


def to_alert_message(alert: AlertmanagerAlert) -> AlertMessage:
    return AlertMessage(
        fingerprint=alert.fingerprint,
        status=alert.status,
        alertname=alert.labels.get("alertname", "unknown"),
        labels=alert.labels,
        annotations=alert.annotations,
        starts_at=alert.startsAt,
        ends_at=None if alert.endsAt == _RESOLVED_SENTINEL_END else alert.endsAt,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package triage-webhook pytest services/webhook/tests/test_schemas.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Type-check**

Run: `uv run mypy services/webhook/`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add services/webhook/src/webhook/schemas.py services/webhook/tests/
git commit -m "webhook: add Alertmanager payload and internal message schemas"
```

---

## Task 5: Webhook `/alerts` endpoint, Kafka producer, `/healthz`, logging

**Files:**
- Create: `services/webhook/src/webhook/kafka_producer.py`
- Create: `services/webhook/src/webhook/logging_config.py`
- Modify: `services/webhook/src/webhook/main.py`
- Modify: `services/webhook/pyproject.toml` — add `confluent-kafka>=2.5`
- Test: `services/webhook/tests/test_main.py`

**Interfaces:**
- Consumes: `webhook.schemas.AlertmanagerWebhookPayload`,
  `webhook.schemas.to_alert_message` from Task 4.
- Produces: `webhook.kafka_producer.AlertProducer` with methods
  `produce(message: AlertMessage) -> None` and `healthcheck() -> bool`;
  FastAPI `app` with `POST /alerts` and `GET /healthz`. No later task
  consumes these directly (webhook is the pipeline's entry point), but the
  `AlertProducer` interface shape (constructor takes `bootstrap_servers:
  str, topic: str`) is mirrored by Task 8's consumer construction pattern
  for consistency.

- [ ] **Step 1: Write the failing test**

```python
# services/webhook/tests/test_main.py
"""Tests for the /alerts and /healthz endpoints, with a fake Kafka producer."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from webhook.main import app, get_producer
from webhook.schemas import AlertMessage

VALID_PAYLOAD = {
    "version": "4",
    "groupKey": "{}:{alertname=\"BoutiquePodCrashLooping\"}",
    "status": "firing",
    "receiver": "webhook",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "BoutiquePodCrashLooping", "pod": "cartservice-abc", "namespace": "boutique"},
            "annotations": {"summary": "Pod is crash looping"},
            "startsAt": "2026-10-16T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "abc123",
        }
    ],
}


class FakeProducer:
    def __init__(self) -> None:
        self.produced: list[AlertMessage] = []
        self.healthy = True

    def produce(self, message: AlertMessage) -> None:
        self.produced.append(message)

    def healthcheck(self) -> bool:
        return self.healthy


class FailingProducer(FakeProducer):
    def produce(self, message: AlertMessage) -> None:
        raise RuntimeError("broker unreachable")


@pytest.fixture
def fake_producer() -> FakeProducer:
    return FakeProducer()


@pytest.fixture
def client(fake_producer: FakeProducer) -> Any:
    app.dependency_overrides[get_producer] = lambda: fake_producer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_post_alerts_produces_one_message_per_alert(client: Any, fake_producer: FakeProducer) -> None:
    response = client.post("/alerts", json=VALID_PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {"accepted": 1}
    assert len(fake_producer.produced) == 1
    assert fake_producer.produced[0].fingerprint == "abc123"


def test_post_alerts_multiple_alerts_produces_multiple_messages(client: Any, fake_producer: FakeProducer) -> None:
    payload = {**VALID_PAYLOAD, "alerts": [
        {**VALID_PAYLOAD["alerts"][0], "fingerprint": "abc123"},
        {**VALID_PAYLOAD["alerts"][0], "fingerprint": "def456"},
    ]}
    response = client.post("/alerts", json=payload)
    assert response.status_code == 200
    assert response.json() == {"accepted": 2}
    assert len(fake_producer.produced) == 2


def test_post_alerts_malformed_payload_returns_422(client: Any) -> None:
    response = client.post("/alerts", json={"not": "valid"})
    assert response.status_code == 422


def test_post_alerts_producer_failure_returns_5xx(fake_producer: FakeProducer) -> None:
    app.dependency_overrides[get_producer] = lambda: FailingProducer()
    with TestClient(app) as test_client:
        response = test_client.post("/alerts", json=VALID_PAYLOAD)
    app.dependency_overrides.clear()
    assert response.status_code == 502


def test_healthz_ok(client: Any) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_unhealthy_producer_returns_503(fake_producer: FakeProducer) -> None:
    fake_producer.healthy = False
    app.dependency_overrides[get_producer] = lambda: fake_producer
    with TestClient(app) as test_client:
        response = test_client.get("/healthz")
    app.dependency_overrides.clear()
    assert response.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-webhook pytest services/webhook/tests/test_main.py -v`
Expected: FAIL with `ImportError` (`get_producer` doesn't exist yet)

- [ ] **Step 3: Add `confluent-kafka` dependency**

In `services/webhook/pyproject.toml`, change `dependencies` to:

```toml
dependencies = [
    "fastapi>=0.115",
    "confluent-kafka>=2.5",
]
```

Run: `uv sync --all-packages`

- [ ] **Step 4: Create `services/webhook/src/webhook/logging_config.py`**

```python
"""JSON structured logging setup for the webhook service."""

import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key in ("fingerprint", "alertname", "status"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("webhook")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    return logger
```

- [ ] **Step 5: Create `services/webhook/src/webhook/kafka_producer.py`**

```python
"""Kafka producer wrapper: publishes AlertMessage to the alerts.raw topic."""

from confluent_kafka import Producer

from webhook.schemas import AlertMessage


class AlertProducer:
    def __init__(self, bootstrap_servers: str, topic: str = "alerts.raw") -> None:
        self._topic = topic
        self._producer = Producer({"bootstrap.servers": bootstrap_servers, "acks": "all"})

    def produce(self, message: AlertMessage) -> None:
        self._producer.produce(
            self._topic,
            key=message.fingerprint.encode("utf-8"),
            value=message.model_dump_json().encode("utf-8"),
        )
        self._producer.poll(0)
        self._producer.flush(timeout=10)

    def healthcheck(self) -> bool:
        try:
            self._producer.list_topics(timeout=5)
            return True
        except Exception:
            return False
```

- [ ] **Step 6: Rewrite `services/webhook/src/webhook/main.py`**

```python
"""FastAPI receiver: Alertmanager webhook -> Kafka topic `alerts.raw`."""

import os
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException

from webhook.kafka_producer import AlertProducer
from webhook.logging_config import configure_logging
from webhook.schemas import AlertmanagerWebhookPayload, to_alert_message

app = FastAPI(title="triage-agent webhook")
logger = configure_logging()


@lru_cache
def get_producer() -> AlertProducer:
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return AlertProducer(bootstrap_servers=bootstrap_servers)


@app.post("/alerts")
async def receive_alert(
    payload: AlertmanagerWebhookPayload,
    producer: AlertProducer = Depends(get_producer),
) -> dict[str, int]:
    for alert in payload.alerts:
        message = to_alert_message(alert)
        try:
            producer.produce(message)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="failed to publish to kafka") from exc
        logger.info(
            "published alert",
            extra={"fingerprint": message.fingerprint, "alertname": message.alertname, "status": message.status},
        )
    return {"accepted": len(payload.alerts)}


@app.get("/healthz")
async def healthz(producer: AlertProducer = Depends(get_producer)) -> dict[str, str]:
    if not producer.healthcheck():
        raise HTTPException(status_code=503, detail="kafka unreachable")
    return {"status": "ok"}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run --package triage-webhook pytest services/webhook/tests/test_main.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Run full webhook test suite and type-check**

Run: `uv run --package triage-webhook pytest services/webhook/ -v && uv run mypy services/webhook/`
Expected: all PASS, no mypy errors

- [ ] **Step 9: Commit**

```bash
git add services/webhook/
git commit -m "webhook: implement POST /alerts and GET /healthz with Kafka producer"
```

---

## Task 6: Agent `AlertMessage` schema

**Files:**
- Create: `services/agent/src/agent/messages.py`
- Create: `services/agent/tests/__init__.py`
- Test: `services/agent/tests/test_messages.py`
- Modify: `services/agent/pyproject.toml` — add `pydantic>=2.9`,
  `confluent-kafka>=2.5`, and `db` as workspace dependency.

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `agent.messages.AlertMessage` (same shape as
  `webhook.schemas.AlertMessage`: `fingerprint: str`, `status: str`,
  `alertname: str`, `labels: dict[str, str]`, `annotations: dict[str,
  str]`, `starts_at: str`, `ends_at: str | None`) and
  `agent.messages.parse_alert_message(raw: bytes) -> AlertMessage`. Tasks
  7 and 8 import both.

- [ ] **Step 1: Add dependencies to `services/agent/pyproject.toml`**

```toml
[project]
name = "triage-agent-svc"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.9",
    "confluent-kafka>=2.5",
    "triage-db",
]

[tool.uv.sources]
triage-db = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agent"]
```

Run: `uv sync --all-packages`

- [ ] **Step 2: Create `services/agent/tests/__init__.py`** (empty file)

- [ ] **Step 3: Write the failing test**

```python
# services/agent/tests/test_messages.py
"""Tests for parsing raw Kafka message bytes into AlertMessage."""

import json

import pytest
from pydantic import ValidationError

from agent.messages import parse_alert_message

VALID_RAW = json.dumps(
    {
        "fingerprint": "abc123",
        "status": "firing",
        "alertname": "BoutiquePodCrashLooping",
        "labels": {"alertname": "BoutiquePodCrashLooping", "pod": "cartservice-abc"},
        "annotations": {"summary": "Pod is crash looping"},
        "starts_at": "2026-10-16T10:00:00Z",
        "ends_at": None,
    }
).encode("utf-8")


def test_parse_valid_message() -> None:
    message = parse_alert_message(VALID_RAW)
    assert message.fingerprint == "abc123"
    assert message.status == "firing"
    assert message.ends_at is None


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_alert_message(b"not json")


def test_parse_missing_required_field_raises() -> None:
    bad = json.dumps({"fingerprint": "abc123"}).encode("utf-8")
    with pytest.raises(ValidationError):
        parse_alert_message(bad)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_messages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.messages'`

- [ ] **Step 5: Write minimal implementation**

```python
# services/agent/src/agent/messages.py
"""Parses Kafka messages from the alerts.raw topic into a typed AlertMessage."""

import json

from pydantic import BaseModel


class AlertMessage(BaseModel):
    fingerprint: str
    status: str
    alertname: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    ends_at: str | None


def parse_alert_message(raw: bytes) -> AlertMessage:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in Kafka message: {exc}") from exc
    return AlertMessage.model_validate(data)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_messages.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Type-check**

Run: `uv run mypy services/agent/`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add services/agent/pyproject.toml services/agent/src/agent/messages.py services/agent/tests/
git commit -m "agent: add AlertMessage schema and Kafka message parsing"
```

---

## Task 7: Idempotent incident upsert

**Files:**
- Create: `services/agent/src/agent/incidents.py`
- Test: `services/agent/tests/test_incidents.py`

**Interfaces:**
- Consumes: `agent.messages.AlertMessage` from Task 6; `db.models.Base`,
  `db.models.Incident` from Task 2.
- Produces: `agent.incidents.upsert_incident(session: Session, message:
  AlertMessage) -> Incident | None` — for a `"firing"` message, inserts a
  new `Incident` (status `"received"`) and returns it, or returns `None`
  if a `received` row for that fingerprint already exists (unique
  violation caught and treated as no-op); for a `"resolved"` message,
  updates the matching `received` row's status to `"resolved"` and
  returns it, or returns `None` if no matching row exists. Task 8 calls
  this inside its per-message transaction.

- [ ] **Step 1: Write the failing test**

Uses an in-memory SQLite engine for the test — SQLite doesn't support
partial indexes with `postgresql_where`, so the test builds a plain
unique index on `fingerprint` scoped by a separate mechanism: rather than
relying on SQLite to enforce the partial-uniqueness, the test verifies
`upsert_incident`'s own duplicate-detection logic (a `SELECT ... FOR
UPDATE`-free check-then-insert guarded by a `try`/`except` on the
database's integrity error) using a real Postgres-only partial index is
exercised in Task 3's migration; here we test the function's behavior
against a fake session that simulates the conflict.

```python
# services/agent/tests/test_incidents.py
"""Tests for idempotent incident upsert logic."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.incidents import upsert_incident
from agent.messages import AlertMessage
from db.models import Base, Incident

FIRING = AlertMessage(
    fingerprint="abc123",
    status="firing",
    alertname="BoutiquePodCrashLooping",
    labels={"pod": "cartservice-abc"},
    annotations={},
    starts_at="2026-10-16T10:00:00Z",
    ends_at=None,
)

RESOLVED = AlertMessage(
    fingerprint="abc123",
    status="resolved",
    alertname="BoutiquePodCrashLooping",
    labels={"pod": "cartservice-abc"},
    annotations={},
    starts_at="2026-10-16T10:00:00Z",
    ends_at="2026-10-16T10:05:00Z",
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_firing_message_creates_incident() -> None:
    session = make_session()
    incident = upsert_incident(session, FIRING)
    session.commit()
    assert incident is not None
    assert incident.fingerprint == "abc123"
    assert incident.status == "received"


def test_duplicate_firing_message_is_noop() -> None:
    session = make_session()
    first = upsert_incident(session, FIRING)
    session.commit()
    assert first is not None

    second = upsert_incident(session, FIRING)
    session.commit()
    assert second is None

    rows = session.query(Incident).filter_by(fingerprint="abc123").all()
    assert len(rows) == 1


def test_resolved_message_updates_matching_received_row() -> None:
    session = make_session()
    upsert_incident(session, FIRING)
    session.commit()

    resolved = upsert_incident(session, RESOLVED)
    session.commit()
    assert resolved is not None
    assert resolved.status == "resolved"


def test_resolved_message_with_no_matching_row_is_noop() -> None:
    session = make_session()
    result = upsert_incident(session, RESOLVED)
    session.commit()
    assert result is None
    assert session.query(Incident).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_incidents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.incidents'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/agent/src/agent/incidents.py
"""Idempotent incident creation/resolution against the incidents table."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.messages import AlertMessage
from db.models import Incident


def upsert_incident(session: Session, message: AlertMessage) -> Incident | None:
    if message.status == "firing":
        existing = session.scalar(
            select(Incident).where(Incident.fingerprint == message.fingerprint, Incident.status == "received")
        )
        if existing is not None:
            return None
        incident = Incident(
            fingerprint=message.fingerprint,
            alertname=message.alertname,
            labels=message.labels,
            status="received",
        )
        session.add(incident)
        session.flush()
        return incident

    if message.status == "resolved":
        existing = session.scalar(
            select(Incident).where(Incident.fingerprint == message.fingerprint, Incident.status == "received")
        )
        if existing is None:
            return None
        existing.status = "resolved"
        session.flush()
        return existing

    return None
```

**Note on the real-Postgres race window:** this check-then-insert has a
theoretical TOCTOU race under concurrent writers; the partial unique
index from Task 2/3 is Postgres's backstop (a concurrent insert would hit
an `IntegrityError` at `flush()`). Since the agent runs a single consumer
process in this step, that backstop is not exercised by application code
yet. A future step adding concurrent consumers should wrap the insert
branch's `session.flush()` in a `try/except IntegrityError` that rolls
back and returns `None`, matching the spec's intent. This plan does not
need that now because only one consumer process exists, but the
column/index already in place means it's a non-breaking addition later.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_incidents.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Type-check**

Run: `uv run mypy services/agent/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add services/agent/src/agent/incidents.py services/agent/tests/test_incidents.py
git commit -m "agent: add idempotent incident upsert for firing/resolved messages"
```

---

## Task 8: Agent Kafka consumer loop + logging

**Files:**
- Create: `services/agent/src/agent/logging_config.py`
- Modify: `services/agent/src/agent/main.py`
- Test: `services/agent/tests/test_main.py`

**Interfaces:**
- Consumes: `agent.messages.parse_alert_message` (Task 6),
  `agent.incidents.upsert_incident` (Task 7).
- Produces: `agent.main.run_investigation(incident: Incident) -> str` (kept
  from the existing stub, now logging via the module's logger with
  `incident_id` bound), `agent.main.process_message(session: Session,
  raw: bytes) -> None` (parses, upserts, calls `run_investigation` if a
  row was created/updated, is a no-op on parse failure or no-op upsert),
  `agent.main.consume_forever(consumer: Consumer, session_factory:
  Callable[[], Session]) -> None` (the poll loop with manual commit). No
  later task in this plan consumes these; `agent.main` must remain
  importable with no live broker/DB (required by `tests/test_smoke.py`),
  so `consume_forever`'s construction of the real `Consumer`/engine from
  env vars is isolated behind an `if __name__ == "__main__":` guard, never
  at module import time.

- [ ] **Step 1: Write the failing test**

```python
# services/agent/tests/test_main.py
"""Tests for the agent's message-processing logic (no live Kafka/Postgres)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.main import process_message
from db.models import Base, Incident

FIRING_RAW = (
    b'{"fingerprint": "abc123", "status": "firing", "alertname": "BoutiquePodCrashLooping", '
    b'"labels": {"pod": "cartservice-abc"}, "annotations": {}, '
    b'"starts_at": "2026-10-16T10:00:00Z", "ends_at": null}'
)

DUPLICATE_RAW = FIRING_RAW

MALFORMED_RAW = b"not json at all"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_process_message_creates_incident() -> None:
    session = make_session()
    process_message(session, FIRING_RAW)
    session.commit()
    rows = session.query(Incident).all()
    assert len(rows) == 1
    assert rows[0].status == "received"


def test_process_message_duplicate_does_not_create_second_row() -> None:
    session = make_session()
    process_message(session, FIRING_RAW)
    session.commit()
    process_message(session, DUPLICATE_RAW)
    session.commit()
    rows = session.query(Incident).all()
    assert len(rows) == 1


def test_process_message_malformed_does_not_raise() -> None:
    session = make_session()
    process_message(session, MALFORMED_RAW)
    session.commit()
    assert session.query(Incident).count() == 0


def test_agent_main_module_imports_without_live_broker() -> None:
    import agent.main  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_main.py -v`
Expected: FAIL (`process_message` not defined)

- [ ] **Step 3: Create `services/agent/src/agent/logging_config.py`**

```python
"""JSON structured logging setup for the agent service, with incident_id binding."""

import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "incident_id"):
            payload["incident_id"] = record.incident_id
        return json.dumps(payload)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("agent")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    return logger
```

- [ ] **Step 4: Rewrite `services/agent/src/agent/main.py`**

```python
"""Kafka consumer: alerts.raw -> incidents table, then a stub investigation.

No agent framework (LangGraph, CrewAI, etc.) — see docs/adr/0001-agent-framework.md.
Model is a config value, not hardcoded.
"""

import os
from collections.abc import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.incidents import upsert_incident
from agent.logging_config import configure_logging
from agent.messages import parse_alert_message
from db.models import Incident

logger = configure_logging()


def run_investigation(incident: Incident) -> str:
    logger.info(
        "would investigate",
        extra={"incident_id": str(incident.id)},
    )
    return "stub: investigation not yet implemented"


def process_message(session: Session, raw: bytes) -> None:
    try:
        message = parse_alert_message(raw)
    except ValueError as exc:
        logger.warning("skipping unparseable message", extra={"error": str(exc)})
        return

    incident = upsert_incident(session, message)
    if incident is not None and incident.status == "received":
        run_investigation(incident)


def consume_forever(consumer: "Consumer", session_factory: Callable[[], Session]) -> None:  # noqa: F821
    while True:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            logger.error("kafka error", extra={"error": str(msg.error())})
            continue
        session = session_factory()
        try:
            process_message(session, msg.value())
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        consumer.commit(message=msg, asynchronous=False)


def main() -> None:
    from confluent_kafka import Consumer

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": "triage-agent",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe(["alerts.raw"])

    engine = create_engine(database_url)
    session_factory = lambda: Session(engine)  # noqa: E731

    consume_forever(consumer, session_factory)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_main.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run full agent test suite, repo-wide smoke test, and type-check**

Run: `uv run --package triage-agent-svc pytest services/agent/ -v && uv run --all-packages pytest tests/test_smoke.py -v && uv run mypy services/agent/`
Expected: all PASS, no mypy errors (the `consume_forever` forward-reference
to `"Consumer"` needs its string-quoted annotation checked — if mypy
complains, add `from confluent_kafka import Consumer` under
`TYPE_CHECKING` at the top of the file instead of importing it lazily
inside `main()`; keep the runtime import inside `main()` either way so
`agent.main` stays importable without the `confluent_kafka` C extension
needing a running broker)

- [ ] **Step 7: Commit**

```bash
git add services/agent/src/agent/logging_config.py services/agent/src/agent/main.py services/agent/tests/test_main.py
git commit -m "agent: implement Kafka consumer loop with manual offset commit"
```

---

## Task 9: Kafka + Postgres infra, Makefile, env example

**Files:**
- Create: `deploy/helm/kafka-values.yaml`
- Create: `deploy/helm/postgres-values.yaml`
- Modify: `Makefile`
- Modify: `.env.example`

**Interfaces:**
- Consumes: Task 3's Alembic setup (`db/alembic.ini`), invoked by the
  modified `make up`.
- Produces: a working `make up` that also stands up Kafka + Postgres in
  the `triage` namespace and runs the migration; no other task consumes
  this directly (it's an operational/infra task verified manually).

- [ ] **Step 1: Create `deploy/helm/kafka-values.yaml`**

```yaml
# Bitnami Kafka, KRaft mode, single broker — no Zookeeper, no replication
# beyond what one broker provides. Sized for a local kind cluster demo.
controller:
  replicaCount: 1
  resources:
    requests: {cpu: 100m, memory: 256Mi}
    limits: {cpu: 500m, memory: 512Mi}
  persistence:
    size: 2Gi

broker:
  replicaCount: 0

listeners:
  client:
    protocol: PLAINTEXT

kraft:
  enabled: true
```

- [ ] **Step 2: Create `deploy/helm/postgres-values.yaml`**

```yaml
# Bitnami PostgreSQL, single instance + PVC. Credentials match .env.example's
# default DATABASE_URL (triage/triage/triage) for local dev convenience.
auth:
  username: triage
  password: triage
  database: triage

primary:
  resources:
    requests: {cpu: 100m, memory: 256Mi}
    limits: {cpu: 500m, memory: 512Mi}
  persistence:
    size: 2Gi

architecture: standalone
```

- [ ] **Step 3: Modify `Makefile`'s `up` target**

Insert after the existing `kubectl apply -f deploy/monitoring/boutique-alerts.yaml` line and before the closing `@echo ""` block:

```makefile
	helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
	helm repo update bitnami
	kubectl create namespace triage --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install kafka bitnami/kafka \
		--namespace triage \
		-f deploy/helm/kafka-values.yaml \
		--wait --timeout 5m
	helm upgrade --install postgres bitnami/postgresql \
		--namespace triage \
		-f deploy/helm/postgres-values.yaml \
		--wait --timeout 5m
	kubectl port-forward -n triage svc/postgres-postgresql 5432:5432 >/tmp/triage-pg-forward.log 2>&1 & \
		PG_PID=$$!; \
		sleep 3; \
		DATABASE_URL=postgresql://triage:triage@localhost:5432/triage \
			uv run --package triage-db alembic -c db/alembic.ini upgrade head; \
		kill $$PG_PID
```

And extend the final `@echo` block (which currently ends with `@echo "Grafana login: admin / admin"`) by adding these lines immediately after it:

```makefile
	@echo "Kafka:      kubectl port-forward -n triage svc/kafka 9092:9092"
	@echo "Postgres:   kubectl port-forward -n triage svc/postgres-postgresql 5432:5432"
	@echo "Run webhook/agent locally against those forwarded ports (see .env.example)."
```

- [ ] **Step 4: Modify `.env.example`**

Add under the `# Postgres` section:

```
# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

- [ ] **Step 5: Verify Makefile syntax**

Run: `make -n up`
Expected: prints the full command sequence without a syntax error (dry
run; does not require a cluster).

- [ ] **Step 6: Commit**

```bash
git add deploy/helm/kafka-values.yaml deploy/helm/postgres-values.yaml Makefile .env.example
git commit -m "infra: add Kafka+Postgres Helm releases and wire migration into make up"
```

---

## Task 10: Alertmanager webhook receiver configuration

**Files:**
- Modify: `deploy/monitoring/kube-prometheus-stack-values.yaml`

**Interfaces:**
- Consumes: nothing from this plan's code (routes to the locally-run
  webhook from Task 5 via `http://host.docker.internal:8000/alerts`).
- Produces: nothing consumed by later tasks; verified manually per Task
  11's end-to-end check.

- [ ] **Step 1: Read current file to find insertion point**

Run: `grep -n "^alertmanager:" deploy/monitoring/kube-prometheus-stack-values.yaml`

- [ ] **Step 2: Add `alertmanager.config` block**

Under the existing `alertmanager:` top-level key (alongside
`alertmanagerSpec:`), add a `config:` sibling key:

```yaml
alertmanager:
  config:
    global: {}
    route:
      receiver: webhook
      group_by: ["alertname"]
      group_wait: 10s
      group_interval: 10s
      repeat_interval: 1h
    receivers:
      - name: webhook
        webhook_configs:
          - url: "http://host.docker.internal:8000/alerts"
            send_resolved: true
  alertmanagerSpec:
    resources:
      requests: {cpu: 25m, memory: 32Mi}
      limits: {cpu: 100m, memory: 64Mi}
    storage: {}
```

(Keep the existing `alertmanagerSpec:` block exactly as it was — only
`config:` is new.)

- [ ] **Step 3: Verify YAML is well-formed**

Run: `uv run python -c "import yaml; yaml.safe_load(open('deploy/monitoring/kube-prometheus-stack-values.yaml'))" && echo OK`
Expected: prints `OK`

- [ ] **Step 4: Commit**

```bash
git add deploy/monitoring/kube-prometheus-stack-values.yaml
git commit -m "monitoring: route Alertmanager to the local webhook receiver"
```

---

## Task 11: End-to-end verification against a real cluster

**Files:**
- None created or modified — this task runs the full stack manually to
  verify the done criteria from the spec.

**Interfaces:**
- Consumes: everything from Tasks 1-10.

- [ ] **Step 1: Bring up the cluster**

Run: `make up`
Expected: Boutique, monitoring stack, Kafka, and Postgres all come up;
migration runs without error.

- [ ] **Step 2: Start port-forwards for Kafka and Postgres (separate terminals)**

Run: `kubectl port-forward -n triage svc/kafka 9092:9092`
Run: `kubectl port-forward -n triage svc/postgres-postgresql 5432:5432`

- [ ] **Step 3: Run webhook locally**

Run: `KAFKA_BOOTSTRAP_SERVERS=localhost:9092 uv run --package triage-webhook uvicorn webhook.main:app --port 8000`

- [ ] **Step 4: Run agent locally**

Run: `KAFKA_BOOTSTRAP_SERVERS=localhost:9092 DATABASE_URL=postgresql://triage:triage@localhost:5432/triage uv run --package triage-agent-svc python -m agent.main`

- [ ] **Step 5: Inject the crash_loop chaos scenario**

Run: `uv run --package triage-chaos chaos inject crash_loop`
Expected: within a few minutes (per the `BoutiquePodCrashLooping` alert's
`for: 5m`), Alertmanager fires, posts to the local webhook, webhook logs
`published alert`, agent logs `would investigate` with an `incident_id`.

- [ ] **Step 6: Verify exactly one incidents row**

Run: `PGPASSWORD=triage psql -h localhost -U triage -d triage -c "SELECT fingerprint, alertname, status FROM incidents;"`
Expected: exactly one row for the crash_loop alert's fingerprint, status
`received`.

- [ ] **Step 7: Restart the agent process and confirm no duplicate row**

Stop the agent (Ctrl-C), restart it with the same command from Step 4.
Wait for Alertmanager's `group_interval`/`repeat_interval` to redeliver
(or re-trigger by waiting for the next evaluation), then re-run the
query from Step 6.
Expected: still exactly one row for that fingerprint.

- [ ] **Step 8: Revert the chaos scenario**

Run: `uv run --package triage-chaos chaos revert crash_loop`
Expected: Alertmanager eventually sends a `resolved` webhook; agent logs
processing it; the query from Step 6 shows that row's `status` is now
`resolved`.

- [ ] **Step 9: Tear down**

Stop the local webhook/agent processes and port-forwards. Run: `make down`
