"""
bot.py — Discord bot entry point

Responsibilities:
  1. Connect to Discord via Gateway (always-on websocket)
  2. Resolve channel objects from env config
  3. Start APScheduler once bot is ready
  4. Handle on-demand !report, !sprint, !tasks, !status, !cleanup-tasks commands
  5. Auto-create threads in #sprint-discuss on new topic messages
  6. Participate in sprint-discuss as a conversational scrum master:
       - Read thread history before deciding how to respond
       - Ask clarifying questions, propose tasks, answer questions
       - Confirm / reject task proposals posted by the pipeline (✅ Px / ❌ Px)
       - Extract tasks from shared text files
"""

import asyncio
import logging
import os
import re
import sys
from datetime import date
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

from pipeline.graph import run_daily_pipeline, run_sprint_report
from pipeline.thread_agent import run_thread_agent
from pipeline.task_manager import (
    load_sprint_state,
    save_sprint_state,
    next_task_id,
    create_task_thread,
    deduplicate_task_list,
)
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

READABLE_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv",
    ".yaml", ".yml", ".log", ".xml", ".html", ".sh", ".toml",
}

# ── Bot setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

guild_ref: Optional[discord.Guild]               = None
ch_tasks: Optional[discord.TextChannel]          = None
ch_ai_report: Optional[discord.TextChannel]      = None
ch_changelog: Optional[discord.TextChannel]      = None
ch_sprint_discuss: Optional[discord.TextChannel] = None

# Pending task confirmations keyed by channel/thread ID.
# { channel_id: {"task_title": str, "task_owner": str} }
pending_confirmations: dict[int, dict] = {}


def get_channel(name: str) -> Optional[discord.TextChannel]:
    ch_id = CHANNEL_IDS.get(name, 0)
    if ch_id and guild_ref:
        ch = guild_ref.get_channel(ch_id)
        if ch:
            return ch
    if guild_ref:
        for ch in guild_ref.text_channels:
            if ch.name == name:
                return ch
    return None


# ── Pending confirmation persistence ──────────────────────────────────────────

def _load_pending_confirmations() -> None:
    global pending_confirmations
    data = load_sprint_state()
    raw = data.get("pending_confirmations", {})
    pending_confirmations = {int(k): v for k, v in raw.items()}
    if pending_confirmations:
        logger.info("Restored %d pending confirmations", len(pending_confirmations))


def _save_pending_confirmations() -> None:
    data = load_sprint_state()
    data["pending_confirmations"] = {str(k): v for k, v in pending_confirmations.items()}
    save_sprint_state(data)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def fetch_thread_history(
    channel: discord.abc.Messageable,
    exclude_message_id: int,
    limit: int = 15,
) -> list[str]:
    history = []
    async for msg in channel.history(limit=limit + 1, oldest_first=False):
        if msg.id == exclude_message_id:
            continue
        name = "🤖 Scrum Bot" if msg.author.bot else msg.author.display_name
        attachment_note = ""
        if msg.attachments:
            names = ", ".join(a.filename for a in msg.attachments)
            attachment_note = f" [attached: {names}]"
        history.append(f"[{name}]: {msg.content}{attachment_note}")
    history.reverse()
    return history


async def extract_attachment_text(message: discord.Message) -> Optional[str]:
    for attachment in message.attachments:
        suffix = "." + attachment.filename.rsplit(".", 1)[-1].lower() if "." in attachment.filename else ""
        if suffix in READABLE_EXTENSIONS:
            try:
                data = await attachment.read()
                text = data.decode("utf-8", errors="replace")
                logger.info("Read attachment: %s (%d chars)", attachment.filename, len(text))
                return f"[{attachment.filename}]\n{text}"
            except Exception as exc:
                logger.warning("Could not read attachment %s: %s", attachment.filename, exc)
    return None


async def create_confirmed_task(confirmation: dict, channel: discord.abc.Messageable) -> str:
    sprint_data = load_sprint_state()
    existing = sprint_data.get("tasks", [])

    task_id = next_task_id(existing)
    task = {
        "id": task_id,
        "title": confirmation["task_title"],
        "owner": confirmation["task_owner"],
        "team": confirmation.get("task_team", "data"),
        "status": "open",
        "thread_id": None,
        "created_date": str(date.today()),
        "report_included": False,
    }

    if ch_tasks:
        thread_id = await create_task_thread(ch_tasks, task)
        task["thread_id"] = thread_id

    existing.append(task)
    sprint_data["tasks"] = existing
    save_sprint_state(sprint_data)

    logger.info("Task confirmed and created: %s — %s", task_id, task["title"])
    return task_id


