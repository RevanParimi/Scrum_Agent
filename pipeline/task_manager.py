"""
task_manager.py — LangGraph Node 3

Extracts action items from standup/blockers, deduplicates against the existing
task list, then PROPOSES new tasks in #sprint-discuss for team-lead confirmation
instead of auto-creating them. Confirmed tasks are created in #tasks.
"""

import json
import logging
import os
import re

from datetime import date
from pathlib import Path
from typing import Optional

import discord
from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.schema import ScrumState, TaskItem
from pipeline.teams import get_team_for_member, get_team_for_task_title

logger = logging.getLogger(__name__)

STATE_PATH = Path(__file__).parent.parent / "state" / "sprint_state.json"

# ── Persistence ───────────────────────────────────────────────────────────────

def load_sprint_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "sprint_number": 1,
        "tasks": [],
        "last_report_date": None,
        "sprint_start": None,
        "sprint_end": None,
        "last_ingested_message_ids": {},
        "pending_confirmations": {},
        "pending_proposals": [],
    }


def save_sprint_state(data: dict) -> None:
    STATE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def next_task_id(existing_tasks: list[dict]) -> str:
    if not existing_tasks:
        return "T1"
    nums = []
    for t in existing_tasks:
        try:
            nums.append(int(t["id"][1:]))
        except (ValueError, KeyError):
            pass
    return f"T{max(nums, default=0) + 1}"


# ── Deduplication ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_duplicate_task(title: str, existing_tasks: list[dict]) -> bool:
    """
    Return True if a task with a semantically identical title already exists.
    Uses normalized string equality — good enough for typical task titles.
    """
    norm_new = _normalize(title)
    for task in existing_tasks:
        norm_existing = _normalize(task.get("title", ""))
        if norm_new == norm_existing:
            return True
        # Catch very high overlap (one is a substring of the other, long enough)
        if len(norm_new) > 10 and (norm_new in norm_existing or norm_existing in norm_new):
            return True
    return False


def deduplicate_task_list(tasks: list[dict]) -> list[dict]:
    """
    Remove duplicate tasks from a list, keeping the first occurrence.
    Used during cleanup operations.
    """
    seen: list[str] = []
    result: list[dict] = []
    for task in tasks:
        norm = _normalize(task.get("title", ""))
        if norm not in seen:
            seen.append(norm)
            result.append(task)
    return result


# ── Task extraction via Groq ───────────────────────────────────────────────────

async def extract_action_items(summary: str, raw_messages: dict[str, list[str]]) -> list[dict]:
    """
    Ask Groq LLaMA to pull action items out of the summary.
    Returns a list of {title, owner} dicts — does NOT create tasks yet.
    """
    recent_snippets = []
    for _, msgs in raw_messages.items():
        recent_snippets.extend(msgs[-5:])
    snippets_text = "\n".join(recent_snippets[-40:])

    prompt = f"""You are a scrum master extracting tasks from standup and blocker messages.

SUMMARY:
{summary}

RECENT MESSAGES:
{snippets_text}

Only create a task if the message clearly describes work that someone needs to do — something with a concrete outcome. Use your judgment on intent, not keywords.

DO NOT create tasks for:
- Decisions, opinions, or things the team chose to ignore or skip
- Vague future ideas with no commitment ("maybe someday", "we could consider")
- Status updates on already-completed work
- Anything that doesn't result in someone producing something

Respond ONLY with a valid JSON array:
[
  {{"title": "short imperative task title (≤10 words)", "owner": "discord_username or unassigned"}},
  ...
]

Return [] if nothing clearly qualifies.
"""

    from langchain_groq import ChatGroq
    llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.environ["GROQ_API_KEY"])

    response = await llm.ainvoke([
        SystemMessage(content="You extract structured data. Respond only with valid JSON."),
        HumanMessage(content=prompt),
    ])

    try:
        start = response.content.find("[")
        end = response.content.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(response.content[start:end])
    except json.JSONDecodeError:
        logger.warning("Failed to parse task JSON from LLM")

    return []


# ── Discord helpers ────────────────────────────────────────────────────────────

async def create_task_thread(
    tasks_channel: discord.TextChannel,
    task: TaskItem,
) -> Optional[int]:
    """Post a task card in #tasks and create a thread. Returns thread ID or None."""
    try:
        owner_mention = f"`{task['owner']}`" if task['owner'] != "unassigned" else "unassigned"
        team_label = task.get("team", "unassigned")
        body = (
            f"**{task['id']} — {task['title']}**\n"
            f"Team: `{team_label}`  |  Owner: {owner_mention}  |  "
            f"Status: `{task['status']}`  |  Created: {task['created_date']}"
        )
        msg = await tasks_channel.send(body)
        thread = await msg.create_thread(name=f"{task['id']} {task['title'][:40]}")
        await thread.send(
            f"Task **{task['id']}** opened. Drop progress updates here.\n"
            f"Owner: {owner_mention} — reply `done` when complete."
        )
        logger.info("Created task thread %s: %s", task["id"], task["title"])
        return thread.id
    except Exception as exc:
        logger.error("Failed to create thread for task %s: %s", task["id"], exc)
        return None


