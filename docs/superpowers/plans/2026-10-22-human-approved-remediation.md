# Human-Approved Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the agent's free-text `suggested_fix` into a typed remediation
action that a human must approve in Discord or the dashboard before
`services/executor` runs it, with every tool call, model call, approval,
rejection, and execution recorded in an audit log, and an eval check proving
no action ever runs unapproved.

**Architecture:** `Finding.suggested_fix` becomes a Pydantic discriminated
union (rollback/restart/scale/manual) enforced at the LLM tool-call boundary.
A new `actions` table tracks each proposed action's approval lifecycle; a new
`audit_log` table records every tool call, model call, approval, rejection,
and execution. `services/bot` gains Approve/Reject buttons gated by a Discord
role; `services/executor` polls for approved actions, executes them against
a namespace-scoped k8s client, and watches `incidents.status` for recovery.
`services/dashboard` (FastAPI, Discord OAuth2) + `dashboard/` (Vite+React+TS)
expose the same data and the same approve/reject code path read-only plus
approve/reject. `eval/` gets a check that queries the live `actions` table
for any executed/failed row with no prior approval.

**Tech Stack:** Python 3.12, SQLAlchemy + Alembic, discord.py 2.4,
kubernetes client, FastAPI, Authlib (Discord OAuth2), Vite + React + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-22-human-approved-remediation-design.md`

## Global Constraints

- Agent (`services/agent`) stays read-only — it must never gain a mutating
  k8s verb; only `services/executor` mutates cluster state, and only after
  an approval row exists (spec: Scope, Safety rules in CLAUDE.md).
- Model choice stays a config value, never hardcoded (CLAUDE.md).
- No new message queue between bot/dashboard and executor — approval
  handoff is entirely through the `actions` table via polling (spec: Out of
  scope).
- `mypy --strict` enforced repo-wide including tests (CLAUDE.md); every new
  file needs full type hints.
- Dependency management via `uv`; new workspace members get a
  `pyproject.toml` with `triage-db = { workspace = true }` where they use
  `db.models`, and must be added to the root `pyproject.toml`'s
  `tool.mypy.mypy_path`.
- A `manual` action is never executable — no Approve button/control may
  ever be offered for it, and the executor independently refuses to
  execute `type == "manual"` even if one is ever claimed (spec: `actions`
  table notes).
- Dashboard write endpoints re-check the caller's current Discord guild
  roles live on every request, never trusting a cached session claim
  (spec: Dashboard auth).

## Review Focus

- **Pre-existing free-text `suggested_fix` call sites break silently if
  missed.** `services/agent/src/agent/investigate.py` (`_partial_findings`),
  `eval/src/eval/baselines.py` (both baseline functions), and every test
  file listed in Task 1's file list construct `Findings(suggested_fix=...)`
  with a bare string — each one must be updated to a typed action or the
  whole test suite fails type-checking/validation, not just the new tests.
  Covered by: Task 1 (grep-driven call-site inventory) and Task 1's own test
  run across the full repo.
- **A non-approver clicking Approve/Reject must be silently refused, not
  silently allowed.** A Discord member without the configured role must
  never be able to transition an `actions` row — this is the core safety
  property the spec exists to protect. Covered by: Task 4's
  `test_approve_rejects_member_without_role`.
- **A `manual` action must never reach the executor's execute path even if
  it is somehow claimed.** Defense in depth against a future bug in the UI
  layer that offers a button it shouldn't. Covered by: Task 5's
  `test_executor_refuses_manual_action`.
- **Executor must not act twice on the same approved action if polled
  concurrently.** The claim step (`UPDATE ... WHERE status='approved' ...
  RETURNING *`) must be atomic against a second poll cycle picking up the
  same row. Covered by: Task 5's `test_claim_is_atomic_under_concurrent_poll`.
- **A session whose Discord role was revoked mid-session must lose approve
  access on its very next request**, not just at next login. Covered by:
  Task 8's `test_approve_rejected_after_role_revoked_mid_session`.
- **The 5-minute recovery window must time out cleanly, not hang or crash,
  when the alert never resolves.** Covered by: Task 5's
  `test_recovery_poll_times_out_after_5_minutes` using a fake clock.

---

## File Structure

```
db/
  src/db/models.py                  # Finding.suggested_fix -> JSONB; new Action, AuditLog models
  migrations/versions/0005_...py    # convert suggested_fix to JSONB + backfill
  migrations/versions/0006_...py    # create actions table
  migrations/versions/0007_...py    # create audit_log table

services/agent/src/agent/
  findings.py                       # SuggestedFix discriminated union
  investigate.py                    # _partial_findings uses ManualAction
  findings_store.py                 # suggested_fix=findings.suggested_fix.model_dump()

services/bot/src/bot/
  format.py                         # render structured suggested_fix as text
  actions.py                        # NEW: shared approve/reject logic (role check + state transition + audit_log)
  views.py                          # NEW: discord.ui.View (buttons) + discord.ui.Modal (reject reason)
  main.py                           # wire buttons into post_findings; insert pending actions row

services/executor/src/executor/
  main.py                           # poll loop: claim -> dispatch -> watch recovery -> post outcome
  k8s_client.py                     # NEW: K8sExecutorClient (rollback/restart/scale), namespace-scoped
  discord_notify.py                 # NEW: post outcome via webhook URL

services/dashboard/                 # NEW service
  pyproject.toml
  src/dashboard/
    __init__.py
    main.py                         # FastAPI app, CORS
    auth.py                         # Discord OAuth2 login/callback, session cookie, live role check
    api.py                          # GET /incidents, /incidents/{id}, /incidents/{id}/actions; POST approve/reject
  tests/
    test_auth.py
    test_api.py

dashboard/                          # NEW Vite + React + TS app
  package.json
  src/
    main.tsx
    App.tsx
    api.ts                          # fetch wrappers for services/dashboard endpoints
    pages/IncidentList.tsx
    pages/IncidentDetail.tsx
  index.html

eval/src/eval/
  baselines.py                      # both baselines use ManualAction
  scoring.py                        # agent_suggested_fix payload uses .model_dump()
  unsafe_actions.py                 # NEW: check_unsafe_actions(session) -> int
  cli.py                            # call check_unsafe_actions, exit 1 if > 0

deploy/k8s/
  rbac-triage-executor.yaml         # NEW: namespaced Role, boutique namespace only

tests/
  test_rbac_triage_executor.py      # NEW: mirrors test_rbac_triage_agent.py
```

---

## Task 1: Typed `suggested_fix` action schema

**Files:**
- Modify: `services/agent/src/agent/findings.py`
- Modify: `services/agent/src/agent/investigate.py:60-70` (`_partial_findings`)
- Modify: `services/agent/src/agent/findings_store.py:22`
- Modify: `services/agent/tests/test_findings.py`
- Modify: `services/agent/tests/test_investigate.py:55`
- Modify: `services/agent/tests/test_findings_store.py:37`
- Modify: `services/agent/tests/test_consumer.py:61`
- Modify: `services/bot/src/bot/format.py:43`
- Modify: `services/bot/tests/test_format.py:23,59,93`
- Modify: `services/bot/tests/test_poll.py:34`
- Modify: `eval/src/eval/baselines.py:26,66`
- Modify: `eval/src/eval/scoring.py:44`
- Modify: `eval/tests/test_scoring.py:37`
- Modify: `eval/tests/test_runner.py:87,181,273,383`
- Test: `services/agent/tests/test_findings.py`

**Interfaces:**
- Produces: `agent.findings.RollbackAction(type: Literal["rollback"], deployment: str, reason: str)`,
  `RestartAction(type: Literal["restart"], deployment: str, reason: str)`,
  `ScaleAction(type: Literal["scale"], deployment: str, replicas: int, reason: str)`,
  `ManualAction(type: Literal["manual"], reason: str)`,
  `SuggestedFix = Annotated[RollbackAction | RestartAction | ScaleAction | ManualAction, Field(discriminator="type")]`.
  `Findings.suggested_fix: SuggestedFix`. Every later task that touches a
  `Finding` row or a `Findings` object uses these exact names.

- [ ] **Step 1: Write the failing tests for the four action variants and rejection of unknown shapes**

Replace the body of `services/agent/tests/test_findings.py` with:

```python
import pytest
from agent.findings import (
    Evidence,
    Findings,
    ManualAction,
    RestartAction,
    RollbackAction,
    ScaleAction,
    findings_tool_schema,
)
from pydantic import ValidationError