# ── Pipeline proposal confirmation (✅ Px / ❌ Px) ────────────────────────────

_CONFIRM_RE = re.compile(r"^[✅✓y][\s]*(P\d+)", re.IGNORECASE)
_REJECT_RE  = re.compile(r"^[❌✗xn][\s]*(P\d+)", re.IGNORECASE)


async def _handle_proposal_reply(message: discord.Message) -> bool:
    """
    Check if this message is confirming/rejecting a pipeline task proposal.
    Returns True if the message was handled here (prevents double-processing).
    """
    confirm_match = _CONFIRM_RE.match(message.content.strip())
    reject_match  = _REJECT_RE.match(message.content.strip())

    if not confirm_match and not reject_match:
        return False

    proposal_id = (confirm_match or reject_match).group(1).upper()
    sprint_data = load_sprint_state()
    proposals   = sprint_data.get("pending_proposals", [])

    target = next((p for p in proposals if p["proposal_id"] == proposal_id), None)
    if not target:
        await message.reply(f"No pending proposal **{proposal_id}** found.")
        return True

    if confirm_match:
        # Create the task
        task_id = next_task_id(sprint_data.get("tasks", []))
        task = {
            "id": task_id,
            "title": target["title"],
            "owner": target["owner"],
            "team": target.get("team", "data"),
            "status": "open",
            "thread_id": None,
            "created_date": str(date.today()),
            "report_included": False,
        }
        if ch_tasks:
            thread_id = await create_task_thread(ch_tasks, task)
            task["thread_id"] = thread_id
        sprint_data.setdefault("tasks", []).append(task)
        sprint_data["pending_proposals"] = [p for p in proposals if p["proposal_id"] != proposal_id]
        save_sprint_state(sprint_data)
        await message.reply(
            f"✅ **{task_id}** created: _{target['title']}_ "
            f"(team: `{target.get('team','data')}`, owner: `{target['owner']}`). "
            f"Thread opened in <#{CHANNEL_IDS.get('tasks', 0)}>."
        )
        logger.info("Proposal %s confirmed → task %s", proposal_id, task_id)
    else:
        sprint_data["pending_proposals"] = [p for p in proposals if p["proposal_id"] != proposal_id]
        save_sprint_state(sprint_data)
        await message.reply(f"❌ Proposal **{proposal_id}** rejected — will not create _{target['title']}_.")
        logger.info("Proposal %s rejected by %s", proposal_id, message.author.display_name)

    return True


# ── Pipeline helpers ───────────────────────────────────────────────────────────

