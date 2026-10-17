# Alert pipeline design: Alertmanager -> webhook -> Kafka -> agent -> Postgres

## Status

Proposed

## Context

This is step 4 of the triage-agent build: the first end-to-end path from a
firing Kubernetes alert to a tracked incident row, with the agent's
investigation logic still stubbed out. Today `services/webhook` and
`services/agent` are empty skeletons (`NotImplementedError` stubs), there is
no Kafka or Postgres in the cluster, and Alertmanager (deployed as part of
`kube-prometheus-stack` via `make up`) has no configured receiver.

Done criteria for this step (from the request):

- `chaos inject crash_loop` produces exactly one `incidents` row.
- Restarting the consumer does not create duplicates.
- Logs for that incident can be found by `incident_id` in Loki.

## Decision

Build the full path, with webhook and agent run locally (not yet
containerized/deployed into the cluster) against port-forwarded Kafka and
Postgres:

```
Alertmanager (in-cluster) --http--> webhook (local, FastAPI)
                                         |
                                         v
                              Kafka topic alerts.raw (port-forwarded)
                                         |
                                         v
                              agent (local, Kafka consumer)
                                         |
                                         v
                              Postgres `incidents` table (port-forwarded)
```

Dockerfiles, `kind load docker-image`, and in-cluster Deployments for
webhook/agent are explicitly deferred to a later step.

## Components

### Infra: Kafka + Postgres (`make up`)

- Bitnami Kafka Helm chart, KRaft mode (no Zookeeper), single broker,
  namespace `triage`. Topic `alerts.raw`: 1 partition, replication factor 1
  (single broker can't replicate further; 1 partition keeps per-fingerprint
  ordering trivial without needing to reason about partition assignment).
- Bitnami PostgreSQL Helm chart, single instance + PVC, namespace `triage`.
- New values files: `deploy/helm/kafka-values.yaml`,
  `deploy/helm/postgres-values.yaml`.
- `make up` additions: create `triage` namespace, `helm upgrade --install`
  both charts, then run `alembic upgrade head` (see `db/` below) against a
  `DATABASE_URL` reachable via a short-lived port-forward the Makefile opens
  and closes around that one command.
- `make up` prints (doesn't background) the `kubectl port-forward` commands
  for Kafka and Postgres for local dev use, matching the existing pattern
  for Grafana/Prometheus/Boutique.

### Alertmanager routing

- `deploy/monitoring/kube-prometheus-stack-values.yaml` gains an
  `alertmanager.config` block: a single receiver `webhook` of type
  `webhook_configs`, URL `http://host.docker.internal:8000/alerts`, default
  route sends everything to it (no routing tree needed yet).
- `host.docker.internal` relies on kind's node containers being able to
  reach the host machine, which Docker Desktop/Podman on macOS support
  directly. This only needs to work on the dev machine, not generally.

### Kafka message contract (topic `alerts.raw`)

One message per alert per webhook POST (Alertmanager's payload carries an
`alerts[]` array; a single POST fans out to N messages). Key = alert
fingerprint (UTF-8 bytes). Value = JSON:

```json
{
  "fingerprint": "string",
  "status": "firing | resolved",
  "alertname": "string",
  "labels": {"...": "..."},
  "annotations": {"...": "..."},
  "starts_at": "RFC3339 timestamp",
  "ends_at": "RFC3339 timestamp or null"
}
```

The webhook validates Alertmanager's own webhook JSON shape with Pydantic
models first, then maps to this schema before publishing — the Kafka
contract is decoupled from Alertmanager's wire format.

### `db/` package (new workspace member, shared by `agent` and future
`executor`)

- `db/pyproject.toml`, `db/src/db/models.py` (SQLAlchemy declarative model
  for `incidents`), `db/alembic.ini`, `db/migrations/` (env configured from
  `DATABASE_URL`).