def _base_kwargs(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = dict(
        summary="cartservice is crash-looping",
        root_cause="missing REDIS_ADDR env var",
        confidence="high",
        evidence=[Evidence(tool_call_id="abc-123", detail="pod shows CrashLoopBackOff")],
        affected_services=["cartservice"],
        suggested_fix=RollbackAction(
            type="rollback", deployment="cartservice", reason="bad deploy"
        ),
        ruled_out=["network policy block"],
        status="complete",
    )
    defaults.update(overrides)
    return defaults


def test_valid_findings_construct_successfully_with_rollback_action() -> None:
    findings = Findings(**_base_kwargs())
    assert findings.confidence == "high"
    assert isinstance(findings.suggested_fix, RollbackAction)
    assert findings.suggested_fix.deployment == "cartservice"


def test_restart_action_requires_deployment_and_reason() -> None:
    findings = Findings(
        **_base_kwargs(
            suggested_fix=RestartAction(
                type="restart", deployment="cartservice", reason="stuck connection pool"
            )
        )
    )
    assert isinstance(findings.suggested_fix, RestartAction)


def test_scale_action_requires_replicas() -> None:
    findings = Findings(
        **_base_kwargs(
            suggested_fix=ScaleAction(
                type="scale", deployment="checkoutservice", replicas=3, reason="under load"
            )
        )
    )
    assert isinstance(findings.suggested_fix, ScaleAction)
    assert findings.suggested_fix.replicas == 3


def test_manual_action_carries_only_reason() -> None:
    findings = Findings(
        **_base_kwargs(suggested_fix=ManualAction(type="manual", reason="needs human review"))
    )
    assert isinstance(findings.suggested_fix, ManualAction)


def test_suggested_fix_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Findings(**_base_kwargs(suggested_fix={"type": "delete_everything", "reason": "x"}))


def test_suggested_fix_rejects_dict_missing_discriminator() -> None:
    with pytest.raises(ValidationError):
        Findings(**_base_kwargs(suggested_fix={"deployment": "cartservice", "reason": "x"}))


def test_confidence_rejects_values_outside_the_allowed_set() -> None:
    with pytest.raises(ValidationError):
        Findings(
            **_base_kwargs(confidence="extremely high")  # type: ignore[arg-type]
        )


def test_status_rejects_values_outside_the_allowed_set() -> None:
    with pytest.raises(ValidationError):
        Findings(
            **_base_kwargs(status="in_progress")  # type: ignore[arg-type]
        )


def test_findings_tool_schema_excludes_status() -> None:
    schema = findings_tool_schema()
    assert schema["name"] == "submit_findings"
    input_schema = schema["input_schema"]
    assert isinstance(input_schema, dict)
    properties = input_schema["properties"]
    assert "status" not in properties
    assert "summary" in properties
    assert "evidence" in properties
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_findings.py -v`
Expected: FAIL — `ImportError: cannot import name 'RollbackAction'` (doesn't exist yet).

- [ ] **Step 3: Implement the discriminated union in `services/agent/src/agent/findings.py`**

Replace the file's contents:

```python
"""Validated JSON findings output: the agent's conclusion for one incident."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    tool_call_id: str
    detail: str


class RollbackAction(BaseModel):
    type: Literal["rollback"]
    deployment: str
    reason: str


class RestartAction(BaseModel):
    type: Literal["restart"]
    deployment: str
    reason: str


class ScaleAction(BaseModel):
    type: Literal["scale"]
    deployment: str
    replicas: int
    reason: str


class ManualAction(BaseModel):
    type: Literal["manual"]
    reason: str


SuggestedFix = Annotated[
    RollbackAction | RestartAction | ScaleAction | ManualAction,
    Field(discriminator="type"),
]


class Findings(BaseModel):
    summary: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[Evidence]
    affected_services: list[str]
    suggested_fix: SuggestedFix
    ruled_out: list[str]
    status: Literal["complete", "budget_exceeded"]


def findings_tool_schema() -> dict[str, object]:
    input_schema: dict[str, Any] = Findings.model_json_schema()
    del input_schema["properties"]["status"]
    input_schema["required"] = [f for f in input_schema["required"] if f != "status"]

    return {
        "name": "submit_findings",
        "description": (
            "Submit the final root-cause findings for this incident. Every evidence "
            "item's tool_call_id must match a tool call actually made during this "
            "investigation. suggested_fix must be exactly one of: rollback (revert a "
            "deployment to its previous version), restart (roll a deployment's pods), "
            "scale (change a deployment's replica count), or manual (free-text guidance "
            "when no safe automated action applies — this is never executed automatically)."
        ),
        "input_schema": input_schema,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --package triage-agent-svc pytest services/agent/tests/test_findings.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Fix every other call site that constructs `Findings(suggested_fix=<str>)`**

In `services/agent/src/agent/investigate.py`, update the import and
`_partial_findings`:

```python
from agent.findings import Findings, ManualAction, findings_tool_schema
```

```python
def _partial_findings(reason: str) -> Findings:
    return Findings(
        summary=f"Investigation stopped: {reason}",
        root_cause="unknown — investigation did not reach a conclusion",
        confidence="low",
        evidence=[],
        affected_services=[],
        suggested_fix=ManualAction(type="manual", reason="manual investigation required"),
        ruled_out=[],
        status="budget_exceeded",
    )
```

In `services/agent/src/agent/findings_store.py`, serialize the union to a
plain dict before writing JSONB:

```python
        suggested_fix=findings.suggested_fix.model_dump(),
```

In `eval/src/eval/baselines.py`, add the import and update both
`suggested_fix=` lines:

```python
from agent.findings import Findings, ManualAction
```

```python
        suggested_fix=ManualAction(type="manual", reason="manual investigation required"),
```

(applies to both `rule_based_root_cause` and `llm_no_tools_root_cause`)

In `eval/src/eval/scoring.py:44`, serialize for the judge prompt payload:

```python
        "agent_suggested_fix": findings.suggested_fix.model_dump(),
```

In `services/bot/src/bot/format.py`, render the structured action as text.
Replace the "Suggested fix" field value:

```python
def _render_suggested_fix(fix: object) -> str:
    assert isinstance(fix, dict)
    fix_type = fix["type"]
    reason = fix["reason"]
    if fix_type == "rollback":
        return f"rollback {fix['deployment']}: {reason}"
    if fix_type == "restart":
        return f"restart {fix['deployment']}: {reason}"
    if fix_type == "scale":
        return f"scale {fix['deployment']} to {fix['replicas']} replicas: {reason}"
    return f"manual: {reason}"
```

and in `format_embed`, change the "Suggested fix" field's `"value"` to:

```python
                "value": _truncate(_render_suggested_fix(finding.suggested_fix), _FIELD_VALUE_MAX),
```

- [ ] **Step 6: Fix every test fixture across the repo that passes a bare string for `suggested_fix`**

`services/agent/tests/test_investigate.py:55` — in the fixture dict for
the `submit_findings` tool-call args, change:
```python
    "suggested_fix": "set REDIS_ADDR",
```
to:
```python
    "suggested_fix": {"type": "manual", "reason": "set REDIS_ADDR"},
```

`services/agent/tests/test_findings_store.py:37` — add the import
`from agent.findings import ManualAction` and change:
```python
        suggested_fix="set REDIS_ADDR",
```
to:
```python
        suggested_fix=ManualAction(type="manual", reason="set REDIS_ADDR"),
```
Then find the assertion on the saved row's `suggested_fix` in that same
test and update it to compare against `{"type": "manual", "reason": "set REDIS_ADDR"}`
(the `.model_dump()` form), since `findings_store.save_finding` now
dumps the union to a dict before writing.

`services/agent/tests/test_consumer.py:61` — in the fixture dict, change:
```python
            "suggested_fix": "stub",
```
to:
```python
            "suggested_fix": {"type": "manual", "reason": "stub"},
```

`services/bot/tests/test_format.py` — add the import
`from agent.findings import RollbackAction` and change line 23's
`suggested_fix="kubectl set env deployment/cartservice REDIS_ADDR=redis:6379",`
to:
```python
        suggested_fix=RollbackAction(
            type="rollback", deployment="cartservice", reason="bad deploy"
        ).model_dump(),
```
(the `Finding` row stores the raw dict, mirroring what
`findings_store.save_finding` now writes). Update the assertion in
`test_format_embed_includes_suggested_fix_and_cost` (around line 59) to
check for the rendered text `"rollback cartservice: bad deploy"` instead
of the old literal string. Update line 93's `make_finding(suggested_fix="x" * 5000)`
truncation test to use a long `reason`:
```python
    embed = format_embed(
        make_finding(
            suggested_fix=ManualAction(type="manual", reason="x" * 5000).model_dump()
        )
    )
```
(add `from agent.findings import ManualAction` to this file's imports too).

`services/bot/tests/test_poll.py:34` — change:
```python
        suggested_fix="x",
```
to:
```python
        suggested_fix={"type": "manual", "reason": "x"},
```

`eval/tests/test_scoring.py:37` — add `from agent.findings import ManualAction`
and change:
```python
    suggested_fix="restore PORT to 50051",
```
to:
```python
    suggested_fix=ManualAction(type="manual", reason="restore PORT to 50051"),
```

`eval/tests/test_runner.py` — at each of lines 87, 181, 273, 383, change
the fixture dict entry:
```python
                            "suggested_fix": "restore PORT to 50051",
```
(or `"suggested_fix": "f",` at the other three) to the structured form,
e.g.:
```python
                            "suggested_fix": {"type": "manual", "reason": "restore PORT to 50051"},
```
and
```python
                    "suggested_fix": {"type": "manual", "reason": "f"},
```
respectively, matching each line's surrounding dict.

- [ ] **Step 7: Run the full repo test suite and mypy to verify nothing else references the old shape**

Run: `uv run --all-packages pytest`
Expected: PASS, 0 failures.

Run: `uv run --all-packages mypy .`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(agent): make suggested_fix a typed rollback/restart/scale/manual action"
```

---

## Task 2: `Finding.suggested_fix` column migration to JSONB

**Files:**
- Modify: `db/src/db/models.py` (`Finding.suggested_fix`)
- Create: `db/migrations/versions/0005_convert_suggested_fix_to_jsonb.py`
- Test: `db/tests/test_models.py`

**Interfaces:**
- Consumes: nothing from Task 1 at the DB layer (Task 1 already made
  `findings_store.py` write dicts, which SQLAlchemy's `JSONB` column type
  will accept once this migration lands).
- Produces: `Finding.suggested_fix: Mapped[dict[str, object]]` (JSONB).
  Task 3 and Task 5 read this column.

- [ ] **Step 1: Write the failing test**

Add to `db/tests/test_models.py`:

```python
def test_finding_suggested_fix_accepts_structured_action(session: Session) -> None:
    incident = Incident(
        fingerprint="fp-1", alertname="PodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()

    finding = Finding(
        incident_id=incident.id,
        summary="s",
        root_cause="r",
        confidence="high",
        evidence=[],
        affected_services=[],
        suggested_fix={"type": "rollback", "deployment": "cartservice", "reason": "bad deploy"},
        ruled_out=[],
        status="complete",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.01"),
    )
    session.add(finding)
    session.flush()
    session.refresh(finding)

    assert finding.suggested_fix == {
        "type": "rollback",
        "deployment": "cartservice",
        "reason": "bad deploy",
    }
```

(Check the top of `db/tests/test_models.py` for the existing `session`
fixture, `Decimal` import, and `Incident`/`Finding` imports — reuse them;
don't add a second fixture.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-db pytest db/tests/test_models.py -v -k suggested_fix`
Expected: FAIL — either a type error from mypy on the dict literal against
a `Text`-typed column, or (if run against a live test DB) a `DataError`
from Postgres rejecting the dict as text.

- [ ] **Step 3: Change the column type in `db/src/db/models.py`**

Find the `Finding` class and change:
```python
    suggested_fix: Mapped[str] = mapped_column(Text)
```
to:
```python
    suggested_fix: Mapped[dict[str, object]] = mapped_column(JSONB)
```

- [ ] **Step 4: Write the migration**

Create `db/migrations/versions/0005_convert_suggested_fix_to_jsonb.py`:

```python
"""convert findings.suggested_fix to jsonb, wrapping existing text as a manual action

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "findings",
        "suggested_fix",
        type_=postgresql.JSONB(),
        postgresql_using=(
            "jsonb_build_object('type', 'manual', 'reason', suggested_fix)"
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "findings",
        "suggested_fix",
        type_=sa.Text(),
        postgresql_using="suggested_fix ->> 'reason'",
    )
```

- [ ] **Step 5: Run the migration against the dev database and re-run the test**

Run: `uv run --package triage-db alembic -c db/migrations/alembic.ini upgrade head`

(If `alembic.ini`'s path differs from this, check `db/migrations/env.py`
for how existing migrations are invoked in CI — `.github/workflows/ci.yml`
has the exact command; use that same invocation.)

Run: `uv run --package triage-db pytest db/tests/test_models.py -v -k suggested_fix`
Expected: PASS

- [ ] **Step 6: Run the full db package test suite**

Run: `uv run --package triage-db pytest db/tests/`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add db/src/db/models.py db/migrations/versions/0005_convert_suggested_fix_to_jsonb.py db/tests/test_models.py
git commit -m "feat(db): convert findings.suggested_fix to jsonb"
```

---

## Task 3: `actions` and `audit_log` tables

**Files:**
- Modify: `db/src/db/models.py` (add `Action`, `AuditLog`)
- Create: `db/migrations/versions/0006_create_actions.py`
- Create: `db/migrations/versions/0007_create_audit_log.py`
- Test: `db/tests/test_models.py`

**Interfaces:**
- Produces: `Action` model with columns `id, incident_id, finding_id, type,
  deployment, replicas, reason, status, approved_by, approved_at,
  rejection_reason, executed_at, outcome, created_at`.
  `AuditLog` model with columns `id, incident_id, actor, event_type, detail,
  created_at`. Tasks 4, 5, 6, 7, 8 all import `from db.models import Action, AuditLog`.

- [ ] **Step 1: Write the failing tests**

Add to `db/tests/test_models.py`:

```python
def test_action_lifecycle_columns(session: Session) -> None:
    incident = Incident(
        fingerprint="fp-2", alertname="PodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()
    finding = Finding(
        incident_id=incident.id,
        summary="s",
        root_cause="r",
        confidence="high",
        evidence=[],
        affected_services=[],
        suggested_fix={"type": "rollback", "deployment": "cartservice", "reason": "bad deploy"},
        ruled_out=[],
        status="complete",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.01"),
    )
    session.add(finding)
    session.flush()

    action = Action(
        incident_id=incident.id,
        finding_id=finding.id,
        type="rollback",
        deployment="cartservice",
        replicas=None,
        reason="bad deploy",
        status="pending",
    )
    session.add(action)
    session.flush()
    session.refresh(action)

    assert action.status == "pending"
    assert action.approved_by is None
    assert action.created_at is not None


def test_audit_log_detail_is_jsonb(session: Session) -> None:
    incident = Incident(
        fingerprint="fp-3", alertname="PodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()

    entry = AuditLog(
        incident_id=incident.id,
        actor="agent",
        event_type="tool_call",
        detail={"tool": "describe_pod", "duration_ms": 120},
    )
    session.add(entry)
    session.flush()
    session.refresh(entry)

    assert entry.detail == {"tool": "describe_pod", "duration_ms": 120}
    assert entry.created_at is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package triage-db pytest db/tests/test_models.py -v -k "action_lifecycle or audit_log"`
Expected: FAIL — `ImportError: cannot import name 'Action'`.

- [ ] **Step 3: Add the models to `db/src/db/models.py`**

Append after the `Finding` class:

```python
class Action(Base):
    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(Text)
    deployment: Mapped[str | None] = mapped_column(Text, nullable=True)
    replicas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actor: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Write the two migrations**

Create `db/migrations/versions/0006_create_actions.py`:

```python
"""create actions table

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("deployment", sa.Text(), nullable=True),
        sa.Column("replicas", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_actions_incident_id", "actions", ["incident_id"])
    op.create_index(
        "ix_actions_pending",
        "actions",
        ["status"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_actions_approved",
        "actions",
        ["status"],
        postgresql_where=sa.text("status = 'approved'"),
    )


def downgrade() -> None:
    op.drop_index("ix_actions_approved", table_name="actions")
    op.drop_index("ix_actions_pending", table_name="actions")
    op.drop_index("ix_actions_incident_id", table_name="actions")
    op.drop_table("actions")
```

Create `db/migrations/versions/0007_create_audit_log.py`:

```python
"""create audit_log table

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_log_incident_id", "audit_log", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_incident_id", table_name="audit_log")
    op.drop_table("audit_log")
