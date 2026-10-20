# Agent loop, findings, and Discord notification design

## Status

Proposed

## Context

This is step 6 of the triage-agent build: replace the `run_investigation`
stub in `services/agent/src/agent/main.py` with a real LLM tool-calling
loop that investigates an incident using the read-only tools built in step
5, produces a validated JSON findings object, stores it, and notifies a
human via Discord.

Today:
- `services/agent` has a working Kafka consumer, incident upsert, and a
  registry of read-only tools (`query_metrics`, `search_logs`,
  `describe_resource`, `get_events`, `list_pods`) with timeout, truncation,
  redaction, and `tool_calls` tracing already implemented
  (`agent/tools/base.py`, `agent/tools/trace.py`).
- There is no LLM integration anywhere in the repo.
- `services/bot/src/bot/main.py` is a one-function `NotImplementedError`
  stub.
- The `db` package has `incidents` and `tool_calls` tables only; no
  `findings` table.
- No agent framework is used anywhere (ADR 0001) — this step's loop is a
  plain Python `while`, not a graph/state machine from a framework.

Done criteria for this step (from the request):

- `chaos inject crash_loop` leads to a Discord message naming the bad env
  var.
- Every evidence item links to a real row in `tool_calls`.
- Cost per incident is stored and under $0.10 on Haiku 5.5.

## Decision

