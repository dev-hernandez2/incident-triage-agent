# Contributing

This is a portfolio project, but issues and PRs are welcome.

## Setup

```bash
uv sync --all-packages
cd dashboard && npm install && cd ..
```

## Running checks before a PR

```bash
uv run --all-packages ruff check .
uv run --all-packages mypy .
uv run --all-packages pytest
cd dashboard && npx tsc -b && npx vitest run
```

All four must pass. The full-repo `pytest` run (no path argument) is
required, not just a package-scoped run — some import-collision bugs
only surface at that scope (see `CLAUDE.md`'s Conventions section).

## Commit style

Small, atomic commits — one logical change each.

## Architectural changes

If your change affects how components communicate, changes an
interface other services depend on, or introduces a new dependency,
open an issue first or include a short rationale in the PR description.
Significant decisions are recorded as ADRs in `docs/adr/` — see existing
ones for the format.

## Safety-critical code

`services/agent` must stay read-only (see `CLAUDE.md`'s Safety rules).
Any PR touching `services/agent/src/agent/tools/` must not add a
mutating capability. Any PR touching `services/executor` should include
or update the corresponding `eval/unsafe_actions` check if it changes
the approval-to-execution path.
