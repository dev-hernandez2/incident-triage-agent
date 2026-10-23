"""Pure formatting of a Finding row into a Discord embed dict (no discord.py import,
so this is testable without a live client)."""

from db.models import Finding

_CONFIDENCE_COLORS = {
    "high": 0x2ECC71,
    "medium": 0xF1C40F,
    "low": 0xE74C3C,
}
_DEFAULT_COLOR = 0x95A5A6

_TITLE_MAX = 256
_DESCRIPTION_MAX = 4096
_FIELD_VALUE_MAX = 1024

_EXECUTABLE_TYPES = {"rollback", "restart", "scale"}


def is_executable_action(suggested_fix: dict[str, object]) -> bool:
    return suggested_fix["type"] in _EXECUTABLE_TYPES


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    ellipsis = "..."
    return text[: limit - len(ellipsis)] + ellipsis


def _render_suggested_fix(fix: object) -> str:
    assert isinstance(fix, dict)
    fix_type = fix["type"]
    reason = fix["reason"]
    if fix_type == "rollback":
        return f"rollback {fix['deployment']}: {reason}"
    if fix_type == "restart":
        return f"restart {fix['deployment']}: {reason}"
    if fix_type == "scale":
        return f"scale {fix['deployment']} to {fix['replicas']} replicas: {reason}"
    return f"manual: {reason}"


def format_embed(finding: Finding) -> dict[str, object]:
    evidence_lines = [
        f"- {item['detail']} (`{item['tool_call_id']}`)" for item in finding.evidence[:3]
    ]
    return {
        "title": _truncate(finding.summary, _TITLE_MAX),
        "description": _truncate(f"**Root cause:** {finding.root_cause}", _DESCRIPTION_MAX),
        "color": _CONFIDENCE_COLORS.get(finding.confidence, _DEFAULT_COLOR),
        "fields": [
            {"name": "Confidence", "value": finding.confidence, "inline": True},
            {"name": "Cost", "value": f"${finding.cost_usd}", "inline": True},
            {
                "name": "Top evidence",
                "value": _truncate("\n".join(evidence_lines) or "none", _FIELD_VALUE_MAX),
                "inline": False,
            },
            {
                "name": "Suggested fix",
                "value": _truncate(_render_suggested_fix(finding.suggested_fix), _FIELD_VALUE_MAX),
                "inline": False,
            },
        ],
    }