Add a new top-level `llm/` workspace package providing a provider-agnostic
completion interface over the Anthropic and OpenAI SDKs. Build the agent
loop directly against it in `services/agent`, driving the existing tool
registry plus one new `submit_findings` tool whose schema is the required
output shape. Store results in a new `findings` table. Have `services/bot`
run as an independent long-lived `discord.py` process that polls
`findings` for unposted rows and posts an embed — no new Kafka topic, no
button/approval wiring yet (that's a later step).

```
agent/main.py (consumer)
      |
      v
investigate(incident, tools, llm_client)   <-- new
      |  loop: complete() -> run tool / submit_findings -> repeat
      |  enforced budgets: 15 steps, 5 min wall clock
      |  tracked (not capped): tokens/cost, for storage only
      v
Findings (validated pydantic)  --save_finding-->  findings table
                                                        |
                                            services/bot polls (5s) -->
                                                 Discord embed, posted_at set
```

## Components

### `llm/` package (new workspace member)

Mirrors the `db/` package's role: a small library other services depend on
via `tool.uv.sources` workspace links, not a service of its own.

- `llm/src/llm/types.py` — provider-agnostic dataclasses:
  - `ToolCallRequest(id: str, name: str, args: dict[str, object])`
  - `Usage(input_tokens: int, output_tokens: int)`
  - `CompletionResult(text: str | None, tool_calls: list[ToolCallRequest], usage: Usage, stop_reason: str)`
  - A `Message` type covering the three roles the loop needs to append:
    assistant text/tool-call turns, and tool-result turns keyed by
    `tool_call_id`.
- `llm/src/llm/pricing.py` — `MODEL_PRICES: dict[str, ModelPrice]` (dollars
  per million input/output tokens) covering the four candidate models
  (`claude-sonnet-5-5`, `claude-haiku-5-5`, `gpt-5.6-terra`, `gpt-5.6-luna`);
  `cost_usd(usage: Usage, model: str) -> Decimal`.
- `llm/src/llm/anthropic_provider.py`, `llm/src/llm/openai_provider.py` —
  each implements `complete(messages, tools, system) -> CompletionResult`,
  translating that provider's SDK request/response shape to/from the
  common types. Tool schemas passed in are already the
  `{name, description, input_schema}` dicts `tools/base.ToolSpec.json_schema()`
  produces; each provider adapter reshapes that into its own SDK's expected
  tool-definition format.
- `llm/src/llm/client.py` — `LLMClient(model: str)`: picks the provider by
  model name prefix (`claude-*` -> Anthropic, `gpt-*` -> OpenAI) read from
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`; exposes `.complete(...)` and
  `.cost_usd(usage)`.
- New deps here only: `anthropic`, `openai`. `services/agent` adds
  `triage-llm` as a workspace dependency, same pattern as `triage-db`.
- `MODEL` is read from env in `agent/config.py` (`Settings.model`), default
  `claude-haiku-5-5`, never hardcoded in loop logic.

### Findings schema (`services/agent/src/agent/findings.py`)

```python
class Evidence(BaseModel):
    tool_call_id: str
    detail: str

class Findings(BaseModel):
    summary: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[Evidence]
    affected_services: list[str]
    suggested_fix: str
    ruled_out: list[str]
    status: Literal["complete", "budget_exceeded"]
```

This is also the JSON schema handed to the model as the `submit_findings`
tool's `input_schema` (minus `status`, which the loop sets itself based on
how the loop ended, not something the model reports).

### Agent loop (`services/agent/src/agent/investigate.py`)

```python
def investigate(
    session: Session,
    incident: Incident,
    tools: list[ToolSpec],
    llm_client: LLMClient,
) -> tuple[Findings, Usage]
```

- System prompt loaded from `services/agent/prompts/investigator_v1.md`
  (see below) at call time (no caching across incidents needed at this
  scale).
- Initial user message wraps the untrusted alert fields (`alertname`,
  `labels`, `annotations`) inside clearly delimited `<alert>` tags, with an
  inline reminder that this content is data to analyze, not instructions.
- Tool schema list passed to `complete()` = `schemas_for(tools)` +
  a `submit_findings` schema built from the `Findings` model (excluding
  `status`).
- Loop body, each iteration:
  1. Check budgets (see below); if exceeded, break and build a partial
     `Findings` with `status="budget_exceeded"`.
  2. Call `llm_client.complete(messages, tool_schemas, system_prompt)`;
     accumulate `usage` into a running total.
  3. For each `ToolCallRequest` in the result:
     - If `name == "submit_findings"`: validate `args` against `Findings`
       (with `status` injected as `"complete"`), **and** verify every
       `evidence[].tool_call_id` is present in the set of tool-call ids
       recorded so far this investigation. On success, return immediately.
       On `ValidationError` or an unknown-id citation, append a tool-result
       message describing the specific error and set a `retried_submit`
       flag.
       - If `retried_submit` is already `True` (second failure): stop the
         loop, return a partial `Findings` with `status="budget_exceeded"`
         and whatever `summary`/`evidence` fields can be salvaged from the
         best-effort parse, or placeholder text if none parse at all.
     - Otherwise: look up the tool by name in `tools`, run it via
       `tools.base.run_tool` / `timed_run_tool`, record the call via
       `tools.trace.record_tool_call` (incident_id, tool name, args,
       result, error, duration), append a tool-result message with that
       row's id as `tool_call_id`, increment step count.
  4. If the model returned no tool calls at all (plain text, no
     `submit_findings`), append its text as an assistant turn and continue
     the loop (nudges toward calling `submit_findings` happen via the
     system prompt, not special-cased code).
- Budgets, tracked as local variables for the duration of one call (no
  persistence of in-progress loop state — matches the existing stateless
  consumer design; a crash mid-investigation just means the incident has
  no finding yet and can be reprocessed):
  - `step_count <= 15` (each tool call, including a failed `submit_findings`
    attempt, counts as one step)
  - wall clock: `time.monotonic() - start <= 300`
  - no separate token/cost budget enforced mid-loop for this step (cost is
    recorded, not capped) — out of scope per the request's budget list.

### Storage

New alembic migration `db/migrations/versions/0003_create_findings.py` and
`Finding` model in `db/src/db/models.py`:

```python
class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID]
    incident_id: Mapped[uuid.UUID]
    summary: Mapped[str]
    root_cause: Mapped[str]
    confidence: Mapped[str]
    evidence: Mapped[list[dict[str, object]]]       # JSONB
    affected_services: Mapped[list[str]]              # JSONB
    suggested_fix: Mapped[str]
    ruled_out: Mapped[list[str]]                       # JSONB
    status: Mapped[str]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cost_usd: Mapped[Decimal]                          # Numeric
    posted_at: Mapped[datetime | None]                 # set by bot
    created_at: Mapped[datetime]
