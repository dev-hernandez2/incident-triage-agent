# ADR 0005: Model choice

## Status

Accepted

## Context

The agent's LLM calls are the dominant cost driver (target: $50/month).
Model choice needed to be a config value, not hardcoded, per CLAUDE.md,
so cost and accuracy could be tuned without code changes.

## Decision

Default candidate models: Claude Sonnet 5.5 and gpt-5.6-terra. Cheap-tier
default for local dev: Claude Haiku 5.5 and gpt-5.6-luna. The tier used
is a config value (env var / Helm values `models.tier`), defaulting to
`cheap`.

## Evidence available today

`eval/results/latest_summary.md` (the committed CI regression baseline,
from the `eval-smoke` CI job replaying 3 fixtures with `claude-haiku-5-5`):

| model | accuracy | median_time_s | median_cost_usd | consistency | n_runs |
|---|---|---|---|---|---|
| ci-smoke-baseline | 0.50 | 12.4 | 0.0294 | 0.78 | 9 |

A full 10-scenario, 3-repeat replay on Haiku (`eval/results/
20261127T040916Z_summary.md`) scored 60% accuracy (18/30), $0.0334
median cost/incident, 0 unsafe actions — a larger sample than the CI
baseline but still small.

A Sonnet 5.5 vs. Haiku 5.5 comparison (1 repeat per scenario, 10
scenarios, `eval/results/20261127T041817Z.csv`):

| model | accuracy | avg cost/incident | avg time |
|---|---|---|---|
| claude-sonnet-5-5 | 80% (8/10) | $0.0527 | 8.6s |
| claude-haiku-5-5 | 50% (5/10) | $0.0335 | 12.5s |

On this sample, Haiku reaches 63% of Sonnet's accuracy at 64% of the
cost. n=1 per scenario is too small to call this a settled result, but
it's a real, non-speculative data point in favor of keeping Haiku as
the local-dev default while reserving Sonnet for demos/deliberate
evals, per CLAUDE.md's budget section. No GPT-side comparison (Claude
vs. gpt-5.6-terra/luna) has been run yet — see the Limitations section
of the README.

## Rationale

- A plain config value (not a framework-level model abstraction, see
  ADR 0001) keeps swapping tiers a one-line change.
- Defaulting local dev to the cheap tier keeps iteration cost near zero
  while developing, reserving the default tier for deliberate evals or
  demos, per CLAUDE.md's budget section.

## Consequences

- Sonnet vs. Haiku is now measured (above), but on a small sample
  (n=1/scenario) — a larger sweep would tighten the confidence interval
  before treating the 80%-vs-50% gap as precise.
- Claude vs. GPT tiers are still not comparable — any claim there would
  be speculation until that sweep is run and committed.
