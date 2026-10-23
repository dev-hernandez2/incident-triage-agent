import opentelemetry.trace as otel_trace
from obs.tracing import configure_tracing
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pytest import MonkeyPatch


def test_configure_tracing_returns_a_tracer_that_creates_spans(
    monkeypatch: MonkeyPatch,
) -> None:
    # `configure_tracing` calls `trace.set_tracer_provider(...)`, which
    # installs a real, process-global OTel TracerProvider. OTel's SDK only
    # allows that to happen once per process, so letting this test perform
    # the real global install would poison every other test in the same
    # pytest process (e.g. services/agent's span-assertion tests) once both
    # suites run together under `uv run --all-packages pytest`. Stub out the
    # global side effect so this test can still exercise the rest of
    # `configure_tracing`'s behavior (resource/exporter/processor
    # construction, no errors) without leaking global state.
    monkeypatch.setattr(otel_trace, "set_tracer_provider", lambda provider: None)

    tracer = configure_tracing("test-service", "http://localhost:4318")

    assert tracer is not None

    # The returned Tracer is a ProxyTracer that resolves against whatever
    # provider is globally installed (which we just stubbed out above), so
    # use a local, isolated provider to verify span creation actually works.
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    local_tracer = provider.get_tracer("test-service")

    with local_tracer.start_as_current_span("test-span") as span:
        span.set_attribute("incident.id", "abc-123")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-span"
    attributes = spans[0].attributes
    assert attributes is not None
    assert attributes["incident.id"] == "abc-123"


def test_spans_capture_set_attributes() -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-service")

    with tracer.start_as_current_span("investigate") as span:
        span.set_attribute("incident.id", "abc-123")
        span.set_attribute("outcome", "complete")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "investigate"
    attributes = spans[0].attributes
    assert attributes is not None
    assert attributes["incident.id"] == "abc-123"
    assert attributes["outcome"] == "complete"