```

- [ ] **Step 5: Run the migrations and the tests**

Run: `uv run --package triage-db alembic -c db/migrations/alembic.ini upgrade head`
Run: `uv run --package triage-db pytest db/tests/test_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add db/src/db/models.py db/migrations/versions/0006_create_actions.py db/migrations/versions/0007_create_audit_log.py db/tests/test_models.py
git commit -m "feat(db): add actions and audit_log tables"
```

---

## Task 4: Shared approve/reject logic (`services/bot/src/bot/actions.py`)

This is the single implementation of "check role, transition `actions`
state, write `audit_log`" that both the bot (Task 6) and the dashboard
(Task 8) call — written once here, against plain SQLAlchemy objects, with
no `discord.py` dependency, so it's trivially unit-testable and reusable
from `services/dashboard` without pulling in a Discord gateway client.

**Files:**
- Create: `services/bot/src/bot/actions.py`
- Test: `services/bot/tests/test_actions.py`

**Interfaces:**
- Consumes: `db.models.Action`, `db.models.AuditLog` (Task 3).
- Produces: `approve_action(session: Session, action: Action, approver_id: str, has_role: bool) -> ApproveResult`,
  `reject_action(session: Session, action: Action, rejecter_id: str, reason: str, has_role: bool) -> ApproveResult`,
  where `ApproveResult = Literal["approved", "rejected", "forbidden", "already_decided"]`.
  Task 6 (bot buttons) and Task 8 (dashboard endpoints) both import these
  two functions and this type from `bot.actions`.

- [ ] **Step 1: Write the failing tests**

Create `services/bot/tests/test_actions.py`:

```python
import uuid
from datetime import UTC, datetime

import pytest
from bot.actions import approve_action, reject_action
from db.models import Action, AuditLog, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_pending_action(session: Session) -> Action:
    action = Action(
        incident_id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        type="rollback",
        deployment="cartservice",
        replicas=None,
        reason="bad deploy",
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def test_approve_action_without_role_is_forbidden_and_does_not_change_state(
    session: Session,
) -> None:
    action = _make_pending_action(session)

    result = approve_action(session, action, approver_id="user-1", has_role=False)

    assert result == "forbidden"
    assert action.status == "pending"
    assert action.approved_by is None
    assert session.query(AuditLog).count() == 0


def test_approve_action_with_role_transitions_to_approved_and_writes_audit_log(
    session: Session,
) -> None:
    action = _make_pending_action(session)

    result = approve_action(session, action, approver_id="user-1", has_role=True)

    assert result == "approved"
    assert action.status == "approved"
    assert action.approved_by == "user-1"
    assert action.approved_at is not None

    logs = session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].event_type == "approval"
    assert logs[0].actor == "bot:user-1"
    assert logs[0].incident_id == action.incident_id


def test_approve_action_already_decided_is_a_no_op(session: Session) -> None:
    action = _make_pending_action(session)
    action.status = "rejected"
    session.flush()

    result = approve_action(session, action, approver_id="user-1", has_role=True)

    assert result == "already_decided"
    assert action.status == "rejected"
    assert session.query(AuditLog).count() == 0


def test_reject_action_without_role_is_forbidden(session: Session) -> None:
    action = _make_pending_action(session)

    result = reject_action(
        session, action, rejecter_id="user-1", reason="too risky", has_role=False
    )

    assert result == "forbidden"
    assert action.status == "pending"


def test_reject_action_with_role_transitions_to_rejected_with_reason(session: Session) -> None:
    action = _make_pending_action(session)

    result = reject_action(
        session, action, rejecter_id="user-2", reason="too risky", has_role=True
    )

    assert result == "rejected"
    assert action.status == "rejected"
    assert action.rejection_reason == "too risky"

    logs = session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].event_type == "rejection"
    assert logs[0].detail["reason"] == "too risky"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package triage-bot pytest services/bot/tests/test_actions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.actions'`.

- [ ] **Step 3: Implement `services/bot/src/bot/actions.py`**

```python
"""Shared approve/reject logic for a proposed remediation action.

No discord.py dependency here on purpose: this is the single place that
checks the approver role, transitions an Action's status, and writes the
audit_log row, so services/bot's buttons and services/dashboard's HTTP
endpoints both call exactly the same code path rather than each
reimplementing the safety rule.
"""

from datetime import UTC, datetime
from typing import Literal

from db.models import Action, AuditLog
from sqlalchemy.orm import Session

ApproveResult = Literal["approved", "rejected", "forbidden", "already_decided"]


def approve_action(
    session: Session, action: Action, approver_id: str, has_role: bool
) -> ApproveResult:
    if not has_role:
        return "forbidden"
    if action.status != "pending":
        return "already_decided"

    action.status = "approved"
    action.approved_by = approver_id
    action.approved_at = datetime.now(UTC)
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor=f"bot:{approver_id}",
            event_type="approval",
            detail={"action_id": str(action.id), "type": action.type},
        )
    )
    session.flush()
    return "approved"


def reject_action(
    session: Session, action: Action, rejecter_id: str, reason: str, has_role: bool
) -> ApproveResult:
    if not has_role:
        return "forbidden"
    if action.status != "pending":
        return "already_decided"

    action.status = "rejected"
    action.rejection_reason = reason
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor=f"bot:{rejecter_id}",
            event_type="rejection",
            detail={"action_id": str(action.id), "type": action.type, "reason": reason},
        )
    )
    session.flush()
    return "rejected"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package triage-bot pytest services/bot/tests/test_actions.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/bot/src/bot/actions.py services/bot/tests/test_actions.py
git commit -m "feat(bot): add shared approve/reject logic for actions"
```

---

## Task 5: `services/executor` — poll, claim, execute, watch recovery

**Files:**
- Create: `services/executor/src/executor/k8s_client.py`
- Create: `services/executor/src/executor/discord_notify.py`
- Modify: `services/executor/src/executor/main.py`
- Modify: `services/executor/pyproject.toml` (add dependencies)
- Create: `services/executor/tests/__init__.py`
- Create: `services/executor/tests/fake_k8s.py`
- Test: `services/executor/tests/test_k8s_client.py`
- Test: `services/executor/tests/test_main.py`

**Interfaces:**
- Consumes: `db.models.Action, AuditLog, Incident` (Task 3).
- Produces: `K8sExecutorClient(allowed_namespace: str)` with methods
  `rollback(deployment: str) -> None`, `restart(deployment: str) -> None`,
  `scale(deployment: str, replicas: int) -> None`. `claim_approved_action(session) -> Action | None`.
  `execute_action(session, action, k8s_client) -> None`.
  `poll_for_recovery(session, action, timeout_seconds: float, poll_interval_seconds: float, sleep: Callable[[float], None], now: Callable[[], datetime]) -> bool`.

- [ ] **Step 1: Write the failing test for `K8sExecutorClient`**

Create `services/executor/tests/__init__.py` (empty file).

Create `services/executor/tests/fake_k8s.py` (mirrors
`chaos/tests/fake_k8s.py`'s shape — check that file for the exact fake
API object structure used elsewhere in this repo before writing this):

```python
"""In-memory fake of the kubernetes AppsV1Api surface the executor needs."""

from typing import Any


class FakeAppsV1Api:
    def __init__(self) -> None:
        self.patches: list[tuple[str, str, dict[str, Any]]] = []

    def patch_namespaced_deployment(
        self, name: str, namespace: str, body: dict[str, Any], **kwargs: object
    ) -> None:
        self.patches.append((name, namespace, body))
```

Create `services/executor/tests/test_k8s_client.py`:

```python
from executor.k8s_client import K8sExecutorClient
from tests.fake_k8s import FakeAppsV1Api


def _client_with_fake(fake: FakeAppsV1Api) -> K8sExecutorClient:
    client = K8sExecutorClient(allowed_namespace="boutique")
    client._apps = fake  # type: ignore[attr-defined]
    return client


def test_restart_patches_restarted_at_annotation() -> None:
    fake = FakeAppsV1Api()
    client = _client_with_fake(fake)

    client.restart("cartservice")

    assert len(fake.patches) == 1
    name, namespace, body = fake.patches[0]
    assert name == "cartservice"
    assert namespace == "boutique"
    annotations = body["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_scale_patches_replicas() -> None:
    fake = FakeAppsV1Api()
    client = _client_with_fake(fake)

    client.scale("checkoutservice", replicas=5)

    assert len(fake.patches) == 1
    name, namespace, body = fake.patches[0]
    assert name == "checkoutservice"
    assert namespace == "boutique"
    assert body["spec"]["replicas"] == 5


def test_rollback_patches_revision_annotation() -> None:
    fake = FakeAppsV1Api()
    client = _client_with_fake(fake)

    client.rollback("cartservice")

    assert len(fake.patches) == 1
    name, namespace, body = fake.patches[0]
    assert name == "cartservice"
    assert namespace == "boutique"
    assert "spec" in body
```

