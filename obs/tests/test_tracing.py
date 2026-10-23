from obs.tracing import configure_tracing
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_configure_tracing_returns_a_tracer_that_creates_spans() -> None:
    tracer = configure_tracing("test-service", "http://localhost:4318")

    with tracer.start_as_current_span("test-span") as span:
        span.set_attribute("incident.id", "abc-123")

    assert tracer is not None


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
    assert spans[0].attributes["incident.id"] == "abc-123"
    assert spans[0].attributes["outcome"] == "complete"
