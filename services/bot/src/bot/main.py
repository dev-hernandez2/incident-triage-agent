"""Discord bot: polls the findings table and posts an embed for each new row.

Executable findings (rollback/restart/scale) get an attached Approve/Reject
button view backed by bot.actions; manual findings are posted without buttons.
"""

import logging
import os
from datetime import UTC, datetime

import discord
from db.models import Action, Finding
from discord.ext import tasks
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from bot.format import format_embed, is_executable_action
from bot.views import RemediationView

POLL_INTERVAL_SECONDS = 5.0

logger = logging.getLogger(__name__)


def fetch_unposted_findings(session: Session) -> list[Finding]:
    return list(
        session.scalars(
            select(Finding).where(Finding.posted_at.is_(None)).order_by(Finding.created_at)
        )
    )


def mark_posted(session: Session, finding: Finding) -> None:
    finding.posted_at = datetime.now(UTC)
    session.flush()


def _insert_pending_action(session: Session, finding: Finding) -> Action:
    fix = finding.suggested_fix
    action = Action(
        incident_id=finding.incident_id,
        finding_id=finding.id,
        type=fix["type"],
        deployment=fix.get("deployment"),
        replicas=fix.get("replicas"),
        reason=fix["reason"],
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def _to_discord_embed(data: dict[str, object]) -> discord.Embed:
    color = data["color"]
    assert isinstance(color, int)
    embed = discord.Embed(title=data["title"], description=data["description"], color=color)
    fields = data["fields"]
    assert isinstance(fields, list)
    for field in fields:
        embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
    return embed


async def post_findings(
    session: Session, channel: discord.abc.Messageable, approver_role_id: int
) -> None:
    """Posts every unposted finding, skipping (and logging) any row whose send fails
    so one bad embed can't take the whole polling task down.
    """
    for finding in fetch_unposted_findings(session):
        try:
            embed = _to_discord_embed(format_embed(finding))
            if is_executable_action(finding.suggested_fix):
                action = _insert_pending_action(session, finding)
                view = RemediationView(
                    session=session,
                    action_id=str(action.id),
                    approver_role_id=approver_role_id,
                    approver=lambda _: None,
                )
                await channel.send(embed=embed, view=view)
            else:
                await channel.send(embed=embed)
            mark_posted(session, finding)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("failed to post finding %s", finding.id)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    approver_role_id = int(os.environ["DISCORD_APPROVER_ROLE_ID"])

    engine = create_engine(database_url)
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_findings() -> None:
        channel = client.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        session = Session(engine)
        try:
            await post_findings(session, channel, approver_role_id)
        finally:
            session.close()

    @client.event
    async def on_ready() -> None:
        poll_findings.start()

    client.run(bot_token)


if __name__ == "__main__":
    main()
