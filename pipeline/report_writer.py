"""
report_writer.py — LangGraph Node 4

1. Builds the Markdown report from summarized state
2. Appends to TEAM_LOG.md
3. Git commits + pushes (so VS Code users auto-pull)
4. Posts the report to #ai-report in Discord
5. Posts a diff summary to #changelog
"""

import logging
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

import discord

from pipeline.schema import ScrumState, TaskItem

logger = logging.getLogger(__name__)

TEAM_LOG_PATH = Path(os.environ.get("TEAM_LOG_REPO_PATH", ".")) / "TEAM_LOG.md"

DISCORD_CHAR_LIMIT = 2000   # Discord message hard limit


# ── Report builder ─────────────────────────────────────────────────────────────

def build_report_markdown(state: ScrumState) -> str:
    report_date = state.get("report_date", str(date.today()))
    summary = state.get("summary", "No summary available.")
    decisions = state.get("decisions", [])
    blockers = state.get("blockers", [])
    new_tasks: list[TaskItem] = state.get("new_tasks", [])
    all_tasks: list[TaskItem] = state.get("tasks", [])

    lines = [f"## {report_date}", "", "### Summary", summary, ""]

    if decisions:
        lines += ["### Decisions"]
        lines += [f"- {d}" for d in decisions]
        lines += [""]

    if blockers:
        lines += ["### Blockers"]
        lines += [f"- {b}" for b in blockers]
        lines += [""]

    if new_tasks:
        lines += ["### New Tasks Created"]
        lines += ["| ID | Title | Owner | Status |",
                  "|----|-------|-------|--------|"]
        for t in new_tasks:
            lines.append(f"| {t['id']} | {t['title']} | {t['owner']} | {t['status']} |")
        lines += [""]

    # Full task board (all open/in-progress)
    open_tasks = [t for t in all_tasks if t.get("status") in ("open", "in_progress", "blocked")]
    if open_tasks:
        lines += ["### Open Task Board"]
        lines += ["| ID | Title | Owner | Status |",
                  "|----|-------|-------|--------|"]
        for t in open_tasks:
            lines.append(f"| {t['id']} | {t['title']} | {t['owner']} | {t['status']} |")
        lines += [""]

    lines += ["---", ""]
    return "\n".join(lines)


# ── File + Git operations ──────────────────────────────────────────────────────

def append_to_team_log(report_md: str) -> None:
    """Append the report to TEAM_LOG.md, creating it if missing."""
    if not TEAM_LOG_PATH.parent.exists():
        TEAM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not TEAM_LOG_PATH.exists():
        TEAM_LOG_PATH.write_text("# Team Log\n\n", encoding="utf-8")

    with open(TEAM_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(report_md)

    logger.info("Appended report to %s", TEAM_LOG_PATH)


def git_commit_and_push(report_date: str) -> bool:
    """Stage TEAM_LOG.md, commit, and push. Returns True on success."""
    repo_path = str(TEAM_LOG_PATH.parent)
    try:
        subprocess.run(["git", "-C", repo_path, "add", str(TEAM_LOG_PATH)],
                       check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", repo_path, "commit", "-m", f"scrum: daily report {report_date}"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "-C", repo_path, "push"],
                       check=True, capture_output=True)
        logger.info("Git push successful for %s", report_date)
        return True
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        logger.error("Git operation failed: %s", stderr)
        return False


# ── Discord posting ────────────────────────────────────────────────────────────

def chunk_message(text: str, limit: int = DISCORD_CHAR_LIMIT) -> list[str]:
    """Split long text into Discord-safe chunks."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def post_to_discord(
    report_md: str,
    report_date: str,
    ai_report_channel: discord.TextChannel,
    changelog_channel: Optional[discord.TextChannel] = None,
) -> None:
    """Post the full report to #ai-report and a short changelog note to #changelog."""
    header = f"**Sprint Report — {report_date}**\n\n"
    full_text = header + report_md

    for chunk in chunk_message(full_text):
        await ai_report_channel.send(chunk)
    logger.info("Posted report to #ai-report")

    if changelog_channel:
        changelog_note = (
            f"**[{report_date}]** Scrum report generated. "
            f"See #{ai_report_channel.name} for full details. "
            f"TEAM_LOG.md updated."
        )
        await changelog_channel.send(changelog_note)
        logger.info("Posted changelog note")


# ── LangGraph node factory ─────────────────────────────────────────────────────

def make_report_node(
    ai_report_channel: discord.TextChannel,
    changelog_channel: Optional[discord.TextChannel] = None,
):
    """
    Factory that binds Discord channels to the LangGraph report node.

    Usage:
        graph.add_node("report", make_report_node(ai_report_ch, changelog_ch))
    """
    async def report_node(state: ScrumState) -> ScrumState:
        report_md = build_report_markdown(state)
        report_date = state.get("report_date", str(date.today()))

        # 1. Write to TEAM_LOG.md
        append_to_team_log(report_md)

        # 2. Git commit + push
        git_commit_and_push(report_date)

        # 3. Post to Discord
        await post_to_discord(report_md, report_date, ai_report_channel, changelog_channel)

        return {**state, "report_md": report_md}

    return report_node