async def _run_daily():
    if not guild_ref or not ch_tasks or not ch_ai_report:
        logger.error("Bot not ready — skipping daily pipeline")
        return
    try:
        await run_daily_pipeline(guild_ref, ch_tasks, ch_ai_report, ch_changelog, ch_sprint_discuss)
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

    guild_ref         = bot.get_guild(GUILD_ID)
    if not guild_ref:
        logger.critical("Guild %d not found. Check DISCORD_GUILD_ID.", GUILD_ID)
        await bot.close()
        return

    ch_tasks          = get_channel("tasks")
    ch_ai_report      = get_channel("ai-report")
    ch_changelog      = get_channel("changelog")
    ch_sprint_discuss = get_channel("sprint-discuss")

    logger.info("Logged in as %s | Guild: %s", bot.user, guild_ref.name)
    logger.info("  #tasks          → %s", ch_tasks)
    logger.info("  #ai-report      → %s", ch_ai_report)
    logger.info("  #sprint-discuss → %s", ch_sprint_discuss)

    if not ch_sprint_discuss:
        logger.warning(
            "⚠️  #sprint-discuss channel NOT found. "
            "Set CHANNEL_SPRINT_DISCUSS env var or ensure the channel name matches."
        )

    _load_pending_confirmations()

    scheduler = create_scheduler(_run_daily, _run_weekly)
    scheduler.start()
    logger.info("APScheduler started")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Determine if this is a sprint-discuss message or a thread inside it
    is_sprint_discuss = False
    if ch_sprint_discuss:
        if message.channel.id == ch_sprint_discuss.id:
            is_sprint_discuss = True
        elif (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == ch_sprint_discuss.id
        ):
            is_sprint_discuss = True
    else:
        # Fallback: match by channel name if ID lookup failed
        ch_name = getattr(message.channel, "name", "") or getattr(
            getattr(message.channel, "parent", None), "name", ""
        )
        if ch_name == "sprint-discuss":
            is_sprint_discuss = True

    # Auto-thread main-channel messages
    if is_sprint_discuss and not isinstance(message.channel, discord.Thread) and len(message.content) >= 20:
        try:
            thread_name = message.content[:50].strip().replace("\n", " ")
            await message.create_thread(name=thread_name, auto_archive_duration=1440)
            logger.info("Auto-created thread: %s", thread_name)
        except discord.HTTPException as exc:
            logger.warning("Failed to create auto-thread: %s", exc)

    # Handle sprint-discuss conversational agent + proposal replies
    if is_sprint_discuss:
        # Check for pipeline proposal confirmations first (✅ Px / ❌ Px)
        handled = await _handle_proposal_reply(message)
        if not handled:
            asyncio.create_task(_handle_sprint_discuss(message))

    await bot.process_commands(message)


async def _handle_sprint_discuss(message: discord.Message) -> None:
    channel_id = message.channel.id

    thread_history  = await fetch_thread_history(message.channel, exclude_message_id=message.id)
    attachment_text = await extract_attachment_text(message)
    sprint_data     = load_sprint_state()
    pending         = pending_confirmations.get(channel_id)

    result = await run_thread_agent(
        message_content=message.content,
        author=message.author.display_name,
        thread_history=thread_history,
        sprint_tasks=sprint_data.get("tasks", []),
        pending_confirmation=pending,
        attachment_text=attachment_text,
    )

    action = result.get("action", "silent")
    reply  = result.get("message", "").strip()

    logger.info(
        "sprint-discuss agent | author=%s | action=%s | channel=%s",
        message.author.display_name, action, message.channel.id,
    )

    if action == "silent":
        return

    elif action == "propose_task":
        if not reply:
            return
        try:
            await message.reply(reply)
            pending_confirmations[channel_id] = {
                "task_title": result.get("task_title", "Unnamed task"),
                "task_owner": result.get("task_owner", "unassigned"),
            }
            _save_pending_confirmations()
        except discord.HTTPException as exc:
            logger.warning("Failed to post task proposal: %s", exc)

    elif action == "ask_clarification":
        if reply:
            try:
                await message.reply(reply)
            except discord.HTTPException as exc:
                logger.warning("Failed to post clarification: %s", exc)

    elif action == "confirm_task":
        if pending:
            try:
                task_id = await create_confirmed_task(pending, message.channel)
                del pending_confirmations[channel_id]
                _save_pending_confirmations()
                owner_display = (
                    f"`{pending['task_owner']}`"
                    if pending["task_owner"] != "unassigned"
                    else "unassigned"
                )
                confirm_msg = (
                    reply
                    or f"Done — added **{task_id}: {pending['task_title']}** "
                       f"(owner: {owner_display}). Thread created in <#{CHANNEL_IDS.get('tasks', 0)}>."
                )
                await message.reply(confirm_msg)
            except Exception as exc:
                logger.exception("Failed to create confirmed task: %s", exc)
        else:
            logger.debug("confirm_task action with no pending confirmation — ignored")

    elif action == "reject_task":
        if pending:
            del pending_confirmations[channel_id]
            _save_pending_confirmations()
            if reply:
                try:
                    await message.reply(reply)
                except discord.HTTPException:
                    pass
            logger.info("Task proposal rejected by team: %s", pending.get("task_title"))

    elif action in ("answer_question", "note_decision"):
        if reply:
            try:
                await message.reply(reply)
            except discord.HTTPException as exc:
                logger.warning("Failed to post agent reply: %s", exc)


# ── Commands ──────────────────────────────────────────────────────────────────

