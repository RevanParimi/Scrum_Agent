"""
run.py — Standalone pipeline runner (no always-on bot needed)

Usage:
    python run.py            # daily (last 24h)
    python run.py --weekly   # weekly (last 7 days)

Designed to be called by GitHub Actions on a cron schedule.
Connects to Discord, runs the pipeline, posts results, then exits.
"""

import asyncio
import argparse
import logging
import os
import sys
from typing import Optional

import discord
from dotenv import load_dotenv

from pipeline.graph import run_daily_pipeline

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scrum-run")

REQUIRED_ENV = ["DISCORD_TOKEN", "DISCORD_GUILD_ID", "GROQ_API_KEY"]

CHANNEL_IDS = {
    "sprint-discuss": int(os.environ.get("CHANNEL_SPRINT_DISCUSS", 0)),
    "standup":        int(os.environ.get("CHANNEL_STANDUP",        0)),
    "tasks":          int(os.environ.get("CHANNEL_TASKS",          0)),
    "blockers":       int(os.environ.get("CHANNEL_BLOCKERS",       0)),
    "ai-report":      int(os.environ.get("CHANNEL_AI_REPORT",      0)),
    "changelog":      int(os.environ.get("CHANNEL_CHANGELOG",      0)),
}


def check_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.critical("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def get_channel(guild: discord.Guild, name: str) -> Optional[discord.TextChannel]:
    ch_id = CHANNEL_IDS.get(name, 0)
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            return ch
    for ch in guild.text_channels:
        if ch.name == name:
            return ch
    return None


async def main(since_hours: int) -> None:
    check_env()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.guild_messages = True

    client = discord.Client(intents=intents)

    async with client:
        await client.login(os.environ["DISCORD_TOKEN"])
        await client.connect(reconnect=False)  # connects and fetches guilds

        guild_id = int(os.environ["DISCORD_GUILD_ID"])
        guild = client.get_guild(guild_id)

        if not guild:
            logger.critical("Guild %d not found. Check DISCORD_GUILD_ID.", guild_id)
            return

        ch_tasks     = get_channel(guild, "tasks")
        ch_ai_report = get_channel(guild, "ai-report")
        ch_changelog = get_channel(guild, "changelog")

        if not ch_tasks or not ch_ai_report:
            logger.critical("Could not resolve #tasks or #ai-report channels.")
            return

        logger.info("Guild: %s | Running pipeline for last %dh", guild.name, since_hours)

        await run_daily_pipeline(
            guild=guild,
            tasks_channel=ch_tasks,
            ai_report_channel=ch_ai_report,
            changelog_channel=ch_changelog,
            since_hours=since_hours,
        )

        logger.info("Pipeline complete. Exiting.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--weekly", action="store_true", help="Fetch last 7 days instead of 24h")
    args = parser.parse_args()

    since_hours = 168 if args.weekly else 24
    asyncio.run(main(since_hours))
