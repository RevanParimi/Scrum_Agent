"""
task_proposer.py — Real-time task detection for #sprint-discuss messages.

Called from bot.py's on_message handler. Asks an LLM whether a message
contains a concrete task proposal worth surfacing to the team for confirmation.
"""

import json
import logging
import os

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a Scrum Master assistant monitoring a sprint planning discussion channel.

Your job: decide if a message proposes concrete work that should become a tracked sprint task.

PROPOSE a task ONLY when the message clearly describes:
- Specific, actionable work with a deliverable outcome
- Something someone would actually build, implement, fix, or complete
- Enough definition to start working on

DO NOT propose a task for:
- Decisions to IGNORE, skip, or not do something ("we should ignore X", "don't worry about Y")
- Vague future ideas without commitment ("maybe we could consider...", "might be nice to...")
- Status updates on already-finished work
- General discussion, opinions, or questions
- "Verify" or "check" something that is clearly part of an ongoing conversation, not assigned work
- Anything that doesn't produce a concrete deliverable

When in doubt, respond with {"propose": false}. Only propose if you are confident.

If warranted, respond with JSON:
{"propose": true, "title": "<short imperative phrase, ≤8 words>", "owner": "<discord_username or unassigned>"}

If not warranted, respond with:
{"propose": false}

Respond ONLY with valid JSON. No explanation."""


async def analyze_for_task(message_content: str, author: str) -> dict | None:
    """
    Analyze a sprint-discuss message to determine if it warrants a task proposal.

    Returns {"title": str, "owner": str} if a task should be proposed, else None.
    """
    if len(message_content.strip()) < 15:
        return None  # too short to be meaningful

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.environ["GROQ_API_KEY"],
        max_tokens=128,
    )

    prompt = f"Author: {author}\nMessage: {message_content}"

    try:
        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        text = response.content
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
            if data.get("propose"):
                return {
                    "title": data.get("title", "Unnamed task"),
                    "owner": data.get("owner", "unassigned"),
                }
    except Exception as exc:
        logger.warning("Task proposer LLM failed: %s", exc)

    return None