@bot.command(name="report")
@commands.has_permissions(manage_messages=True)
async def cmd_report(ctx: commands.Context):
    """!report — trigger an immediate daily digest."""
    await ctx.reply("Generating scrum report… this may take ~30 seconds.")
    try:
        await _run_daily()
        await ctx.reply(f"Report complete. Check #{ch_ai_report.name if ch_ai_report else 'ai-report'}.")
    except Exception as exc:
        logger.exception("On-demand report failed")
        await ctx.reply(f"Report failed: {exc}")


@bot.command(name="sprint")
@commands.has_permissions(manage_messages=True)
async def cmd_sprint(ctx: commands.Context):
    """!sprint — trigger the weekly 7-day sprint summary."""
    await ctx.reply("Generating weekly sprint report…")
    try:
        await _run_weekly()
        await ctx.reply("Sprint report complete.")
    except Exception as exc:
        logger.exception("On-demand sprint report failed")
        await ctx.reply(f"Sprint report failed: {exc}")


@bot.command(name="tasks")
async def cmd_tasks(ctx: commands.Context):
    """!tasks — list all open tasks grouped by team."""
    data = load_sprint_state()
    open_tasks = [t for t in data.get("tasks", []) if t.get("status") != "done"]
    if not open_tasks:
        await ctx.reply("No open tasks.")
        return

    # Group by team
    by_team: dict[str, list] = {}
    for t in open_tasks:
        team = t.get("team", "unassigned")
        by_team.setdefault(team, []).append(t)

    lines = ["**Open Tasks by Team**"]
    for team, tasks in sorted(by_team.items()):
        lines.append(f"\n**{team.upper()}**")
        lines.append("```")
        for t in tasks:
            lines.append(f"{t['id']:4s}  {t['status']:12s}  {t['owner']:15s}  {t['title']}")
        lines.append("```")

    # Proposals pending confirmation
    proposals = data.get("pending_proposals", [])
    if proposals:
        lines.append(f"\n**Pending Proposals** ({len(proposals)} awaiting confirmation in #sprint-discuss)")
        lines.append("```")
        for p in proposals:
            lines.append(f"{p['proposal_id']:4s}  {p['team']:12s}  {p['owner']:15s}  {p['title']}")
        lines.append("```")
        lines.append("Reply `✅ Px` to confirm or `❌ Px` to reject in #sprint-discuss.")

    await ctx.reply("\n".join(lines))


@bot.command(name="status")
async def cmd_status(ctx: commands.Context):
    """!status — confirm the bot is alive and show channel bindings."""
    sprint_data = load_sprint_state()
    open_count  = sum(1 for t in sprint_data.get("tasks", []) if t.get("status") != "done")
    proposal_count = len(sprint_data.get("pending_proposals", []))
    await ctx.reply(
        f"Scrum bot online — Sprint {sprint_data.get('sprint_number', '?')}\n"
        f"  #tasks         = {ch_tasks}\n"
        f"  #ai-report     = {ch_ai_report}\n"
        f"  #sprint-discuss= {ch_sprint_discuss}\n"
        f"  open tasks     = {open_count}\n"
        f"  pending proposals = {proposal_count}"
    )


@bot.command(name="cleanup-tasks")
@commands.has_permissions(manage_messages=True)
async def cmd_cleanup_tasks(ctx: commands.Context):
    """!cleanup-tasks — deduplicate tasks in state and post a summary."""
    sprint_data = load_sprint_state()
    before = len(sprint_data.get("tasks", []))
    sprint_data["tasks"] = deduplicate_task_list(sprint_data.get("tasks", []))
    after = len(sprint_data["tasks"])
    save_sprint_state(sprint_data)

    removed = before - after
    lines = [
        f"✅ Task cleanup complete.",
        f"  Before: {before} tasks",
        f"  After : {after} tasks",
        f"  Removed: {removed} duplicates",
        "",
        "**Current canonical tasks:**",
        "```",
    ]
    for t in sprint_data["tasks"]:
        lines.append(f"{t['id']:4s}  [{t.get('team','?'):14s}]  {t['owner']:15s}  {t['title']}")
    lines.append("```")
    await ctx.reply("\n".join(lines))


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN, log_handler=None)
