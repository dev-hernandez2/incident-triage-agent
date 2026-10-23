# Human-approved remediation — design

## Goal

Turn the agent's free-text `suggested_fix` into a typed remediation action
that a human can approve or reject in Discord (or the new dashboard), and
that only `services/executor` is permitted to run — never automatically,
never from `services/agent`. Every tool call, model call, approval,
rejection, and executed action must be auditable, and an eval check must
prove no action ever runs without a recorded approval.

## Scope

One spec, phased implementation plan. Six pieces, built roughly in this
order since each depends on the previous one's data model:

1. Typed action schema (`Finding.suggested_fix` becomes structured)
2. `actions` + `audit_log` tables
3. Discord bot: Approve/Reject buttons, reject-reason modal, role-gated
4. `services/executor`: polls approved actions, executes, watches recovery
5. `services/dashboard` (FastAPI) + `dashboard/` (Vite + React + TS)
6. Eval check: 0 unsafe actions (no action without a prior approval)

## Data model

### `Finding.suggested_fix`: free text → structured action

`services/agent/src/agent/findings.py` currently has:

```python
class Findings(BaseModel):
    ...
    suggested_fix: str
```

This becomes a discriminated union, enforced by the LLM tool-call schema
itself (the `submit_findings` tool's JSON schema), so the model cannot
emit anything but these four shapes:

```python
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
    reason: str  # free text, never executable

SuggestedFix = Annotated[
    RollbackAction | RestartAction | ScaleAction | ManualAction,
    Field(discriminator="type"),
]

class Findings(BaseModel):
    ...
    suggested_fix: SuggestedFix
```

`Finding.suggested_fix` in `db/src/db/models.py` changes from `Text` to
`JSONB`. A migration converts the column and backfills existing rows by
wrapping the old text as `{"type": "manual", "reason": <old text>}`.
`services/bot/src/bot/format.py`'s "Suggested fix" embed field renders
the structured action as text (e.g. `rollback checkout-service: <reason>`).

### New table: `actions`

One row per proposed remediation action, lifecycle tracked in `status`.

| column | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `incident_id` | UUID | |
| `finding_id` | UUID | |
| `type` | text | `rollback` / `restart` / `scale` / `manual` |
| `deployment` | text, nullable | null for `manual` |
| `replicas` | int, nullable | `scale` only |
| `reason` | text | copied from the finding's `suggested_fix.reason` |
| `status` | text | `pending` → `approved`/`rejected` → (if approved) `executed`/`failed` |
| `approved_by` | text, nullable | Discord user id |
| `approved_at` | timestamptz, nullable | |
| `rejection_reason` | text, nullable | from the Discord modal or dashboard reject form |
| `executed_at` | timestamptz, nullable | |
| `outcome` | text, nullable | what the executor found: resolved / timed out / error detail |
| `created_at` | timestamptz | |

A `manual` action never gets a `pending`→`approved` transition offered in
any UI (no Approve button, no dashboard approve control) — it exists only
to carry the finding's manual-remediation text into the same table/timeline.
The executor additionally refuses to execute any `type == "manual"` row
defensively, even though the UI layer should never produce one.

### New table: `audit_log`

Append-only unified timeline, written alongside (not instead of) the
existing `tool_calls`/`findings`/`actions` tables.

| column | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `incident_id` | UUID | |
| `actor` | text | `agent`, `bot:<discord_user_id>`, `executor`, `dashboard:<discord_user_id>` |
| `event_type` | text | `tool_call` / `model_call` / `finding_created` / `approval` / `rejection` / `action_executed` / `action_failed` |
| `detail` | JSONB | event-specific payload |
| `created_at` | timestamptz | |

Every write path (agent's tool-call loop, model-call completion, finding
creation, bot/dashboard approve or reject, executor claim/execute/outcome)
inserts its `audit_log` row in the same DB transaction as its primary
write.

## Services

### `services/bot`

- For findings whose `suggested_fix.type` is `rollback`/`restart`/`scale`,
  the posted embed (`format.py`) includes a `discord.ui.View` with
  Approve and Reject buttons. On post, insert a `pending` `actions` row.
  `manual` findings get no buttons.
- Button custom IDs encode the `action_id`.
- **Approve**: check the clicking member's roles for
  `DISCORD_APPROVER_ROLE_ID` (env var). If absent, ephemeral "you don't
  have permission" reply, no state change. If present: set
  `status="approved"`, `approved_by`, `approved_at`; write `audit_log`
  (`event_type="approval"`); edit the message to show "Approved by @x".
- **Reject**: same role check, then open a `discord.ui.Modal` asking for
  a reason. On submit: set `status="rejected"`, `rejection_reason`; write
  `audit_log` (`event_type="rejection"`); edit the message.
- The approve/reject logic (role check + state transition + audit write)
  lives in one shared function so `services/dashboard` can call the exact
  same code path (see below) rather than reimplementing the rule.

### `services/executor`

Replaces the current `NotImplementedError` stub (`main.py`) with a poll
loop (same `tasks.loop`-style polling cadence as `services/bot`, a few
seconds):

1. Claim: `UPDATE actions SET status='executing' WHERE status='approved' ... RETURNING *` (avoids double-claim if ever run with >1 replica).
2. Reject (defensively) any claimed row with `type == "manual"` — should
   never happen, but the executor never executes free text.
3. Dispatch to a new `K8sExecutorClient` (mirrors
   `services/agent/src/agent/tools/k8s_client.py`'s shape: namespace
   allow-listed to `boutique`, no other mutating verbs):
   - `rollback` → patch the deployment's pod template back to the
     previous revision (direct API patch, consistent with how `chaos/`
     already drives the k8s API directly rather than shelling out).
   - `restart` → patch
     `spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"]`
     (rollout-restart equivalent).
   - `scale` → patch `spec.replicas`.
4. Write `audit_log` (`event_type="action_executed"` or on failure
   `action_failed`) at claim and at dispatch.
5. Poll `incidents.status` (via `actions.incident_id`) every ~10s for up
   to 5 minutes. On `resolved`, set `actions.status="executed"` and
   `outcome="resolved"`; on timeout, `status="failed"`,
   `outcome="timed out after 5m"`. Write a final `audit_log` row.
6. Post the outcome to the Discord channel via a webhook URL env var
   (`DISCORD_WEBHOOK_URL`) — no need to share the bot's gateway
   connection for a one-way notification.

New RBAC (`deploy/k8s/rbac-triage-executor.yaml`): a separate
ServiceAccount with a namespaced `Role` (not `ClusterRole`) in the
`boutique` namespace only, granting `get`/`list`/`patch` on `deployments`
— nothing else. The agent's existing ServiceAccount/ClusterRole
(`deploy/k8s/rbac-triage-agent.yaml`) is untouched.

### `services/dashboard` (FastAPI) + `dashboard/` (Vite + React + TS)

Read endpoints:
- `GET /incidents` — list with status
- `GET /incidents/{id}` — finding, evidence, full chronological timeline
  (`tool_calls` + `audit_log` for that incident, ordered by `created_at`)
- `GET /incidents/{id}/actions`

Write endpoints (require an authenticated session — see below):
- `POST /actions/{id}/approve`
- `POST /actions/{id}/reject` (body: `{reason: str}`)

Both call the same shared approve/reject function `services/bot` uses, so
there is exactly one implementation of "check role, transition state,
write audit_log."

**Auth**: Discord OAuth2 login (`GET /auth/login` redirects to Discord;
`GET /auth/callback` exchanges the code and sets a signed session cookie
containing the Discord user id — not their roles). Every write endpoint
re-checks the user's current guild roles live against Discord's API
(rather than trusting a cached role claim), so a role revoked mid-session
is caught immediately.

`dashboard/` is a separate Vite + React + TS app (not built into
`services/dashboard`): incident list, incident detail with timeline +
evidence, and Approve/Reject controls on pending actions, calling the
FastAPI API by URL. CORS configured for local dev.

## Eval check

New check in `eval/` (`eval/src/eval/scoring.py` or a new module): for
every `actions` row with `status in ("executed", "failed")`, assert an
`audit_log` row with `event_type="approval"` and non-null actor exists
for that action, timestamped before the row's `action_executed`/
`action_failed` audit entry. `eval/src/eval/report.py` gains an "unsafe
actions: N" line; target and CI gate is 0.

## Testing

- `findings.py`: new `services/agent/tests/test_findings.py` with schema
  validation tests for all four `SuggestedFix` variants and rejection of
  anything else.
- `services/bot`: button/modal handlers tested the way `format.py`
  already is — pure functions for the role check and state transition,
  decoupled from `discord.py` objects where possible (mirrors
  `test_format.py`'s approach of avoiding a live client).
- `services/executor`: unit tests against a fake k8s client (mirrors
  `chaos/tests/fake_k8s.py`) for each action type's patch shape, plus the
  claim/poll/timeout state machine with a fake clock.
- `services/dashboard`: endpoint tests with a fake/stubbed Discord OAuth
  and role lookup; a test asserting a non-approver's request is rejected
  (403) even with a valid session.
- `eval/`: a scenario with an `actions` row executed without a matching
  approval `audit_log` row must be caught (count = 1, not 0).

## Out of scope

- No new message queue between bot/dashboard and executor — approval
  handoff happens entirely through the `actions` table (polling), kept
  consistent with "no dependencies the project doesn't already have."
- No dashboard support for creating incidents or editing findings — it is
  read-only except for the approve/reject actions explicitly listed above.
- No retry/backoff policy beyond the single 5-minute recovery window;
  a timed-out action is reported as failed, not automatically retried.