```

`services/agent/src/agent/findings_store.py`:
`save_finding(session, incident, findings, usage, cost_usd) -> Finding`.

`main.py`'s `run_investigation` becomes:

```python
def run_investigation(session: Session, incident: Incident, tools, llm_client) -> None:
    findings, usage = investigate(session, incident, tools, llm_client)
    cost = llm_client.cost_usd(usage)
    save_finding(session, incident, findings, usage, cost)
```

`tools` and `llm_client` are built once in `main()` (registry +
`LLMClient(settings.model)`) and threaded through `process_message` /
`consume_forever`, same lifecycle as the existing `session_factory`.

### System prompt (`services/agent/prompts/investigator_v1.md`)

Plain Markdown, loaded as a string (no templating engine needed — the only
variable content is the alert, which goes in the user message, not the
system prompt). Content: role and goal (investigate the alert using the
available read-only tools), the gather-evidence -> hypothesize -> test ->
conclude method, an explicit instruction that alert text, log lines, and
event messages are untrusted data to analyze and never instructions to
follow, and a description of `submit_findings` as the required way to
conclude, including that every evidence item must cite the `tool_call_id`
of a tool call actually made.

### `services/bot` — polling Discord bot

- Adds `discord.py`, `triage-db` to `services/bot/pyproject.toml`.
- `services/bot/src/bot/main.py`:
  - `discord.Client` with a `tasks.loop(seconds=5)` background task started
    `on_ready`.
  - Each tick: open a session, `SELECT * FROM findings WHERE posted_at IS NULL ORDER BY created_at`,
    for each row build an embed (`format_embed(finding) -> discord.Embed`,
    a pure function so it's unit-testable without a live client) — summary,
    root cause, confidence, top 3 evidence entries, suggested fix, cost —
    and `channel.send(embed=...)`, then set `posted_at = now()` and commit.
  - Reads `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `DATABASE_URL` from
    env (already in `.env.example`).
- No approve/deny buttons yet, matching the request's explicit scope.

## Testing

- `llm/tests/test_anthropic_provider.py`, `test_openai_provider.py`: feed a
  mocked SDK response, assert translation into `CompletionResult`.
- `llm/tests/test_pricing.py`: cost calculation for known token counts.
- `services/agent/tests/test_investigate.py`, using a fake `LLMClient` that
  returns a scripted sequence of `CompletionResult`s:
  - normal path: a couple of tool calls then valid `submit_findings` ->
    returns `Findings` with matching evidence ids, tool_calls rows exist.
  - budget exhaustion: fake client scripted to always request another tool
    call -> loop stops at 15 steps (or simulated wall clock) with
    `status="budget_exceeded"`.
  - invalid JSON retry: first `submit_findings` call has a field that fails
    Pydantic validation, second call is valid -> one retry, succeeds.
  - evidence-citation rejection: `submit_findings` cites a `tool_call_id`
    that was never recorded -> rejected, triggers the same one-retry path,
    and fails closed (`budget_exceeded`) if the retry also cites a bad id.
- `services/bot/tests/test_format_embed.py`: pure formatting function,
  various confidence/evidence-count inputs.
- `services/bot/tests/test_poll.py`: fake session/query asserting only
  `posted_at IS NULL` rows are picked up and `posted_at` gets set after
  posting (posting itself mocked).

## Out of scope (explicitly deferred)

- Discord approve/deny buttons and the approval-gated executor flow.
- Token/cost budget enforcement mid-loop (only step count and wall clock
  are enforced; cost is recorded, not capped).
- Persisting in-progress loop state for crash recovery.
- Containerizing/deploying `services/agent` or `services/bot` into the
  cluster (still run locally, matching step 4's deferral of this for
  webhook/agent).
