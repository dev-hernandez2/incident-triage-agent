# Building a Kubernetes incident triage agent that can't make things worse

## The problem

Alert fatigue is real, and so is the fear of auto-remediation: give an
automated system write access to production and the first time it's
wrong, it can make an outage worse instead of better. I wanted to build
an agent that gets the *investigation* automated — tracing a
CrashLoopBackOff or an OOMKill back to a root cause — without ever
risking the *fix* happening unsupervised.

## Architecture

Alertmanager fires on a Kubernetes alert, and a FastAPI webhook
(`services/webhook`) is the only thing that receives it directly. The
webhook doesn't investigate anything itself — it just validates the
payload and drops it on a Kafka topic, `alerts.raw`. That queue is the
seam between "something happened" and "something is looking into it":
the agent consumes at its own pace, with its own retry and backpressure
semantics, decoupled from however bursty or synchronous Alertmanager's
delivery is.

`services/agent` is a plain tool-calling loop against the
Anthropic/OpenAI SDKs directly — no LangGraph, CrewAI, or AutoGen (see
[ADR 0001](adr/0001-agent-framework.md)). It calls read-only
observability tools (`kubectl get`, `kubectl logs`, metrics and log
queries), writes its findings to Postgres, and proposes a typed
`suggested_fix` — a discriminated union of `rollback`, `restart`,
`scale`, or `manual` (free text, never executable). That's it. It has
no mutating tool to call even if it wanted to: its ServiceAccount's
`ClusterRole` grants only `get`/`list`/`watch`, cluster-wide, and
nothing else exists in its toolbox to try.

The summary and suggested fix get surfaced two ways — a Discord bot
post with Approve/Reject buttons (reject requires a reason, via a
modal) gated to a configured approver role, and a web dashboard with
Discord OAuth2 login that offers the same actions and re-checks the
caller's live Discord role on every write rather than trusting a
cached session claim. Both call the same shared
`bot.actions.approve_action`/`reject_action` functions, so there's
exactly one place in the codebase that enforces the approval rule, not
two copies that could drift.

Only after a human approves does `services/executor` touch the
cluster, and it's a genuinely separate service with a genuinely
separate identity: a namespaced `Role` scoped to one namespace, granting
`get`/`list`/`patch` on `deployments` only. The agent/executor split
([ADR 0004](adr/0004-read-only-agent-separate-executor.md)) is the
load-bearing safety decision in this whole project. It's not a
conditional in application code that says "don't execute without
approval" — a bug could get that condition wrong. It's a Kubernetes
RBAC boundary enforced by the API server: the agent's ServiceAccount
has no `patch` verb on anything, so there is no code path, buggy or
otherwise, by which the investigating process can mutate the cluster.

## How the eval works

The `chaos` CLI injects real faults into a local Online Boutique
cluster — a bad `PORT` env var, a memory limit set below working set, a
broken image tag, under-provisioned CPU, a slow Redis dependency — each
with a hand-authored ground-truth label (root cause, affected service,
expected fix). The eval harness runs the agent against each scenario,
either live against a real cluster or replayed from committed fixtures,
and scores root-cause accuracy and explanation quality against that
ground truth, while tracking cost and latency per run. A budget guard
(`EVAL_BUDGET_USD`) aborts a sweep before it overspends.

## Results, including failures

The committed baseline — `ci-smoke-baseline`, Haiku tier, 9 runs across
3 live-recorded scenarios (`crash_loop`, `oom`, `bad_deploy`) — is 50%
root-cause accuracy, with a median cost of $0.0294 and a median latency
of 12.4s per incident, and a consistency score of 0.78.

I want to be honest about what that number does and doesn't say. This
is a CI regression smoke test, not an accuracy study. It replays 3
fixtures, not the harness's full set of 10 scenarios — the other 7
(`cpu_throttle`, `slow_redis`, `failing_readiness_probe`,
`dns_failure`, `expired_tls_cert`, `red_herring`,
`prompt_injection`) are hand-authored synthetic fixtures that have
never been run through this baseline sweep, so I have no accuracy
number for them at all, live or synthetic. And the one number I do
have is an aggregate: 9 runs, 50% accuracy, no per-scenario breakdown
committed anywhere in the repo. I don't know, from the data I have,
whether the agent gets `crash_loop` right every time and `bad_deploy`
wrong every time, or whether it's inconsistent across all three — the
0.78 consistency score tells me the three runs per scenario don't
always agree with each other, but not which scenario is driving that.
I'd rather say that plainly than invent a specific failure mode I
haven't actually observed. What I can say is that 50% on 9 runs is a
small enough sample that it's a floor to improve from, not a claim
about the agent's real-world reliability, and the next honest step is
running the full 10-scenario set and keeping a per-scenario breakdown
committed so this section can eventually say something sharper than
"an aggregate exists."

