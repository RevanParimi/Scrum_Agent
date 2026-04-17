"""
thread_agent.py — Conversational sprint-discuss agent.

Reads the full thread history + sprint context before deciding how to respond.
Behaves like a scrum master team member: asks clarifying questions, proposes tasks
for confirmation, answers sprint questions, and stays silent when not needed.
"""

import json
import logging
import os

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a Scrum Master embedded in your team's #sprint-discuss Discord channel.
You are a team member, not a bot. You read the conversation carefully and only contribute when genuinely useful.

Your responsibilities:
1. Identify concrete work commitments → propose tracking them as tasks (after confirming)
2. Ask one clarifying question when a message is ambiguous before assuming it's a task
3. Answer direct sprint questions (task status, owners, blockers, what was decided)
4. Note important decisions the team locks in
5. Stay silent the rest of the time

GOLDEN RULES:
- PROPOSE a task ONLY when someone is clearly committing to do specific, deliverable work
- NEVER propose tasks for: "ignore X", "skip Y", vague ideas, status updates, casual discussion, things the team decided NOT to do
- ALWAYS ask first if you're not sure — one good question beats a wrong task
- Check the thread history: if you already asked about something, don't ask again
- Be brief — max 2 sentences, natural tone, use first names
- When someone shares a file, read it and extract any task commitments from it

PENDING CONFIRMATION:
If context includes "PENDING CONFIRMATION", the latest message may be answering your earlier question.
- Yes signals (yes / yeah / sure / yep / do it / add it / track it / correct / go ahead) → confirm_task
- No signals (no / nah / nope / skip / don't / not a task / just discussion / ignore it) → reject_task
- Ambiguous → silent (wait, don't ask again)

RESPOND with valid JSON only:
{
  "action": "propose_task" | "ask_clarification" | "confirm_task" | "reject_task" | "answer_question" | "note_decision" | "silent",
  "message": "your natural reply (omit entirely if silent)",
  "task_title": "imperative phrase ≤8 words (only for propose_task or confirm_task)",
  "task_owner": "discord_username or unassigned (only for propose_task or confirm_task)"
}"""


async def run_thread_agent(
    message_content: str,
    author: str,
    thread_history: list[str],
    sprint_tasks: list[dict],
    pending_confirmation: dict | None = None,
    attachment_text: str | None = None,
) -> dict:
    """
    Decide how to respond to a message in #sprint-discuss.

    Args:
        message_content:      The incoming message text.
        author:               Display name of the message author.
        thread_history:       Recent messages in the thread, oldest first, formatted as "[Name]: text".
        sprint_tasks:         Current sprint task list from state.
        pending_confirmation: If the bot already asked a yes/no question here, the pending task dict.
        attachment_text:      Extracted text from any file attachment.

    Returns:
        Dict with keys: action, message (optional), task_title (optional), task_owner (optional).
    """
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.environ["GROQ_API_KEY"],
        max_tokens=256,
    )

    # ── Build context sections ─────────────────────────────────────────────────

    history_block = "\n".join(thread_history) if thread_history else "(start of thread)"

    open_tasks = [t for t in sprint_tasks if t.get("status") in ("open", "in_progress")]
    tasks_block = (
        "\n".join(f"  {t['id']}: {t['title']} → {t['owner']}" for t in open_tasks[-10:])
        or "  (none yet)"
    )

    pending_block = ""
    if pending_confirmation:
        pending_block = (
            f"\nPENDING CONFIRMATION: You already asked whether to track "
            f'"{pending_confirmation["task_title"]}" as a task '
            f"for {pending_confirmation['task_owner']}. "
            f"Check if the latest message is answering that.\n"
        )

    attachment_block = ""
    if attachment_text:
        attachment_block = (
            f"\nFILE ATTACHMENT shared by {author}:\n"
            f"{attachment_text[:2000]}\n"
        )

    user_prompt = f"""=== THREAD HISTORY (oldest → latest) ===
{history_block}
{pending_block}{attachment_block}
=== CURRENT SPRINT TASKS ===
{tasks_block}

=== LATEST MESSAGE from {author} ===
{message_content}

Decide what to do."""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        text = response.content
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            result = json.loads(text[start:end])
            logger.info("Thread agent → action: %s", result.get("action", "silent"))
            return result
    except Exception as exc:
        logger.warning("Thread agent failed: %s", exc)

    return {"action": "silent"}
