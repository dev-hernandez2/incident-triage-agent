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

This is the only real number available: a small-sample (9 runs, 3
scenarios) Haiku-tier baseline. No cross-model comparison (Sonnet vs.
Haiku, Claude vs. GPT) has been run yet — see the Limitations section of
the README. This ADR records the config mechanism and the evidence that
exists, not a conclusion about which tier is "better"; that comparison
is future work.

## Rationale

- A plain config value (not a framework-level model abstraction, see
  ADR 0001) keeps swapping tiers a one-line change.
- Defaulting local dev to the cheap tier keeps iteration cost near zero
  while developing, reserving the default tier for deliberate evals or
  demos, per CLAUDE.md's budget section.

## Consequences

- Eval results are not yet comparable across tiers/providers — any
  claim about relative accuracy or cost between Sonnet/Haiku/GPT tiers
  would be speculation until that sweep is run and committed.