async def post_task_proposals(
    sprint_discuss_channel: discord.TextChannel,
    proposed: list[dict],
) -> None:
    """
    Post a batch proposal message to #sprint-discuss listing all new candidate
    tasks. Team leads reply with ✅ task_id to confirm or ❌ task_id to reject.
    Confirmed tasks are created by the bot's reaction/message handler.
    """
    if not proposed:
        return

    lines = [
        "**📋 New task proposals from today's standup — please confirm or reject:**",
        "",
    ]
    for item in proposed:
        lines.append(
            f"• **[{item['proposal_id']}]** {item['title']}  "
            f"_(owner: {item['owner']}, team: {item['team']})_"
        )

    lines += [
        "",
        "Reply `✅ P1` to confirm, `❌ P1` to reject (use the proposal ID, not task ID).",
        "Unconfirmed proposals expire after 24 hours.",
    ]

    try:
        await sprint_discuss_channel.send("\n".join(lines))
        logger.info("Posted %d task proposals to #sprint-discuss", len(proposed))
    except discord.HTTPException as exc:
        logger.error("Failed to post task proposals: %s", exc)


# ── LangGraph node factory ─────────────────────────────────────────────────────

def make_task_node(
    tasks_channel: discord.TextChannel,
    sprint_discuss_channel: Optional[discord.TextChannel] = None,
):
    """
    Factory that binds Discord channels to the LangGraph node.

    New behaviour:
    1. Load existing tasks.
    2. Collect already-confirmed interactive tasks (report_included=False).
    3. Extract candidate tasks from standup/blockers.
    4. Deduplicate against existing tasks.
    5. If sprint_discuss_channel is set → post proposals there for confirmation.
       Otherwise (legacy mode) → create tasks immediately.
    6. Save state and return.
    """
    async def task_node(state: ScrumState) -> ScrumState:
        sprint_data = load_sprint_state()
        existing_tasks: list[TaskItem] = sprint_data.get("tasks", [])

        # Step 1: Collect confirmed-but-unreported interactive tasks
        confirmed_unreported: list[TaskItem] = [
            t for t in existing_tasks if not t.get("report_included", True)
        ]

        # Step 2: Extract candidate tasks from standup/blockers only
        standup_blocker_msgs = {
            src: msgs
            for src, msgs in state.get("raw_messages", {}).items()
            if not src.startswith("sprint-discuss")
        }
        raw_items = await extract_action_items(
            state.get("summary", ""),
            standup_blocker_msgs,
        )

        # Step 3: Deduplicate — skip anything already tracked
        novel_items = [
            item for item in raw_items
            if not is_duplicate_task(item.get("title", ""), existing_tasks)
        ]
        logger.info(
            "Extracted %d candidates, %d after dedup (existing: %d)",
            len(raw_items), len(novel_items), len(existing_tasks),
        )

        # Step 4: Either propose or create directly
        pipeline_new_tasks: list[TaskItem] = []

        if sprint_discuss_channel and novel_items:
            # Proposal mode — post to sprint-discuss, do NOT create threads yet
            existing_proposals = sprint_data.get("pending_proposals", [])
            next_proposal_num = max(
                (int(p["proposal_id"][1:]) for p in existing_proposals if p["proposal_id"].startswith("P")),
                default=0,
            ) + 1

            new_proposals = []
            for i, item in enumerate(novel_items):
                team = get_team_for_task_title(item.get("title", ""))
                if item.get("owner", "unassigned") != "unassigned":
                    team = get_team_for_member(item["owner"]) or team
                proposal = {
                    "proposal_id": f"P{next_proposal_num + i}",
                    "title": item.get("title", "Untitled"),
                    "owner": item.get("owner", "unassigned"),
                    "team": team,
                    "proposed_date": str(date.today()),
                }
                new_proposals.append(proposal)

            sprint_data["pending_proposals"] = existing_proposals + new_proposals
            save_sprint_state(sprint_data)
            await post_task_proposals(sprint_discuss_channel, new_proposals)

        else:
            # Legacy / fallback mode — create tasks immediately (no sprint-discuss channel)
            for item in novel_items:
                task_id = next_task_id(existing_tasks + pipeline_new_tasks)
                team = get_team_for_task_title(item.get("title", ""))
                if item.get("owner", "unassigned") != "unassigned":
                    team = get_team_for_member(item["owner"]) or team
                task: TaskItem = {
                    "id": task_id,
                    "title": item.get("title", "Untitled task"),
                    "owner": item.get("owner", "unassigned"),
                    "team": team,
                    "status": "open",
                    "thread_id": None,
                    "created_date": str(date.today()),
                    "report_included": True,
                }
                thread_id = await create_task_thread(tasks_channel, task)
                task["thread_id"] = thread_id
                pipeline_new_tasks.append(task)
                existing_tasks.append(task)

        # Step 5: Mark confirmed interactive tasks as reported
        for task in existing_tasks:
            if not task.get("report_included", True):
                task["report_included"] = True

        sprint_data["tasks"] = existing_tasks
        save_sprint_state(sprint_data)

        new_tasks = confirmed_unreported + pipeline_new_tasks
        logger.info(
            "Task node complete — %d confirmed + %d pipeline = %d new tasks total",
            len(confirmed_unreported), len(pipeline_new_tasks), len(new_tasks),
        )

        return {**state, "tasks": existing_tasks, "new_tasks": new_tasks}

    return task_node
