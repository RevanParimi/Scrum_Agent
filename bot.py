"""
bot.py — Discord bot entry point

Responsibilities:
  1. Connect to Discord via Gateway (always-on websocket)
  2. Resolve channel objects from env config
  3. Start APScheduler once bot is ready
  4. Handle on-demand !report and !sprint commands
  5. Auto-create threads in #sprint-discuss on new topic messages
"""

import asyncio
import logging
import os
import sys
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

from pipeline.graph import run_daily_pipeline, run_sprint_report
from scheduler import create_scheduler

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scrum-bot")


# ── Config ────────────────────────────────────────────────────────────────────

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID      = int(os.environ["DISCORD_GUILD_ID"])

CHANNEL_IDS = {
    "sprint-discuss": int(os.environ.get("CHANNEL_SPRINT_DISCUSS", 0)),
    "standup":        int(os.environ.get("CHANNEL_STANDUP",        0)),
    "tasks":          int(os.environ.get("CHANNEL_TASKS",          0)),
    "blockers":       int(os.environ.get("CHANNEL_BLOCKERS",       0)),
    "ai-report":      int(os.environ.get("CHANNEL_AI_REPORT",      0)),
    "changelog":      int(os.environ.get("CHANNEL_CHANGELOG",      0)),
}


# ── Bot setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True   # required to read message text
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Resolved at on_ready; used by pipeline and scheduler
guild_ref: Optional[discord.Guild]           = None
ch_tasks: Optional[discord.TextChannel]      = None
ch_ai_report: Optional[discord.TextChannel]  = None
ch_changelog: Optional[discord.TextChannel]  = None
ch_sprint_discuss: Optional[discord.TextChannel] = None


def get_channel(name: str) -> Optional[discord.TextChannel]:
    """Resolve a channel by name from the guild, using env ID as priority."""
    ch_id = CHANNEL_IDS.get(name, 0)
    if ch_id and guild_ref:
        ch = guild_ref.get_channel(ch_id)
        if ch:
            return ch
    # Fallback: match by name
    if guild_ref:
        for ch in guild_ref.text_channels:
            if ch.name == name:
                return ch
    return None


# ── Pipeline helpers (bound to resolved channels) ─────────────────────────────

async def _run_daily():
    if not guild_ref or not ch_tasks or not ch_ai_report:
        logger.error("Bot not ready — skipping daily pipeline")
        return
    try:
        await run_daily_pipeline(guild_ref, ch_tasks, ch_ai_report, ch_changelog)
    except Exception as exc:
        logger.exception("Daily pipeline failed: %s", exc)


async def _run_weekly():
    if not guild_ref or not ch_tasks or not ch_ai_report:
        logger.error("Bot not ready — skipping weekly pipeline")
        return
    try:
        await run_sprint_report(guild_ref, ch_tasks, ch_ai_report, ch_changelog)
    except Exception as exc:
        logger.exception("Weekly pipeline failed: %s", exc)


# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global guild_ref, ch_tasks, ch_ai_report, ch_changelog, ch_sprint_discuss

    guild_ref       = bot.get_guild(GUILD_ID)
    if not guild_ref:
        logger.critical("Guild %d not found. Check DISCORD_GUILD_ID.", GUILD_ID)
        await bot.close()
        return

    ch_tasks         = get_channel("tasks")
    ch_ai_report     = get_channel("ai-report")
    ch_changelog     = get_channel("changelog")
    ch_sprint_discuss = get_channel("sprint-discuss")

    logger.info("Logged in as %s | Guild: %s", bot.user, guild_ref.name)
    logger.info("  #tasks       → %s", ch_tasks)
    logger.info("  #ai-report   → %s", ch_ai_report)
    logger.info("  #changelog   → %s", ch_changelog)

    # Start scheduler
    scheduler = create_scheduler(_run_daily, _run_weekly)
    scheduler.start()
    logger.info("APScheduler started")


@bot.event
async def on_message(message: discord.Message):
    """Auto-create threads in #sprint-discuss for topic-starter messages."""
    if message.author.bot:
        return

    # Auto-thread: if a message in #sprint-discuss has no thread yet and
    # is long enough to be a topic (>= 20 chars), spin up a thread
    if (
        ch_sprint_discuss
        and message.channel.id == ch_sprint_discuss.id
        and not isinstance(message.channel, discord.Thread)
        and len(message.content) >= 20
    ):
        try:
            thread_name = message.content[:50].strip().replace("\n", " ")
            await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,  # archive after 24h of inactivity
            )
            logger.info("Auto-created thread: %s", thread_name)
        except discord.HTTPException as exc:
            logger.warning("Failed to create auto-thread: %s", exc)

    await bot.process_commands(message)


# ── Commands ──────────────────────────────────────────────────────────────────

@bot.command(name="report")
@commands.has_permissions(manage_messages=True)
async def cmd_report(ctx: commands.Context):
    """!report — trigger an immediate daily digest (owner only)."""
    await ctx.reply("Generating scrum report... this may take ~30 seconds.")
    try:
        await _run_daily()
        await ctx.reply(f"Report complete. Check #{ch_ai_report.name if ch_ai_report else 'ai-report'}.")
    except Exception as exc:
        logger.exception("On-demand report failed")
        await ctx.reply(f"Report failed: {exc}")


@bot.command(name="sprint")
@commands.has_permissions(manage_messages=True)
async def cmd_sprint(ctx: commands.Context):
    """!sprint — trigger the weekly 7-day sprint summary (owner only)."""
    await ctx.reply("Generating weekly sprint report...")
    try:
        await _run_weekly()
        await ctx.reply("Sprint report complete.")
    except Exception as exc:
        logger.exception("On-demand sprint report failed")
        await ctx.reply(f"Sprint report failed: {exc}")


@bot.command(name="tasks")
async def cmd_tasks(ctx: commands.Context):
    """!tasks — list all open tasks from sprint_state.json."""
    import json
    from pathlib import Path
    state_path = Path(__file__).parent / "state" / "sprint_state.json"
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        open_tasks = [t for t in data.get("tasks", []) if t.get("status") != "done"]
        if not open_tasks:
            await ctx.reply("No open tasks.")
            return
        lines = ["**Open Tasks**", "```"]
        for t in open_tasks:
            lines.append(f"{t['id']:4s}  {t['status']:12s}  {t['owner']:15s}  {t['title']}")
        lines.append("```")
        await ctx.reply("\n".join(lines))
    except Exception as exc:
        await ctx.reply(f"Could not load tasks: {exc}")


@bot.command(name="status")
async def cmd_status(ctx: commands.Context):
    """!status — confirm the bot is alive and show next scheduled run."""
    await ctx.reply(
        f"Scrum bot online. Channels resolved:\n"
        f"  tasks={ch_tasks}\n"
        f"  ai-report={ch_ai_report}\n"
        f"  changelog={ch_changelog}"
    )


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN, log_handler=None)
