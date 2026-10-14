# ADR 0001: Plain tool-calling loop instead of an agent framework

## Status

Accepted

## Context

`services/agent` investigates Kubernetes alerts by calling a small, fixed
set of read-only tools (e.g. `kubectl get`, `kubectl logs`, metrics queries)
and producing a root-cause summary. Frameworks such as LangGraph, CrewAI, and
AutoGen offer graph/state orchestration, built-in multi-agent patterns, and
abstractions over the tool-calling loop.

## Decision

Implement the agent as a plain tool-calling loop written directly against
the Anthropic and OpenAI SDKs. Do not use LangGraph, CrewAI, AutoGen, or any
other agent framework.

## Rationale

- The tool surface is small and fixed (read-only k8s/observability calls).
  A framework's orchestration layer adds no leverage over a direct
  `while` loop that calls the model, dispatches tool calls, and feeds
  results back.
- This is a portfolio project. Hand-rolling the loop keeps control flow,
  retries, and error handling fully transparent and inspectable — both for
  debugging and for demonstrating the mechanics, rather than hiding them
  behind framework abstractions.
- Avoids framework lock-in and version churn from a fast-moving dependency
  that isn't earning its weight here.
- Model choice is a config value; a plain loop keeps swapping between
  Anthropic/OpenAI SDKs and model tiers trivial, without routing it through
  a framework's model-provider abstraction.

## Consequences

- We own retry logic, conversation state management, and tool-call error
  handling ourselves.
- No framework-provided persistence, tracing, or multi-agent orchestration;
  if investigation needs multiple cooperating agents later, that would be a
  deliberate addition, not inherited for free.
- Easier to audit exactly what the agent can and cannot do (reinforces the
  read-only safety rule), since there's no framework internals to verify.