- Added to root `pyproject.toml`'s `[tool.uv.workspace]` members.
- Schema:

  ```
  incidents
    id           uuid        pk, server_default gen_random_uuid()
    fingerprint  text        not null
    alertname    text        not null
    labels       jsonb       not null
    status       text        not null   -- 'received' | 'resolved'
    created_at   timestamptz not null, server_default now()
  ```

  Partial unique index: `UNIQUE (fingerprint) WHERE status = 'received'`.

  This index is the mechanism for "exactly one incident per fingerprint
  while firing": a firing message for an already-`received` fingerprint
  hits a unique violation on insert, which the consumer treats as "already
  tracked, no-op" rather than an error. A resolved message updates the
  matching `received` row's status to `resolved` (no matching row ->
  no-op; e.g. resolved arrives for a fingerprint we never recorded, or one
  already resolved).

- One Alembic revision for this step: create `incidents` + the partial
  unique index.

### `services/webhook`

- `POST /alerts`: Pydantic models for the Alertmanager webhook payload
  (`version`, `groupKey`, `status`, `receiver`, `alerts: list[Alert]`, each
  alert with `status`, `labels`, `annotations`, `startsAt`, `endsAt`,
  `fingerprint`). Maps each alert to the Kafka message schema above,
  produces to `alerts.raw` keyed by fingerprint, synchronously
  (`produce()` + `poll()`/`flush()`) so a 200 response means the broker has
  the message. Returns `{"accepted": <n>}`.
- `GET /healthz`: 200 plus a cheap producer/broker connectivity check.
- Kafka client: `confluent-kafka-python`, `acks=all`.
- JSON log line per request: `fingerprint`, `alertname`, `status`.

### `services/agent`

- Kafka consumer (`confluent-kafka-python`), single consumer group,
  `enable.auto.commit=False`.
- Per message: parse JSON -> open DB transaction -> if `status=="firing"`,
  insert into `incidents` (status `received`), catching the unique
  violation as a no-op; if `status=="resolved"`, `UPDATE ... SET
  status='resolved' WHERE fingerprint=... AND status='received'` (no-op if
  0 rows matched) -> commit DB transaction -> commit Kafka offset for that
  message -> call stub `investigate(incident)` (logs `"would investigate"`
  with `incident_id` bound via a logging adapter/`extra`).
- Ordering: DB commit happens before the Kafka offset commit, so a crash
  between them causes redelivery, which lands on the no-op path — never a
  lost or duplicated incident.
- Uses `db.models` (SQLAlchemy) for the insert/update instead of hand-rolled
  SQL strings, for mypy-strict-friendly typing.

### Logging

Both services configure stdlib `logging` with a JSON formatter (no shared
package — each service's setup is ~15 lines, duplicated rather than
abstracted). The agent binds `incident_id` into every log record for a
given message's processing via a `LoggerAdapter`/`extra=`, satisfying the
"logs findable by incident_id in Loki" done-criterion (Promtail already
ships container stdout to Loki per the existing monitoring stack — no
changes needed there, since webhook/agent will run locally as processes
and these logs don't flow into Loki yet in this step, but the format is
rehearsal for when they do).

## Testing

- `services/webhook/tests/`: valid single-alert payload -> one Kafka
  message with correct mapped shape; multi-alert payload -> one message
  per alert; malformed payload -> 422.
- `services/agent/tests/`: same fingerprint firing message processed twice
  (simulated redelivery/restart) -> exactly one `incidents` row; firing
  then resolved -> row transitions to `resolved`; resolved with no prior
  firing row -> no-op, no crash.
- `db/tests/`: migration applies cleanly; partial unique index behavior
  (two inserts with same fingerprint while both `received` -> second
  raises; insert after first is `resolved` -> succeeds).

## Open items explicitly deferred

- Dockerfiles, `kind load docker-image`, in-cluster Deployments for
  webhook/agent.
- Routing beyond a single default Alertmanager receiver.
- Any `status` values beyond `received`/`resolved` (e.g. `investigating`).
- Backgrounded/managed port-forwards for local dev (`make up` only prints
  the commands).
