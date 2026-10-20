import uuid
from datetime import UTC, datetime
from decimal import Decimal

from bot.format import format_embed
from db.models import Finding


def make_finding(**overrides: object) -> Finding:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        summary="cartservice is crash-looping",
        root_cause="missing REDIS_ADDR env var",
        confidence="high",
        evidence=[
            {"tool_call_id": "a1", "detail": "pod shows CrashLoopBackOff"},
            {"tool_call_id": "a2", "detail": "logs show redis connection refused"},
            {"tool_call_id": "a3", "detail": "deployment env lacks REDIS_ADDR"},
            {"tool_call_id": "a4", "detail": "a fourth piece of evidence"},
        ],
        affected_services=["cartservice"],
        suggested_fix="kubectl set env deployment/cartservice REDIS_ADDR=redis:6379",
        ruled_out=["network policy block"],
        status="complete",
        input_tokens=500,
        output_tokens=200,
        cost_usd=Decimal("0.0045"),
        posted_at=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _fields(embed: dict[str, object]) -> list[dict[str, str]]:
    fields = embed["fields"]
    assert isinstance(fields, list)
    return fields


def test_format_embed_includes_summary_root_cause_and_confidence() -> None:
    embed = format_embed(make_finding())
    assert embed["title"] == "cartservice is crash-looping"
    description = embed["description"]
    assert isinstance(description, str)
    assert "missing REDIS_ADDR env var" in description
    field_names = [f["name"] for f in _fields(embed)]
    assert "Confidence" in field_names


def test_format_embed_shows_only_top_three_evidence_items() -> None:
    embed = format_embed(make_finding())
    evidence_field = next(f for f in _fields(embed) if f["name"] == "Top evidence")
    assert evidence_field["value"].count("\n") == 2
    assert "a4" not in evidence_field["value"]


def test_format_embed_includes_suggested_fix_and_cost() -> None:
    embed = format_embed(make_finding())
    field_names = [f["name"] for f in _fields(embed)]
    assert "Suggested fix" in field_names
    cost_field = next(f for f in _fields(embed) if f["name"] == "Cost")
    assert "0.0045" in cost_field["value"]


def test_format_embed_color_reflects_confidence() -> None:
    high = format_embed(make_finding(confidence="high"))
    low = format_embed(make_finding(confidence="low"))
    assert high["color"] != low["color"]


def test_format_embed_falls_back_to_a_default_color_for_unknown_confidence() -> None:
    embed = format_embed(make_finding(confidence="unknown"))
    assert isinstance(embed["color"], int)


def test_format_embed_truncates_title_to_discord_limit() -> None:
    embed = format_embed(make_finding(summary="x" * 5000))
    title = embed["title"]
    assert isinstance(title, str)
    assert len(title) <= 256


def test_format_embed_truncates_description_to_discord_limit() -> None:
    embed = format_embed(make_finding(root_cause="x" * 5000))
    description = embed["description"]
    assert isinstance(description, str)
    assert len(description) <= 4096


def test_format_embed_truncates_field_values_to_discord_limit() -> None:
    embed = format_embed(make_finding(suggested_fix="x" * 5000))
    fix_field = next(f for f in _fields(embed) if f["name"] == "Suggested fix")
    assert len(fix_field["value"]) <= 1024