## Lessons learned

**A "read-only" safety boundary is also an operational hazard if you
don't bound it.** Building the demo script (`scripts/demo.sh`) that
drives `make demo` end to end, I registered a `cleanup()` trap on
EXIT/INT/TERM that sent SIGTERM to the script's backgrounded
`kubectl port-forward` processes and then called a plain `wait`. That's
fine until a port-forward process is mid-reconnect and simply ignores
SIGTERM — at which point `wait` blocks forever and Ctrl-C (or any
mid-run failure) stops returning control to the user, which is exactly
the failure mode a cleanup trap exists to prevent. The fix was to give
each PID a bounded grace period — poll `kill -0` a fixed number of
times, 1 second apart — and force-kill with `kill -9` if it's still
alive afterward, so cleanup always completes in a bounded time instead
of trusting that every child process honors a termination signal.

**A template that's correct in isolation can still be functionally
dead on arrival.** The Helm chart's ServiceMonitor template was written
to the plan's literal spec — a resource in the chart's own namespace,
with no `release` label and no `namespaceSelector` — and it rendered
fine, passed `helm lint`, and looked done. But the actual
kube-prometheus-stack deployment in this repo discovers ServiceMonitors
through a `serviceMonitorSelector` that, absent an override, only
matches resources carrying `release: kube-prometheus-stack`, and the
Prometheus Operator's CRD watch expected the resource in the
`monitoring` namespace reaching into the target namespace via a
`namespaceSelector`, not the other way around. Nothing about that was
visible from the template alone — you only find it by checking what
the actual operator's discovery mechanism requires, not just whether
the YAML is well-formed.

**Deleting superseded files doesn't surface its own blast radius
until you run the whole test suite, not a scoped one.** Migrating
`deploy/k8s/*.yaml` to the Helm chart meant deleting 9 raw manifests
that the chart now fully replaced. A dry-run and a residual-reference
grep across Makefiles, scripts, and READMEs came back clean — nothing
*operational* pointed at the deleted files anymore. What that check
missed were two pre-existing test files
(`tests/test_deployment_manifests.py`, `tests/test_networkpolicy.py`)
that read those raw YAML files directly off disk as their source of
truth, unrelated to anything the migration task touched on purpose.
They only failed when the full repo-wide `pytest` ran — a package- or
path-scoped run wouldn't have touched them at all, and would have
reported a clean pass while two tests were quietly broken.

**"Zero references today" and "dead code" are not the same claim, and
conflating them is an easy mistake to make during a cleanup pass.** A
dead-code sweep found a `budget.monthlyUsd` key in the Helm chart's
`values.yaml` with no template anywhere referencing it, and the
reflex was to delete it as unused. But that key wasn't an accident —
it was a deliberate, named deliverable of an earlier task in this same
plan, forward-scaffolding toward the project's stated $50/month budget
target, ahead of any enforcement logic the plan had scoped yet. A
naive reference-count check can't distinguish "this is unused and
safe to remove" from "this is a placeholder for a feature that hasn't
been built"; it took someone checking what the key was *for*, not just
whether anything currently reads it, to catch that removing it was
actually reverting a different task's intentional decision.

**The RBAC split only earns the "load-bearing safety decision" claim
if the verbs are checked, not assumed.** It would have been easy to
port the agent's and executor's RBAC manifests into the Helm chart and
trust that templating preserved them faithfully. Instead, each
templated `ClusterRole`/`Role` was diffed verb-for-verb and
resource-for-resource against the original raw manifests it replaced
— confirming the agent's `ClusterRole` still had exactly
`get`/`list`/`watch` and nothing else, and the executor's `Role` still
had exactly `get`/`list`/`patch` on `deployments`, scoped to one
namespace, with zero accidental broadening introduced by the move to
Helm. For a safety boundary that the whole project's threat model
leans on, "it looks the same" isn't good enough; the verbs have to be
checked against the source of truth every time the manifest that
encodes them moves.