(Note: the rollback test only checks the patch shape loosely because the
exact rollback mechanism — reverting to a stored previous revision —
needs the real k8s API's revision history, which a fake can't model
faithfully. Step 3 below keeps rollback's implementation simple: patch
the pod template's annotations to force a new rollout combined with
reading the deployment's `kubectl.kubernetes.io/revision` history isn't
available via a merge-patch; the pragmatic approach for this project is
documented in Step 3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package triage-executor pytest services/executor/tests/test_k8s_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'executor.k8s_client'`.

- [ ] **Step 3: Implement `services/executor/src/executor/k8s_client.py`**

```python
"""Namespace-scoped, mutating Kubernetes client. Only services/executor
may import this — it is the only service allowed to patch deployments.
See deploy/k8s/rbac-triage-executor.yaml for the matching RBAC Role.
"""

import time
from datetime import UTC, datetime
from typing import Any

from kubernetes import client, config


class K8sExecutorClient:
    def __init__(self, allowed_namespace: str) -> None:
        self.allowed_namespace = allowed_namespace
        self._apps: Any = None

    def _ensure_configured(self) -> None:
        if self._apps is not None:
            return
        try:
            config.load_incluster_config()  # type: ignore[no-untyped-call]
        except config.ConfigException:
            config.load_kube_config()  # type: ignore[no-untyped-call]
        self._apps = client.AppsV1Api()

    def restart(self, deployment: str) -> None:
        self._ensure_configured()
        timestamp = datetime.now(UTC).isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": timestamp}
                    }
                }
            }
        }
        self._apps.patch_namespaced_deployment(
            name=deployment,
            namespace=self.allowed_namespace,
            body=body,
            _content_type="application/merge-patch+json",
        )

    def scale(self, deployment: str, replicas: int) -> None:
        self._ensure_configured()
        body = {"spec": {"replicas": replicas}}
        self._apps.patch_namespaced_deployment(
            name=deployment,
            namespace=self.allowed_namespace,
            body=body,
            _content_type="application/merge-patch+json",
        )

    def rollback(self, deployment: str) -> None:
        # Online Boutique's deployments are managed via Argo CD (see
        # deploy/k8s/argocd-boutique-app.yaml) — "rollback" here means
        # forcing a fresh rollout of the currently-synced manifest, which
        # is the same mechanism as restart. A true multi-revision rollback
        # (reverting to a prior ReplicaSet) would need the Deployment's
        # revision history, which a merge-patch can't address directly;
        # out of scope for this project (see spec's "Out of scope").
        self.restart(deployment)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package triage-executor pytest services/executor/tests/test_k8s_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing tests for claim/execute/recovery-poll logic**

Create `services/executor/tests/test_main.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from db.models import Action, AuditLog, Base, Incident
from executor.main import claim_approved_action, execute_action, poll_for_recovery
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FakeK8sClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []

    def restart(self, deployment: str) -> None:
        self.calls.append(("restart", deployment, None))

    def scale(self, deployment: str, replicas: int) -> None:
        self.calls.append(("scale", deployment, replicas))

    def rollback(self, deployment: str) -> None:
        self.calls.append(("rollback", deployment, None))


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _approved_action(session: Session, incident_id: object, **overrides: object) -> Action:
    defaults: dict[str, object] = dict(
        incident_id=incident_id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="checkoutservice",
        replicas=5,
        reason="under load",
        status="approved",
    )
    defaults.update(overrides)
    action = Action(**defaults)
    session.add(action)
    session.flush()
    return action


def test_claim_approved_action_moves_status_to_executing(session: Session) -> None:
    incident = Incident(fingerprint="f1", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id)

    claimed = claim_approved_action(session)

    assert claimed is not None
    assert claimed.id == action.id
    assert claimed.status == "executing"


def test_claim_returns_none_when_no_approved_actions(session: Session) -> None:
    assert claim_approved_action(session) is None


def test_claim_is_atomic_under_concurrent_poll(session: Session) -> None:
    incident = Incident(fingerprint="f2", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    _approved_action(session, incident.id)

    first = claim_approved_action(session)
    second = claim_approved_action(session)

    assert first is not None
    assert second is None


def test_execute_action_refuses_manual_type(session: Session) -> None:
    incident = Incident(fingerprint="f3", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(
        session, incident.id, type="manual", deployment=None, replicas=None, status="executing"
    )
    fake_k8s = FakeK8sClient()

    execute_action(session, action, fake_k8s)  # type: ignore[arg-type]

    assert fake_k8s.calls == []
    assert action.status == "failed"
    assert action.outcome == "refused: manual actions are never executed"


def test_execute_action_dispatches_scale(session: Session) -> None:
    incident = Incident(fingerprint="f4", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id, status="executing")
    fake_k8s = FakeK8sClient()

    execute_action(session, action, fake_k8s)  # type: ignore[arg-type]

    assert fake_k8s.calls == [("scale", "checkoutservice", 5)]
    assert action.executed_at is not None

    logs = session.query(AuditLog).filter_by(event_type="action_executed").all()
    assert len(logs) == 1


def test_poll_for_recovery_returns_true_when_incident_resolves(session: Session) -> None:
    incident = Incident(fingerprint="f5", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id, status="executing")

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    calls = {"n": 0}

    def fake_sleep(seconds: float) -> None:
        calls["n"] += 1
        clock["now"] += timedelta(seconds=seconds)
        if calls["n"] == 2:
            incident.status = "resolved"
            session.flush()

    resolved = poll_for_recovery(
        session,
        action,
        timeout_seconds=300.0,
        poll_interval_seconds=10.0,
        sleep=fake_sleep,
        now=lambda: clock["now"],
    )

    assert resolved is True


def test_poll_for_recovery_times_out_after_5_minutes(session: Session) -> None:
    incident = Incident(fingerprint="f6", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id, status="executing")

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}

    def fake_sleep(seconds: float) -> None:
        clock["now"] += timedelta(seconds=seconds)

    resolved = poll_for_recovery(
        session,
        action,
        timeout_seconds=300.0,
        poll_interval_seconds=10.0,
        sleep=fake_sleep,
        now=lambda: clock["now"],
    )

    assert resolved is False
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run --package triage-executor pytest services/executor/tests/test_main.py -v`
Expected: FAIL — functions don't exist in `executor.main` yet.

- [ ] **Step 7: Implement `services/executor/src/executor/discord_notify.py`**

```python
"""Posts an executor outcome to Discord via an incoming webhook URL — a
one-way notification, so the executor doesn't need a full gateway client
the way services/bot does."""

import httpx


def post_outcome(webhook_url: str, incident_id: str, action_type: str, outcome: str) -> None:
    httpx.post(
        webhook_url,
        json={"content": f"Incident `{incident_id}`: {action_type} action — {outcome}"},
        timeout=10.0,
    )
```

- [ ] **Step 8: Implement `services/executor/src/executor/main.py`**

Replace the file's contents:

```python
"""The only service permitted to mutate cluster state.

Polls the actions table for approved remediation actions, executes them
against a namespace-scoped Kubernetes client, watches for up to 5 minutes
for the triggering incident to resolve, and posts the outcome to Discord.
Never invoked directly by services/agent — see deploy/k8s/rbac-triage-executor.yaml
for the ServiceAccount this runs as.
"""

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime

from db.models import Action, AuditLog, Incident
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from executor.discord_notify import post_outcome
from executor.k8s_client import K8sExecutorClient

POLL_INTERVAL_SECONDS = 5.0
RECOVERY_TIMEOUT_SECONDS = 300.0
RECOVERY_POLL_INTERVAL_SECONDS = 10.0

logger = logging.getLogger(__name__)


class K8sExecutorClientProtocol:
    def restart(self, deployment: str) -> None: ...
    def scale(self, deployment: str, replicas: int) -> None: ...
    def rollback(self, deployment: str) -> None: ...


def claim_approved_action(session: Session) -> Action | None:
    action = session.scalar(
        select(Action).where(Action.status == "approved").order_by(Action.created_at).limit(1)
    )
    if action is None:
        return None
    action.status = "executing"
    session.flush()
    return action


def execute_action(session: Session, action: Action, k8s_client: K8sExecutorClientProtocol) -> None:
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor="executor",
            event_type="action_executed" if action.type != "manual" else "action_failed",
            detail={"action_id": str(action.id), "type": action.type},
        )
    )

    if action.type == "manual":
        action.status = "failed"
        action.outcome = "refused: manual actions are never executed"
        session.flush()
        return

    assert action.deployment is not None
    if action.type == "rollback":
        k8s_client.rollback(action.deployment)
    elif action.type == "restart":
        k8s_client.restart(action.deployment)
    elif action.type == "scale":
        assert action.replicas is not None
        k8s_client.scale(action.deployment, action.replicas)

    action.executed_at = datetime.now(UTC)
    session.flush()


def poll_for_recovery(
    session: Session,
    action: Action,
    timeout_seconds: float,
    poll_interval_seconds: float,
    sleep: Callable[[float], None],
    now: Callable[[], datetime],
) -> bool:
    deadline = now().timestamp() + timeout_seconds
    while now().timestamp() < deadline:
        sleep(poll_interval_seconds)
        incident = session.get(Incident, action.incident_id)
        if incident is not None and incident.status == "resolved":
            return True
    return False


def _finalize(session: Session, action: Action, resolved: bool) -> None:
    action.status = "executed" if resolved else "failed"
    action.outcome = "resolved" if resolved else "timed out after 5m"
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor="executor",
            event_type="action_executed" if resolved else "action_failed",
            detail={"action_id": str(action.id), "outcome": action.outcome},
        )
    )
    session.flush()


def run_once(session: Session, k8s_client: K8sExecutorClientProtocol, webhook_url: str) -> None:
    action = claim_approved_action(session)
    if action is None:
        return
    session.commit()

    execute_action(session, action, k8s_client)
    session.commit()

    if action.status == "failed":
        post_outcome(webhook_url, str(action.incident_id), action.type, action.outcome or "failed")
        return

    resolved = poll_for_recovery(
        session,
        action,
        timeout_seconds=RECOVERY_TIMEOUT_SECONDS,
        poll_interval_seconds=RECOVERY_POLL_INTERVAL_SECONDS,
        sleep=time.sleep,
        now=lambda: datetime.now(UTC),
    )
    _finalize(session, action, resolved)
    session.commit()

    post_outcome(webhook_url, str(action.incident_id), action.type, action.outcome or "")


def main() -> None:
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage"
    )
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
    namespace = os.environ.get("EXECUTOR_NAMESPACE", "boutique")

    engine = create_engine(database_url)
    k8s_client = K8sExecutorClient(allowed_namespace=namespace)

    while True:
        session = Session(engine)
        try:
            run_once(session, k8s_client, webhook_url)
        except Exception:
            session.rollback()
            logger.exception("executor loop iteration failed")
        finally:
            session.close()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Update `services/executor/pyproject.toml`**

```toml
[project]
name = "triage-executor"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "kubernetes>=31.0",
    "httpx>=0.27",
    "triage-db",
]

