## What changed and why

## Checks run

- [ ] `uv run --all-packages ruff check .`
- [ ] `uv run --all-packages mypy .`
- [ ] `uv run --all-packages pytest`
- [ ] `cd dashboard && npx tsc -b && npx vitest run` (if `dashboard/` changed)

## Architectural impact

If this changes how components communicate, changes an interface other
services depend on, or introduces a new dependency, link the issue
discussing it or explain the rationale here (see `CONTRIBUTING.md`).
