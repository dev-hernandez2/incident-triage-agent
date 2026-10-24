# ADR 0004: Read-only agent, separate executor

## Status

Accepted

## Context

The agent investigates alerts using an LLM, and LLM output cannot be
fully trusted to never attempt an unintended or unsafe action. The
project's core safety promise is that no remediation touches the
cluster without a human approving it first.

## Decision

Split "investigate" and "mutate" into two separate services with two
separate Kubernetes ServiceAccounts and RBAC identities:

- `services/agent`: a cluster-wide `ClusterRole` granting only
  `get`/`list`/`watch` — no mutating verb, anywhere, on any resource.
- `services/executor`: a namespaced `Role` (scoped to the executor's
  target namespace, e.g. `boutique`) granting only `get`/`list`/`patch`
  on `deployments` — nothing else, no access outside that namespace,
  and a ServiceAccount entirely distinct from the agent's.

The executor only acts on an `actions` row after it has been approved
via the Discord bot or dashboard (see CLAUDE.md's Notifications &
approvals section) — never directly from the agent's output.

## Rationale

- This is a defense-in-depth guarantee, not just an application-level
  check: even if the agent's code had a bug, or the LLM somehow produced
  a tool call outside its intended tool set, its ServiceAccount's RBAC
  makes mutation impossible at the Kubernetes API level — there is no
  verb to exploit.
- A single service with conditional mutation logic ("only mutate if
  approved") would still need a ServiceAccount with mutating RBAC
  permissions at all times, meaning a bug in the conditional check
  becomes a real cluster mutation. Splitting into two services means the
  mutating identity doesn't exist in the same process as the
  LLM-driven investigation code at all.
- The remediation action schema (typed Pydantic union — rollback/
  restart/scale/manual) enforced at the LLM tool-call boundary is a
  second, independent layer on top of this RBAC split: even an approved
  `manual` action is never executable by `services/executor`, which
  independently refuses it.

## Consequences

- Two deployments to operate and monitor instead of one, and the
  `actions` table is the only handoff point between them — any future
  remediation type must go through that same approval-gated path, not a
  new direct agent-to-cluster call.
- The executor cannot investigate or gather evidence; it can only act on
  an already-diagnosed, already-approved action row. All diagnostic
  logic stays in the agent, where it's safe for it to be imperfect.