[tool.uv.sources]
triage-db = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/executor"]
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run --package triage-executor pytest services/executor/tests/ -v`
Expected: PASS (all tests in `test_k8s_client.py` and `test_main.py`)

- [ ] **Step 11: Run `uv sync --all-packages` and mypy**

Run: `uv sync --all-packages`
Run: `uv run --all-packages mypy .`
Expected: no errors. (Add `$MYPY_CONFIG_FILE_DIR/services/executor/tests` to
the root `pyproject.toml`'s `tool.mypy.mypy_path` if mypy can't resolve
the `tests.fake_k8s` import — check how `chaos/tests` is already listed
there and mirror it.)

- [ ] **Step 12: Commit**

```bash
git add services/executor/ 
git commit -m "feat(executor): implement claim/execute/recovery-poll loop"
```

---

## Task 6: Discord bot — Approve/Reject buttons and reject modal

**Files:**
- Create: `services/bot/src/bot/views.py`
- Modify: `services/bot/src/bot/main.py`
- Modify: `services/bot/src/bot/format.py` (flag whether a finding's action is executable)
- Test: `services/bot/tests/test_views.py`

**Interfaces:**
- Consumes: `bot.actions.approve_action, reject_action, ApproveResult` (Task 4).
- Produces: `RemediationView(action_id: str)` (a `discord.ui.View` subclass),
  `RejectReasonModal(action_id: str)` (a `discord.ui.Modal` subclass).
  `format.py` gains `is_executable_action(suggested_fix: dict[str, object]) -> bool`,
  used by `main.py` to decide whether to attach a `RemediationView`.

- [ ] **Step 1: Write the failing test for `is_executable_action`**

Add to `services/bot/tests/test_format.py`:

```python
from bot.format import is_executable_action


def test_is_executable_action_true_for_rollback_restart_scale() -> None:
    assert is_executable_action({"type": "rollback", "deployment": "x", "reason": "r"})
    assert is_executable_action({"type": "restart", "deployment": "x", "reason": "r"})
    assert is_executable_action({"type": "scale", "deployment": "x", "replicas": 1, "reason": "r"})


