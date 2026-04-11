"""
task_manager.py — LangGraph Node 3

Uses Claude to detect action items from the summary + raw messages.
Creates new task threads in the #tasks Discord channel.
Persists task state to state/sprint_state.json.
"""

import json
import logging
import os

from datetime import date
from pathlib import Path
from typing import Optional

import discord
#from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.schema import ScrumState, TaskItem

logger = logging.getLogger(__name__)

STATE_PATH = Path(__file__).parent.parent / "state" / "sprint_state.json"
MODEL = "claude-haiku-4-5-20251001"   # fast + cheap for task extraction
MAX_TOKENS = 1024


# ── Persistence ───────────────────────────────────────────────────────────────

def load_sprint_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"sprint_number": 1, "tasks": [], "last_report_date": None,
            "sprint_start": None, "sprint_end": None, "last_ingested_message_ids": {}}


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


# ── Task extraction via Claude ─────────────────────────────────────────────────

async def extract_action_items(summary: str, raw_messages: dict[str, list[str]]) -> list[dict]:
    """
    Ask Claude Haiku to pull action items out of the summary.
    Returns a list of {title, owner} dicts.
    """
    recent_snippets = []
    for _, msgs in raw_messages.items():
        recent_snippets.extend(msgs[-5:])   # last 5 msgs per source
    snippets_text = "\n".join(recent_snippets[-40:])  # cap at 40 lines

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

    #llm = ChatAnthropic(
    #    model=MODEL,
    #    max_tokens=MAX_TOKENS,
    #    anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
   # )
    from langchain_groq import ChatGroq
    llm = ChatGroq(
        model="llama-3.3-70b-versatile", 
        api_key=os.environ["GROQ_API_KEY"]
    )


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
        logger.warning("Failed to parse task JSON from Claude")

    return []


# ── Discord thread creation ────────────────────────────────────────────────────

async def create_task_thread(
    tasks_channel: discord.TextChannel,
    task: TaskItem,
) -> Optional[int]:
    """
    Post a task card message in #tasks and create a thread on it.
    Returns the thread ID or None on failure.
    """
    try:
        owner_mention = f"`{task['owner']}`" if task['owner'] != "unassigned" else "unassigned"
        body = (
            f"**{task['id']} — {task['title']}**\n"
            f"Owner: {owner_mention}  |  Status: `{task['status']}`  |  Created: {task['created_date']}"
        )
        msg = await tasks_channel.send(body)
        thread = await msg.create_thread(name=f"{task['id']} {task['title'][:40]}")
        await thread.send(
            f"Task **{task['id']}** opened. Drop progress updates here.\n"
            f"Owner: {owner_mention} — mark done by replying `done` or updating status."
        )
        logger.info("Created task thread %s: %s", task["id"], task["title"])
        return thread.id
    except Exception as exc:
        logger.error("Failed to create thread for task %s: %s", task["id"], exc)
        return None


# ── LangGraph node factory ─────────────────────────────────────────────────────

def make_task_node(tasks_channel: discord.TextChannel):
    """
    Factory that binds the #tasks Discord channel to the LangGraph node.

    Usage:
        graph.add_node("tasks", make_task_node(tasks_channel))
    """
    async def task_node(state: ScrumState) -> ScrumState:
        sprint_data = load_sprint_state()
        existing_tasks: list[TaskItem] = sprint_data.get("tasks", [])

        # ── Step 1: Collect confirmed tasks pending their first report ────────
        # These were confirmed interactively in #sprint-discuss via ✅ reaction.
        # report_included=False means they haven't appeared in a report yet.
        confirmed_unreported: list[TaskItem] = [
            t for t in existing_tasks if not t.get("report_included", True)
        ]

        # ── Step 2: Extract action items from standup/blockers only ──────────
        # Sprint-discuss tasks come exclusively from the interactive flow above;
        # we no longer auto-extract from sprint-discuss to avoid vague tasks.
        standup_blocker_msgs = {
            src: msgs
            for src, msgs in state.get("raw_messages", {}).items()
            if not src.startswith("sprint-discuss")
        }
        raw_items = await extract_action_items(
            state.get("summary", ""),
            standup_blocker_msgs,
        )

        # ── Step 3: Create threads for new standup/blocker action items ───────
        pipeline_new_tasks: list[TaskItem] = []
        for item in raw_items:
            task_id = next_task_id(existing_tasks + pipeline_new_tasks)
            task: TaskItem = {
                "id": task_id,
                "title": item.get("title", "Untitled task"),
                "owner": item.get("owner", "unassigned"),
                "status": "open",
                "thread_id": None,
                "created_date": str(date.today()),
                "report_included": True,  # being added in this report run
            }

            thread_id = await create_task_thread(tasks_channel, task)
            task["thread_id"] = thread_id

            pipeline_new_tasks.append(task)
            existing_tasks.append(task)

        # ── Step 4: Mark confirmed tasks as reported ──────────────────────────
        for task in existing_tasks:
            if not task.get("report_included", True):
                task["report_included"] = True

        # ── Persist ───────────────────────────────────────────────────────────
        sprint_data["tasks"] = existing_tasks
        save_sprint_state(sprint_data)

        # new_tasks for the report = confirmed interactive tasks + pipeline tasks
        new_tasks = confirmed_unreported + pipeline_new_tasks
        logger.info(
            "Task node complete — %d confirmed + %d pipeline = %d new tasks",
            len(confirmed_unreported), len(pipeline_new_tasks), len(new_tasks),
        )

        return {
            **state,
            "tasks": existing_tasks,
            "new_tasks": new_tasks,
        }

    return task_node
