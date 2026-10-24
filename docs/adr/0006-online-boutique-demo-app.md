# ADR 0006: Online Boutique as the only demo app

## Status

Accepted

## Context

The agent needs a realistic target application to investigate alerts
against, and the `chaos` CLI needs a realistic application to inject
faults into.

## Decision

Use Google's Online Boutique (`microservices-demo`) exclusively. No
other demo app is supported.

## Rationale

- Online Boutique is a realistic polyglot microservices topology (Go,
  Java, Python, Node.js, C# services communicating over gRPC) — closer
  to a real production system than a toy single-service demo, which
  matters for an agent meant to investigate real-looking failure modes
  (CrashLoopBackOff, OOMKilled, ImagePullBackOff, CPU throttling, slow
  dependency calls — see `chaos/README.md`'s scenario table).
- It's well-known enough in the Kubernetes/observability community that
  reviewers evaluating this portfolio project don't need to learn an
  unfamiliar app's architecture before understanding what the agent
  diagnosed.
- Existing community Prometheus/Grafana dashboards and alerting rules
  for Online Boutique reduce the amount of custom monitoring setup this
  project needs to build and maintain itself.
- Supporting multiple demo apps would mean maintaining fault-injection
  scenarios, ground-truth labels, and alerting rules per app — pure
  overhead for a project whose focus is the agent, not the demo
  environment.

## Consequences

- `chaos/`'s scenario implementations and ground-truth labels
  (`chaos/src/chaos/scenarios/`) are written against Online Boutique's
  specific service names (`cartservice`, `paymentservice`,
  `redis-cart`, etc.) — porting to a different demo app would mean
  rewriting those, not just pointing at a new cluster.
