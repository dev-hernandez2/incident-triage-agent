# ADR 0003: Kafka for alert ingestion

## Status

Accepted

## Context

`services/webhook` receives Alertmanager webhooks and must hand them off
to `services/agent` for investigation. The agent's investigation (a
multi-turn LLM tool-calling loop) takes seconds to tens of seconds per
alert — far longer than a webhook handler should hold a request open for.

## Decision

Put a Kafka topic (`alerts.raw`) between the webhook and the agent.
`services/webhook` only validates and publishes; `services/agent` consumes
independently.

## Rationale

- Decouples webhook availability from agent processing time. Alertmanager
  gets a fast 2xx the moment the message is published, regardless of how
  long investigation takes or whether the agent is temporarily down.
- Kafka's consumer offset model gives the agent at-least-once delivery
  and natural backpressure: if investigation is slow, alerts queue
  rather than get dropped or time out the webhook.
- A single-partition topic with one consumer group is sufficient at this
  project's scale (one demo cluster, a handful of alerts at a time) —
  Kafka's partitioning/scaling story isn't the reason for the choice, and
  isn't exercised here.
- Alternatives considered: a direct HTTP call from webhook to agent
  (couples their availability and request lifetimes together, and the
  agent has no natural place to expose an HTTP endpoint since it's a
  pure consumer loop); Redis Streams or SQS (would work similarly, but
  Kafka was already the more familiar/demonstrable choice for a
  portfolio project and this repo's existing `kafka-values.yaml`
  Bitnami chart).

## Consequences

- An extra moving part (`deploy/helm/kafka-values.yaml`'s Bitnami Kafka)
  that must be running for the pipeline to function at all — `make up`
  fails fast if it can't come up, rather than degrading silently.
- `services/agent`'s consumer group (`group.id: "triage-agent"`,
  `enable.auto.commit: False`) commits offsets only after a message is
  fully processed, so a crash mid-investigation redelivers that alert
  rather than losing it.