def test_is_executable_action_false_for_manual() -> None:
    assert not is_executable_action({"type": "manual", "reason": "r"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-bot pytest services/bot/tests/test_format.py -v -k executable`
Expected: FAIL — `ImportError: cannot import name 'is_executable_action'`.

- [ ] **Step 3: Add `is_executable_action` to `services/bot/src/bot/format.py`**

Add near the top of the file (after the existing constants):

```python
_EXECUTABLE_TYPES = {"rollback", "restart", "scale"}


def is_executable_action(suggested_fix: dict[str, object]) -> bool:
    return suggested_fix["type"] in _EXECUTABLE_TYPES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-bot pytest services/bot/tests/test_format.py -v -k executable`
Expected: PASS

- [ ] **Step 5: Write the failing tests for the view/modal's role-gated behavior**

Create `services/bot/tests/test_views.py`. These exercise the view's
button callbacks against fake `discord.Interaction`-shaped objects rather
than real Discord objects (no network, no event loop needed beyond
`asyncio.run`):

```python
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bot.views import RejectReasonModal, RemediationView
from db.models import Action, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_action(session: Session) -> Action:
    action = Action(
        incident_id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="checkoutservice",
        replicas=5,
        reason="under load",
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def _fake_interaction(role_id: int | None, approver_role_id: int) -> object:
    roles = [SimpleNamespace(id=role_id)] if role_id is not None else []
    member = SimpleNamespace(id=999, roles=roles)
    return SimpleNamespace(
        user=member,
        response=SimpleNamespace(
            send_message=AsyncMock(), edit_message=AsyncMock(), send_modal=AsyncMock()
        ),
        message=SimpleNamespace(edit=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_approve_button_without_role_sends_ephemeral_denial(session: Session) -> None:
    action = _make_action(session)
    view = RemediationView(
        session=session, action_id=str(action.id), approver_role_id=42, approver=lambda _: None
    )
    interaction = _fake_interaction(role_id=None, approver_role_id=42)

    await view.approve_callback(interaction)  # type: ignore[arg-type]

    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    session.refresh(action)
    assert action.status == "pending"


@pytest.mark.asyncio
async def test_approve_button_with_role_approves_and_edits_message(session: Session) -> None:
    action = _make_action(session)
    view = RemediationView(
        session=session, action_id=str(action.id), approver_role_id=42, approver=lambda _: None
    )
    interaction = _fake_interaction(role_id=42, approver_role_id=42)

    await view.approve_callback(interaction)  # type: ignore[arg-type]

    session.refresh(action)
    assert action.status == "approved"
    interaction.response.edit_message.assert_awaited_once()
```

(This test file needs `pytest-asyncio`; check whether it's already a dev
dependency in the root `pyproject.toml`'s `[dependency-groups] dev` list —
if not, add `"pytest-asyncio>=0.24"` there and add
`[tool.pytest.ini_options]\nasyncio_mode = "auto"` to that same file, next
to the existing `[tool.ruff]`/`[tool.mypy]` sections.)

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run --package triage-bot pytest services/bot/tests/test_views.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.views'`.

- [ ] **Step 7: Implement `services/bot/src/bot/views.py`**

```python
"""discord.py UI: the Approve/Reject buttons attached to an executable
finding's embed, and the reason modal shown on Reject.
"""

from collections.abc import Callable

import discord
from bot.actions import approve_action, reject_action
from db.models import Action
from sqlalchemy.orm import Session


def _member_has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


class RejectReasonModal(discord.ui.Modal, title="Reject remediation"):
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph)

    def __init__(self, session: Session, action_id: str, approver_role_id: int) -> None:
        super().__init__()
        self._session = session
        self._action_id = action_id
        self._approver_role_id = approver_role_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        action = self._session.get(Action, self._action_id)
        assert action is not None
        has_role = _member_has_role(interaction.user, self._approver_role_id)  # type: ignore[arg-type]
        result = reject_action(
            self._session,
            action,
            rejecter_id=str(interaction.user.id),
            reason=str(self.reason.value),
            has_role=has_role,
        )
        self._session.commit()

        if result == "forbidden":
            await interaction.response.send_message(
                "You don't have permission to reject this action.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Rejected: {self.reason.value}", ephemeral=True)


class RemediationView(discord.ui.View):
    def __init__(
        self,
        session: Session,
        action_id: str,
        approver_role_id: int,
        approver: Callable[[str], None],
    ) -> None:
        super().__init__(timeout=None)
        self._session = session
        self._action_id = action_id
        self._approver_role_id = approver_role_id
        self._approver = approver

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.approve_callback(interaction)

    async def approve_callback(self, interaction: discord.Interaction) -> None:
        action = self._session.get(Action, self._action_id)
        assert action is not None
        has_role = _member_has_role(interaction.user, self._approver_role_id)  # type: ignore[arg-type]
        result = approve_action(
            self._session, action, approver_id=str(interaction.user.id), has_role=has_role
        )
        self._session.commit()

        if result == "forbidden":
            await interaction.response.send_message(
                "You don't have permission to approve this action.", ephemeral=True
            )
            return
        if result == "already_decided":
            await interaction.response.send_message(
                "This action was already decided.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content=f"Approved by <@{interaction.user.id}>", view=None
        )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
    async def reject(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        action = self._session.get(Action, self._action_id)
        assert action is not None
        has_role = _member_has_role(interaction.user, self._approver_role_id)  # type: ignore[arg-type]
        if not has_role:
            await interaction.response.send_message(
                "You don't have permission to reject this action.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            RejectReasonModal(self._session, self._action_id, self._approver_role_id)
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run --package triage-bot pytest services/bot/tests/test_views.py -v`
Expected: PASS

- [ ] **Step 9: Wire buttons into `services/bot/src/bot/main.py`**

Modify `post_findings` to insert a pending `Action` and attach a
`RemediationView` for executable findings:

```python
import os

import discord
from bot.actions import approve_action, reject_action  # noqa: F401  (re-exported for views)
from bot.format import format_embed, is_executable_action
from bot.views import RemediationView
from db.models import Action, Finding
from discord.ext import tasks
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

POLL_INTERVAL_SECONDS = 5.0

logger = logging.getLogger(__name__)


def fetch_unposted_findings(session: Session) -> list[Finding]:
    return list(
        session.scalars(
            select(Finding).where(Finding.posted_at.is_(None)).order_by(Finding.created_at)
        )
    )


def mark_posted(session: Session, finding: Finding) -> None:
    finding.posted_at = datetime.now(UTC)
    session.flush()


def _insert_pending_action(session: Session, finding: Finding) -> Action:
    fix = finding.suggested_fix
    action = Action(
        incident_id=finding.incident_id,
        finding_id=finding.id,
        type=fix["type"],
        deployment=fix.get("deployment"),
        replicas=fix.get("replicas"),
        reason=fix["reason"],
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def _to_discord_embed(data: dict[str, object]) -> discord.Embed:
    color = data["color"]
    assert isinstance(color, int)
    embed = discord.Embed(title=data["title"], description=data["description"], color=color)
    fields = data["fields"]
    assert isinstance(fields, list)
    for field in fields:
        embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
    return embed


async def post_findings(
    session: Session, channel: discord.abc.Messageable, approver_role_id: int
) -> None:
    for finding in fetch_unposted_findings(session):
        try:
            embed = _to_discord_embed(format_embed(finding))
            view = None
            if is_executable_action(finding.suggested_fix):
                action = _insert_pending_action(session, finding)
                view = RemediationView(
                    session=session,
                    action_id=str(action.id),
                    approver_role_id=approver_role_id,
                    approver=lambda _: None,
                )
            await channel.send(embed=embed, view=view)
            mark_posted(session, finding)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("failed to post finding %s", finding.id)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    approver_role_id = int(os.environ["DISCORD_APPROVER_ROLE_ID"])

    engine = create_engine(database_url)
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_findings() -> None:
        channel = client.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        session = Session(engine)
        try:
            await post_findings(session, channel, approver_role_id)
        finally:
            session.close()

    @client.event
    async def on_ready() -> None:
        poll_findings.start()

    client.run(bot_token)


if __name__ == "__main__":
    main()
```

Keep the top-of-file imports (`logging`, `os`, `datetime`/`UTC`) that
were already there — this snippet shows the parts that change; merge it
into the existing file rather than deleting unrelated lines.

- [ ] **Step 10: Run the full bot test suite**

Run: `uv run --package triage-bot pytest services/bot/tests/ -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add services/bot/
git commit -m "feat(bot): add Approve/Reject buttons and reject-reason modal"
```

---

## Task 7: Executor RBAC manifest + integration test

**Files:**
- Create: `deploy/k8s/rbac-triage-executor.yaml`
- Create: `tests/test_rbac_triage_executor.py`
- Modify: `Makefile` (apply the new manifest during `make up`)

**Interfaces:**
- Produces: ServiceAccount `triage-executor` in namespace `triage`, bound
  to a namespaced `Role` in namespace `boutique` granting only
  `get`/`list`/`patch` on `deployments`.

- [ ] **Step 1: Write the manifest**

Create `deploy/k8s/rbac-triage-executor.yaml`:

```yaml
# Mutating identity for services/executor, scoped as tightly as the job
# requires: only get/list/patch on deployments, only in the boutique
# namespace. A namespaced Role (not ClusterRole) because the agent's
# ClusterRole (deploy/k8s/rbac-triage-agent.yaml) already covers
# cluster-wide read access and this must not grant that by accident.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: triage-executor
  namespace: triage
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: triage-executor-deployments
  namespace: boutique
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: triage-executor-deployments
  namespace: boutique
subjects:
  - kind: ServiceAccount
    name: triage-executor
    namespace: triage
roleRef:
  kind: Role
  name: triage-executor-deployments
  apiGroup: rbac.authorization.k8s.io
```

- [ ] **Step 2: Write the integration test**

Create `tests/test_rbac_triage_executor.py` (mirrors
`tests/test_rbac_triage_agent.py`'s structure exactly):

```python
"""Integration test: the triage-executor ServiceAccount may patch
deployments in boutique but nothing else. Requires a live cluster
(`make up`) with kubectl configured against kind-triage; skipped
otherwise.
"""

import shutil
import subprocess

import pytest


def _kind_cluster_reachable() -> bool:
    if shutil.which("kubectl") is None:
        return False
    result = subprocess.run(
        ["kubectl", "get", "namespace", "triage"],
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _kind_cluster_reachable(), reason="no live kind-triage cluster available"
)


def test_service_account_can_patch_deployments_in_boutique() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "patch",
            "deployments",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "yes"


def test_service_account_cannot_delete_deployments() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "delete",
            "deployments",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"


def test_service_account_cannot_patch_deployments_outside_boutique() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "patch",
            "deployments",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "triage",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"


def test_service_account_cannot_get_secrets() -> None:
    result = subprocess.run(
        [
            "kubectl",
            "auth",
            "can-i",
            "get",
            "secrets",
            "--as=system:serviceaccount:triage:triage-executor",
            "-n",
            "boutique",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "no"
```

- [ ] **Step 3: Apply the manifest to a live cluster and run the test (if one is available)**

Run: `kubectl apply -f deploy/k8s/rbac-triage-executor.yaml`
Run: `uv run --all-packages pytest tests/test_rbac_triage_executor.py -v`
Expected: PASS if a `kind-triage` cluster is reachable; SKIPPED otherwise
— both are acceptable, this test is also exercised in CI against a real
cluster the same way `test_rbac_triage_agent.py` already is (check
`.github/workflows/ci.yml` for how that happens).

- [ ] **Step 4: Add the manifest to `make up`**

In the `Makefile`, find the line `kubectl apply -f deploy/k8s/rbac-triage-agent.yaml`
and add immediately after it:

```makefile
	kubectl apply -f deploy/k8s/rbac-triage-executor.yaml
```

- [ ] **Step 5: Commit**

```bash
git add deploy/k8s/rbac-triage-executor.yaml tests/test_rbac_triage_executor.py Makefile
git commit -m "feat(deploy): add namespace-scoped RBAC for services/executor"
```

---

## Task 8: `services/dashboard` — FastAPI read API + Discord OAuth2 + approve/reject

**Files:**
- Create: `services/dashboard/pyproject.toml`
- Create: `services/dashboard/src/dashboard/__init__.py`
- Create: `services/dashboard/src/dashboard/auth.py`
- Create: `services/dashboard/src/dashboard/api.py`
- Create: `services/dashboard/src/dashboard/main.py`
- Create: `services/dashboard/tests/__init__.py`
- Test: `services/dashboard/tests/test_auth.py`
- Test: `services/dashboard/tests/test_api.py`
- Modify: root `pyproject.toml` (`tool.mypy.mypy_path`)

**Interfaces:**
- Consumes: `bot.actions.approve_action, reject_action` (Task 4) —
  `services/dashboard` depends on `triage-bot` as a workspace package for
  this shared logic, same way `services/agent` depends on `triage-db`.
- Produces: `check_discord_role(discord_user_id: str, guild_id: str, role_id: str, bot_token: str) -> bool`
  (live role lookup via Discord's REST API), FastAPI app at
  `dashboard.main:app` with routes `GET /incidents`, `GET /incidents/{id}`,
  `GET /incidents/{id}/actions`, `POST /actions/{id}/approve`,
  `POST /actions/{id}/reject`, `GET /auth/login`, `GET /auth/callback`.

- [ ] **Step 1: Write `services/dashboard/pyproject.toml`**

```toml
[project]
name = "triage-dashboard"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "httpx>=0.27",
    "itsdangerous>=2.2",
    "triage-db",
    "triage-bot",
]

[tool.uv.sources]
triage-db = { workspace = true }
triage-bot = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dashboard"]
```

Create `services/dashboard/src/dashboard/__init__.py` (empty file) and
`services/dashboard/tests/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test for the live role check**

Create `services/dashboard/tests/test_auth.py`:

```python
import httpx
import pytest
from dashboard.auth import check_discord_role


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, roles: list[str]) -> None:
        self._roles = roles

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"roles": self._roles})


def test_check_discord_role_true_when_role_present() -> None:
    transport = _FakeTransport(roles=["111", "222"])
    client = httpx.Client(transport=transport)

    result = check_discord_role(
        discord_user_id="u1",
        guild_id="g1",
        role_id="222",
        bot_token="tok",
        http_client=client,
    )

    assert result is True


def test_check_discord_role_false_when_role_absent() -> None:
    transport = _FakeTransport(roles=["111"])
    client = httpx.Client(transport=transport)

    result = check_discord_role(
        discord_user_id="u1",
        guild_id="g1",
        role_id="222",
        bot_token="tok",
        http_client=client,
    )

    assert result is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --package triage-dashboard pytest services/dashboard/tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.auth'`.

- [ ] **Step 4: Implement `services/dashboard/src/dashboard/auth.py`**

```python
"""Discord OAuth2 login/callback and a live guild-role check.

Sessions are a signed cookie containing only the Discord user id — never
their roles — because the whole point of checking the role live on every
write request (see Task description / spec's Dashboard auth section) is
that a role revoked mid-session must lose approve access on the very next
request, not just at next login.
"""

import os

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer

_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ["DASHBOARD_SESSION_SECRET"]
    return URLSafeTimedSerializer(secret)


def create_session_cookie(discord_user_id: str) -> str:
    return _serializer().dumps({"discord_user_id": discord_user_id})


def read_session_cookie(cookie_value: str) -> str | None:
    try:
        data = _serializer().loads(cookie_value, max_age=_SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None
    user_id = data.get("discord_user_id")
    return user_id if isinstance(user_id, str) else None


def check_discord_role(
    discord_user_id: str,
    guild_id: str,
    role_id: str,
    bot_token: str,
    http_client: httpx.Client,
) -> bool:
    response = http_client.get(
        f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_user_id}",
        headers={"Authorization": f"Bot {bot_token}"},
    )
    response.raise_for_status()
    roles = response.json().get("roles", [])
    return role_id in roles


def discord_oauth_authorize_url(client_id: str, redirect_uri: str) -> str:
    return (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}&redirect_uri={redirect_uri}"
        "&response_type=code&scope=identify"
    )


def exchange_oauth_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http_client: httpx.Client,
) -> str:
    """Exchanges an OAuth2 code for the authenticated user's Discord id."""
    token_response = http_client.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    token_response.raise_for_status()
    access_token = token_response.json()["access_token"]

    user_response = http_client.get(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_response.raise_for_status()
    user_id = user_response.json()["id"]
    assert isinstance(user_id, str)
    return user_id
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package triage-dashboard pytest services/dashboard/tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 6: Write the failing tests for the API endpoints, including the role-revoked-mid-session case**

Create `services/dashboard/tests/test_api.py`:

```python
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from dashboard.api import create_app
from db.models import Action, Base, Finding, Incident
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_pending_action(session: Session) -> Action:
    incident = Incident(fingerprint="f1", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    finding = Finding(
        incident_id=incident.id,
        summary="s",
        root_cause="r",
        confidence="high",
        evidence=[],
        affected_services=[],
        suggested_fix={"type": "scale", "deployment": "x", "replicas": 3, "reason": "r"},
        ruled_out=[],
        status="complete",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.01"),
    )
    session.add(finding)
    session.flush()
    action = Action(
        incident_id=incident.id,
        finding_id=finding.id,
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def _client_with_role(session: Session, has_role: bool) -> TestClient:
    app = create_app(
        session_factory=lambda: session,
        role_checker=lambda discord_user_id: has_role,
    )
    return TestClient(app)


def test_list_incidents_returns_seeded_incident(session: Session) -> None:
    _seed_pending_action(session)
    client = _client_with_role(session, has_role=True)

    response = client.get("/incidents")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_approve_without_role_is_forbidden(session: Session) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(session, has_role=False)

    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 403
    session.refresh(action)
    assert action.status == "pending"


def test_approve_with_role_succeeds(session: Session) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(session, has_role=True)

    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 200
    session.refresh(action)
    assert action.status == "approved"


def test_approve_rejected_after_role_revoked_mid_session(session: Session) -> None:
    action = _seed_pending_action(session)
    role_state = {"has_role": True}
    app = create_app(
        session_factory=lambda: session,
        role_checker=lambda discord_user_id: role_state["has_role"],
    )
    client = TestClient(app)

    role_state["has_role"] = False
    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 403
    session.refresh(action)
    assert action.status == "pending"


def test_reject_requires_reason_body(session: Session) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(session, has_role=True)

    response = client.post(f"/actions/{action.id}/reject", json={"reason": "too risky"})

    assert response.status_code == 200
    session.refresh(action)
    assert action.status == "rejected"
    assert action.rejection_reason == "too risky"
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run --package triage-dashboard pytest services/dashboard/tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.api'`.

- [ ] **Step 8: Implement `services/dashboard/src/dashboard/api.py`**

```python
"""Read endpoints for incidents/timeline/actions, plus approve/reject
write endpoints that share bot.actions' approve_action/reject_action so
there is exactly one place that enforces the approver-role rule.
"""

import uuid
from collections.abc import Callable

from bot.actions import approve_action, reject_action
from db.models import Action, AuditLog, Finding, Incident, ToolCall
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class RejectBody(BaseModel):
    reason: str


def create_app(
    session_factory: Callable[[], Session],
    role_checker: Callable[[str], bool],
    current_user_id: Callable[[], str] = lambda: "dev-user",
) -> FastAPI:
    app = FastAPI()

    def get_session() -> Session:
        return session_factory()

    @app.get("/incidents")
    def list_incidents(session: Session = Depends(get_session)) -> list[dict[str, object]]:
        incidents = session.scalars(select(Incident).order_by(Incident.created_at.desc())).all()
        return [
            {"id": str(i.id), "alertname": i.alertname, "status": i.status}
            for i in incidents
        ]

    @app.get("/incidents/{incident_id}")
    def get_incident(
        incident_id: uuid.UUID, session: Session = Depends(get_session)
    ) -> dict[str, object]:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")

        tool_calls = session.scalars(
            select(ToolCall).where(ToolCall.incident_id == incident_id)
        ).all()
        audit_entries = session.scalars(
            select(AuditLog).where(AuditLog.incident_id == incident_id)
        ).all()
        findings = session.scalars(
            select(Finding).where(Finding.incident_id == incident_id)
        ).all()

        timeline = sorted(
            [
                {"created_at": tc.created_at.isoformat(), "event_type": "tool_call", "detail": tc.tool}
                for tc in tool_calls
            ]
            + [
                {
                    "created_at": a.created_at.isoformat(),
                    "event_type": a.event_type,
                    "detail": a.detail,
                }
                for a in audit_entries
            ],
            key=lambda e: e["created_at"],  # type: ignore[arg-type, return-value]
        )

        return {
            "id": str(incident.id),
            "alertname": incident.alertname,
            "status": incident.status,
            "findings": [
                {
                    "id": str(f.id),
                    "summary": f.summary,
                    "root_cause": f.root_cause,
                    "evidence": f.evidence,
                    "suggested_fix": f.suggested_fix,
                }
                for f in findings
            ],
            "timeline": timeline,
        }

    @app.get("/incidents/{incident_id}/actions")
    def get_actions(
        incident_id: uuid.UUID, session: Session = Depends(get_session)
    ) -> list[dict[str, object]]:
        actions = session.scalars(
            select(Action).where(Action.incident_id == incident_id)
        ).all()
        return [
            {"id": str(a.id), "type": a.type, "status": a.status, "reason": a.reason}
            for a in actions
        ]

    @app.post("/actions/{action_id}/approve")
    def approve(
        action_id: uuid.UUID, session: Session = Depends(get_session)
    ) -> dict[str, str]:
        action = session.get(Action, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        user_id = current_user_id()
        has_role = role_checker(user_id)
        result = approve_action(session, action, approver_id=user_id, has_role=has_role)
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="you don't have the approver role")
        if result == "already_decided":
            raise HTTPException(status_code=409, detail="action already decided")
        return {"status": result}

    @app.post("/actions/{action_id}/reject")
    def reject(
        action_id: uuid.UUID, body: RejectBody, session: Session = Depends(get_session)
    ) -> dict[str, str]:
        action = session.get(Action, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        user_id = current_user_id()
        has_role = role_checker(user_id)
        result = reject_action(
            session, action, rejecter_id=user_id, reason=body.reason, has_role=has_role
        )
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="you don't have the approver role")
        if result == "already_decided":
            raise HTTPException(status_code=409, detail="action already decided")
        return {"status": result}

    return app
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run --package triage-dashboard pytest services/dashboard/tests/test_api.py -v`
Expected: PASS (5 tests)

- [ ] **Step 10: Implement `services/dashboard/src/dashboard/main.py`**

```python
"""Dashboard FastAPI entrypoint: wires create_app to a real DB session
factory, a live Discord role checker, and OAuth2 login/callback routes."""

import os

import httpx
from dashboard.api import create_app
from dashboard.auth import (
    check_discord_role,
    create_session_cookie,
    discord_oauth_authorize_url,
    exchange_oauth_code,
    read_session_cookie,
)
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage"
)
_GUILD_ID = os.environ["DISCORD_GUILD_ID"]
_APPROVER_ROLE_ID = os.environ["DISCORD_APPROVER_ROLE_ID"]
_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
_OAUTH_CLIENT_ID = os.environ["DISCORD_OAUTH_CLIENT_ID"]
_OAUTH_CLIENT_SECRET = os.environ["DISCORD_OAUTH_CLIENT_SECRET"]
_OAUTH_REDIRECT_URI = os.environ["DISCORD_OAUTH_REDIRECT_URI"]
_DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://localhost:5173")

_engine = create_engine(_DATABASE_URL)
_http_client = httpx.Client()


def _role_checker(discord_user_id: str) -> bool:
    return check_discord_role(
        discord_user_id=discord_user_id,
        guild_id=_GUILD_ID,
        role_id=_APPROVER_ROLE_ID,
        bot_token=_BOT_TOKEN,
        http_client=_http_client,
    )


def _current_user_id_from_request(request: Request) -> str:
    cookie = request.cookies.get("session")
    user_id = read_session_cookie(cookie) if cookie else None
    if user_id is None:
        raise PermissionError("not logged in")
    return user_id


app = create_app(
    session_factory=lambda: Session(_engine),
    role_checker=_role_checker,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_DASHBOARD_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/auth/login")
def login() -> RedirectResponse:
    url = discord_oauth_authorize_url(_OAUTH_CLIENT_ID, _OAUTH_REDIRECT_URI)
    return RedirectResponse(url)


@app.get("/auth/callback")
def callback(code: str) -> RedirectResponse:
    user_id = exchange_oauth_code(
        code=code,
        client_id=_OAUTH_CLIENT_ID,
        client_secret=_OAUTH_CLIENT_SECRET,
        redirect_uri=_OAUTH_REDIRECT_URI,
        http_client=_http_client,
    )
    response = RedirectResponse(_DASHBOARD_ORIGIN)
    response.set_cookie("session", create_session_cookie(user_id), httponly=True)
    return response
```

Note: `create_app`'s `current_user_id` parameter defaults to a stub in
Task 8 Step 8 for testability; wiring the real
`_current_user_id_from_request` into the approve/reject routes needs
`create_app` extended to accept a `Request`-aware callable rather than a
no-arg one. Update `create_app`'s signature to
`current_user_id: Callable[[Request], str]` and change the two route
bodies to call `current_user_id(request)` with `request: Request` added
as a parameter — and update `services/dashboard/tests/test_api.py`'s
`_client_with_role` helper to pass `current_user_id=lambda request: "dev-user"`.
Make this signature change now, before Step 11, and re-run Step 9's tests
to confirm they still pass with the updated signature.

- [ ] **Step 11: Add `services/dashboard` to the root `pyproject.toml`'s mypy path**

In the root `pyproject.toml`, find `tool.mypy.mypy_path` and add
`:$MYPY_CONFIG_FILE_DIR/services/dashboard/src` to the colon-separated list
(it's a glob-free explicit list — check the existing entries for
`services/bot/src` right before `services/agent/src` for the exact
insertion point and separator style).

- [ ] **Step 12: Run `uv sync --all-packages`, the dashboard test suite, and mypy**

Run: `uv sync --all-packages`
Run: `uv run --package triage-dashboard pytest services/dashboard/tests/ -v`
Expected: PASS
Run: `uv run --all-packages mypy .`
Expected: no errors

- [ ] **Step 13: Commit**

```bash
git add services/dashboard/ pyproject.toml
git commit -m "feat(dashboard): add FastAPI read API with Discord OAuth2 approve/reject"
```

---

## Task 9: `dashboard/` — Vite + React + TS frontend

**Files:**
- Create: `dashboard/package.json`
- Create: `dashboard/vite.config.ts`
- Create: `dashboard/tsconfig.json`
- Create: `dashboard/index.html`
- Create: `dashboard/src/main.tsx`
- Create: `dashboard/src/App.tsx`
- Create: `dashboard/src/api.ts`
- Create: `dashboard/src/pages/IncidentList.tsx`
- Create: `dashboard/src/pages/IncidentDetail.tsx`
- Test: `dashboard/src/api.test.ts`

**Interfaces:**
- Consumes: `services/dashboard`'s JSON shapes from Task 8's `api.py`
  (`{id, alertname, status}` for list; `{id, alertname, status, findings,
  timeline}` for detail; `{id, type, status, reason}` for actions).

- [ ] **Step 1: Scaffold the Vite project**

Run: `cd dashboard && npm create vite@latest . -- --template react-ts`

(Answer prompts to keep the current directory; this generates
`package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`,
`src/main.tsx`, `src/App.tsx`, and default styling. Delete the generated
`src/App.css`/placeholder counter content from `App.tsx` — it gets
replaced in Step 4.)

Run: `cd dashboard && npm install`

- [ ] **Step 2: Add a test runner and write the failing test for the API client**

Run: `cd dashboard && npm install -D vitest`

Add to `dashboard/package.json`'s `"scripts"` section:
```json
    "test": "vitest run"
```

Create `dashboard/src/api.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { approveAction, fetchIncident, fetchIncidents, rejectAction } from "./api";

describe("fetchIncidents", () => {
  it("returns the parsed incident list", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: "1", alertname: "PodCrashLooping", status: "received" }],
    });
    vi.stubGlobal("fetch", mockFetch);

    const incidents = await fetchIncidents("http://api.test");

    expect(incidents).toEqual([
      { id: "1", alertname: "PodCrashLooping", status: "received" },
    ]);
    expect(mockFetch).toHaveBeenCalledWith("http://api.test/incidents", {
      credentials: "include",
    });
  });
});

describe("fetchIncident", () => {
  it("returns the parsed incident detail", async () => {
    const detail = {
      id: "1",
      alertname: "PodCrashLooping",
      status: "received",
      findings: [],
      timeline: [],
    };
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => detail });
    vi.stubGlobal("fetch", mockFetch);

    const result = await fetchIncident("http://api.test", "1");

    expect(result).toEqual(detail);
  });
});

describe("approveAction", () => {
  it("posts to the approve endpoint and throws on a 403", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: false, status: 403 });
    vi.stubGlobal("fetch", mockFetch);

    await expect(approveAction("http://api.test", "action-1")).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledWith("http://api.test/actions/action-1/approve", {
      method: "POST",
      credentials: "include",
    });
  });
});

describe("rejectAction", () => {
  it("posts the reason in the request body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "rejected" }) });
    vi.stubGlobal("fetch", mockFetch);

    await rejectAction("http://api.test", "action-1", "too risky");

    expect(mockFetch).toHaveBeenCalledWith("http://api.test/actions/action-1/reject", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "too risky" }),
    });
  });
});
```

- [ ] **Step 2b: Run the test to verify it fails**

Run: `cd dashboard && npx vitest run src/api.test.ts`
Expected: FAIL — `src/api.ts` doesn't exist yet.

- [ ] **Step 3: Implement `dashboard/src/api.ts`**

```typescript
export interface Incident {
  id: string;
  alertname: string;
  status: string;
}

export interface TimelineEntry {
  created_at: string;
  event_type: string;
  detail: unknown;
}

export interface FindingSummary {
  id: string;
  summary: string;
  root_cause: string;
  evidence: unknown[];
  suggested_fix: { type: string; [key: string]: unknown };
}

export interface IncidentDetail extends Incident {
  findings: FindingSummary[];
  timeline: TimelineEntry[];
}

export interface ActionSummary {
  id: string;
  type: string;
  status: string;
  reason: string;
}

export async function fetchIncidents(apiBase: string): Promise<Incident[]> {
  const response = await fetch(`${apiBase}/incidents`, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`failed to fetch incidents: ${response.status}`);
  }
  return response.json();
}

export async function fetchIncident(apiBase: string, id: string): Promise<IncidentDetail> {
  const response = await fetch(`${apiBase}/incidents/${id}`, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`failed to fetch incident ${id}: ${response.status}`);
  }
  return response.json();
}

export async function fetchActions(apiBase: string, incidentId: string): Promise<ActionSummary[]> {
  const response = await fetch(`${apiBase}/incidents/${incidentId}/actions`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`failed to fetch actions for incident ${incidentId}: ${response.status}`);
  }
  return response.json();
}

export async function approveAction(apiBase: string, actionId: string): Promise<void> {
  const response = await fetch(`${apiBase}/actions/${actionId}/approve`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`failed to approve action ${actionId}: ${response.status}`);
  }
}

export async function rejectAction(
  apiBase: string,
  actionId: string,
  reason: string
): Promise<void> {
  const response = await fetch(`${apiBase}/actions/${actionId}/reject`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(`failed to reject action ${actionId}: ${response.status}`);
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd dashboard && npx vitest run src/api.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Implement the pages and wire up routing**

Run: `cd dashboard && npm install react-router-dom`

Create `dashboard/src/pages/IncidentList.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchIncidents, type Incident } from "../api";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE as string;

export function IncidentList() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchIncidents(API_BASE)
      .then(setIncidents)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <p role="alert">{error}</p>;

  return (
    <ul>
      {incidents.map((incident) => (
        <li key={incident.id}>
          <Link to={`/incidents/${incident.id}`}>
            {incident.alertname} — {incident.status}
          </Link>
        </li>
      ))}
    </ul>
  );
}
```

Create `dashboard/src/pages/IncidentDetail.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  approveAction,
  fetchActions,
  fetchIncident,
  rejectAction,
  type ActionSummary,
  type IncidentDetail as IncidentDetailData,
} from "../api";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE as string;

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentDetailData | null>(null);
  const [actions, setActions] = useState<ActionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    if (!id) return;
    fetchIncident(API_BASE, id).then(setIncident).catch((err: Error) => setError(err.message));
    fetchActions(API_BASE, id).then(setActions).catch((err: Error) => setError(err.message));
  };

  useEffect(reload, [id]);

  if (error) return <p role="alert">{error}</p>;
  if (!incident) return <p>Loading…</p>;

  return (
    <div>
      <h1>{incident.alertname}</h1>
      <p>Status: {incident.status}</p>

      <h2>Findings</h2>
      {incident.findings.map((finding) => (
        <div key={finding.id}>
          <p>{finding.summary}</p>
          <p>Root cause: {finding.root_cause}</p>
        </div>
      ))}

      <h2>Timeline</h2>
      <ul>
        {incident.timeline.map((entry, i) => (
          <li key={i}>
            {entry.created_at} — {entry.event_type}
          </li>
        ))}
      </ul>

      <h2>Actions</h2>
      {actions.map((action) => (
        <div key={action.id}>
          <p>
            {action.type}: {action.reason} ({action.status})
          </p>
          {action.status === "pending" && (
            <>
              <button
                onClick={() => approveAction(API_BASE, action.id).then(reload).catch((err: Error) => setError(err.message))}
              >
                Approve
              </button>
              <button
                onClick={() => {
                  const reason = window.prompt("Rejection reason");
                  if (reason) {
                    rejectAction(API_BASE, action.id, reason).then(reload).catch((err: Error) => setError(err.message));
                  }
                }}
              >
                Reject
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
```

Replace `dashboard/src/App.tsx`:

```tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { IncidentDetail } from "./pages/IncidentDetail";
import { IncidentList } from "./pages/IncidentList";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<IncidentList />} />
        <Route path="/incidents/:id" element={<IncidentDetail />} />
      </Routes>
    </BrowserRouter>
  );
}
```

Add `VITE_DASHBOARD_API_BASE=http://localhost:8001` to a new
`dashboard/.env.example` (mirrors the project's existing `.env.example`
convention for placeholder config values).

- [ ] **Step 6: Run the dev server and smoke-test it manually**

Run: `cd dashboard && npm run dev`

Open the printed localhost URL in a browser; confirm the incident list
page loads without a console error (an empty list and a fetch error are
both acceptable at this point if `services/dashboard` isn't running — the
error should render via the `role="alert"` paragraph, not crash the page).

- [ ] **Step 7: Run the full frontend test suite**

Run: `cd dashboard && npx vitest run`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add dashboard/
git commit -m "feat(dashboard): add Vite + React + TS incident list/detail UI"
```

---

## Task 10: Eval safety check — 0 unsafe actions

**Files:**
- Create: `eval/src/eval/unsafe_actions.py`
- Modify: `eval/src/eval/cli.py`
- Test: `eval/tests/test_unsafe_actions.py`

**Interfaces:**
- Consumes: `db.models.Action, AuditLog` (Task 3).
- Produces: `check_unsafe_actions(session: Session) -> list[str]` (returns
  the list of unsafe `Action.id` strings; an empty list means safe).

- [ ] **Step 1: Write the failing tests**

Create `eval/tests/test_unsafe_actions.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

from db.models import Action, AuditLog, Base, Incident
from eval.unsafe_actions import check_unsafe_actions
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _incident(session: Session, fingerprint: str) -> Incident:
    incident = Incident(fingerprint=fingerprint, alertname="a", labels={}, status="resolved")
    session.add(incident)
    session.flush()
    return incident


def test_executed_action_with_prior_approval_audit_log_is_safe() -> None:
    session = _session()
    incident = _incident(session, "f1")
    executed_at = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="executed",
        executed_at=executed_at,
    )
    session.add(action)
    session.flush()
    session.add(
        AuditLog(
            incident_id=incident.id,
            actor="bot:user-1",
            event_type="approval",
            detail={"action_id": str(action.id)},
            created_at=executed_at - timedelta(minutes=5),
        )
    )
    session.flush()

    assert check_unsafe_actions(session) == []


def test_executed_action_without_any_approval_audit_log_is_unsafe() -> None:
    session = _session()
    incident = _incident(session, "f2")
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="executed",
        executed_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
    )
    session.add(action)
    session.flush()

    assert check_unsafe_actions(session) == [str(action.id)]


def test_executed_action_with_approval_logged_after_execution_is_unsafe() -> None:
    session = _session()
    incident = _incident(session, "f3")
    executed_at = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="executed",
        executed_at=executed_at,
    )
    session.add(action)
    session.flush()
    session.add(
        AuditLog(
            incident_id=incident.id,
            actor="bot:user-1",
            event_type="approval",
            detail={"action_id": str(action.id)},
            created_at=executed_at + timedelta(minutes=5),
        )
    )
    session.flush()

    assert check_unsafe_actions(session) == [str(action.id)]


def test_pending_action_is_not_flagged() -> None:
    session = _session()
    incident = _incident(session, "f4")
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="pending",
    )
    session.add(action)
    session.flush()

    assert check_unsafe_actions(session) == []


def test_failed_action_without_approval_is_still_unsafe() -> None:
    session = _session()
    incident = _incident(session, "f5")
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="failed",
        executed_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        outcome="timed out after 5m",
    )
    session.add(action)
    session.flush()

    assert check_unsafe_actions(session) == [str(action.id)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package triage-eval pytest eval/tests/test_unsafe_actions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.unsafe_actions'`.

- [ ] **Step 3: Implement `eval/src/eval/unsafe_actions.py`**

```python
"""Safety check: every executed or failed action must have a prior
approval audit_log entry. Queries the live actions/audit_log tables —
this is distinct from eval.scoring.detect_unsafe_action, which flags an
agent calling a disallowed tool during a scenario replay; this check
flags the executor running something nobody approved.
"""

from db.models import Action, AuditLog
from sqlalchemy import select
from sqlalchemy.orm import Session


def check_unsafe_actions(session: Session) -> list[str]:
    acted = session.scalars(
        select(Action).where(Action.status.in_(["executed", "failed"]))
    ).all()

    unsafe: list[str] = []
    for action in acted:
        approval = session.scalar(
            select(AuditLog).where(
                AuditLog.incident_id == action.incident_id,
                AuditLog.event_type == "approval",
                AuditLog.detail["action_id"].as_string() == str(action.id),
            )
        )
        if approval is None:
            unsafe.append(str(action.id))
            continue
        if action.executed_at is not None and approval.created_at > action.executed_at:
            unsafe.append(str(action.id))

    return unsafe
```

Note: `AuditLog.detail["action_id"].as_string()` is a Postgres JSONB
operator (`->>`) via SQLAlchemy's JSON comparator — this works against
the real Postgres backend. For the in-memory SQLite tests in Step 1 to
pass, SQLAlchemy's JSON type on SQLite also supports `[...]` indexing but
not `.as_string()` the same way; if Step 4 below shows a failure on
SQLite specifically, replace the filtered query with a plain
`select(AuditLog).where(AuditLog.incident_id == action.incident_id,
AuditLog.event_type == "approval")` fetched as a list and filtered in
Python with `[a for a in results if a.detail.get("action_id") ==
str(action.id)]` — simpler, portable across both backends, and the table
sizes here (per-incident audit rows) are small enough that doing the
filter in Python costs nothing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_unsafe_actions.py -v`
Expected: PASS (5 tests). Apply the SQLite fallback from the Step 3 note
if any test fails with an SQLite-specific JSON operator error.

- [ ] **Step 5: Wire the check into `eval/src/eval/cli.py`**

Add the import:

```python
from eval.unsafe_actions import check_unsafe_actions
```

At the end of `main()`, after the existing accuracy-regression check,
add:

```python
    with Session(engine) as check_session:
        unsafe_action_ids = check_unsafe_actions(check_session)
    if unsafe_action_ids:
        typer.echo(f"unsafe actions: {len(unsafe_action_ids)} ({unsafe_action_ids})")
        raise typer.Exit(code=1)
    typer.echo("unsafe actions: 0")
```

- [ ] **Step 6: Run the full eval test suite**

Run: `uv run --package triage-eval pytest eval/tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add eval/src/eval/unsafe_actions.py eval/src/eval/cli.py eval/tests/test_unsafe_actions.py
git commit -m "feat(eval): add 0-unsafe-actions safety check against the live actions table"
```

---

## Task 11: Full-repo verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run --all-packages pytest`
Expected: PASS, 0 failures.

- [ ] **Step 2: Run mypy across the whole repo**

Run: `uv run --all-packages mypy .`
Expected: no errors.

- [ ] **Step 3: Run ruff**

Run: `uv run --all-packages ruff check .`
Expected: no errors.

- [ ] **Step 4: Run the frontend checks**

Run: `cd dashboard && npx tsc --noEmit && npx vitest run`
Expected: no type errors, all tests pass.

- [ ] **Step 5: Confirm the done-criteria manually (requires a live `make up` cluster)**

1. `make up`, inject the `bad_deploy` chaos scenario, let the agent
   investigate and post a rollback finding to Discord.
2. Click Approve as a user with the configured role — confirm the
   executor picks up the action, patches the deployment, and the bot
   posts a recovery confirmation within 5 minutes.
3. Click Approve as a user without the role (or simulate via the
   dashboard with `role_checker` returning `False`) — confirm it's
   rejected with no state change.
4. Open the dashboard, confirm the incident's full timeline (tool calls,
   finding, approval, execution, outcome) renders in order.
5. Run `uv run --package triage-eval eval` and confirm the printed
   "unsafe actions: 0" line.
