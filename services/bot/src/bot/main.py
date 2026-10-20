"""Discord bot: polls the findings table and posts an embed for each new row.

No approve/deny buttons yet — that's a later step.
"""

import os
from datetime import UTC, datetime

import discord
from db.models import Finding
from discord.ext import tasks
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from bot.format import format_embed

POLL_INTERVAL_SECONDS = 5.0


def fetch_unposted_findings(session: Session) -> list[Finding]:
    return list(
        session.scalars(
            select(Finding).where(Finding.posted_at.is_(None)).order_by(Finding.created_at)
        )
    )


def mark_posted(session: Session, finding: Finding) -> None:
    finding.posted_at = datetime.now(UTC)
    session.flush()


def _to_discord_embed(data: dict[str, object]) -> discord.Embed:
    color = data["color"]
    assert isinstance(color, int)
    embed = discord.Embed(title=data["title"], description=data["description"], color=color)
    fields = data["fields"]
    assert isinstance(fields, list)
    for field in fields:
        embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
    return embed


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    bot_token = os.environ["DISCORD_BOT_TOKEN"]

    engine = create_engine(database_url)
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_findings() -> None:
        channel = client.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        session = Session(engine)
        try:
            for finding in fetch_unposted_findings(session):
                embed = _to_discord_embed(format_embed(finding))
                await channel.send(embed=embed)
                mark_posted(session, finding)
                session.commit()
        finally:
            session.close()

    @client.event
    async def on_ready() -> None:
        poll_findings.start()

    client.run(bot_token)


if __name__ == "__main__":
    main()
