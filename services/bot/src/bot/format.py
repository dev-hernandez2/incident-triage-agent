"""Pure formatting of a Finding row into a Discord embed dict (no discord.py import,
so this is testable without a live client)."""

from db.models import Finding

_CONFIDENCE_COLORS = {
    "high": 0x2ECC71,
    "medium": 0xF1C40F,
    "low": 0xE74C3C,
}


def format_embed(finding: Finding) -> dict[str, object]:
    evidence_lines = [
        f"- {item['detail']} (`{item['tool_call_id']}`)" for item in finding.evidence[:3]
    ]
    return {
        "title": finding.summary,
        "description": f"**Root cause:** {finding.root_cause}",
        "color": _CONFIDENCE_COLORS[finding.confidence],
        "fields": [
            {"name": "Confidence", "value": finding.confidence, "inline": True},
            {"name": "Cost", "value": f"${finding.cost_usd}", "inline": True},
            {
                "name": "Top evidence",
                "value": "\n".join(evidence_lines) or "none",
                "inline": False,
            },
            {"name": "Suggested fix", "value": finding.suggested_fix, "inline": False},
        ],
    }
