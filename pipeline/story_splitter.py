"""
story_splitter.py — LangGraph Node 2.5 (between summarize and tasks)

Reads messages from #sprint-discuss threads and applies dual PO + SM logic:
  - Product Owner: extracts user stories with acceptance criteria
  - Scrum Master: splits each story into concrete subtasks with owners

Only sprint-discuss content is processed; standup/blockers are ignored here.
"""

import json
import logging
import os
from pathlib import Path

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.schema import ScrumState, UserStory

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "story_splitter.md"
MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 2048


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _extract_discuss_messages(raw_messages: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return only sprint-discuss channel and thread messages."""
    return {
        src: msgs
        for src, msgs in raw_messages.items()
        if src.startswith("sprint-discuss")
    }


async def split_stories(raw_messages: dict[str, list[str]]) -> list[UserStory]:
    """
    Send sprint-discuss content to the LLM acting as PO + SM.
    Returns a list of UserStory dicts.
    """
    discuss_msgs = _extract_discuss_messages(raw_messages)

    if not discuss_msgs:
        logger.info("No sprint-discuss messages — skipping story splitting")
        return []

    # Format messages by thread for the LLM
    sections = []
    for src, msgs in discuss_msgs.items():
        thread_label = src.replace("sprint-discuss/", "Thread: ").replace("sprint-discuss", "Main channel")
        sections.append(f"=== {thread_label} ===\n" + "\n".join(msgs))
    user_content = "\n\n".join(sections)

    llm = ChatGroq(
        model=MODEL,
        api_key=os.environ["GROQ_API_KEY"],
        max_tokens=MAX_TOKENS,
    )

    response = await llm.ainvoke([
        SystemMessage(content=_load_system_prompt()),
        HumanMessage(content=user_content),
    ])

    try:
        text = response.content
        start = text.find("[")
        end = text.rfind("]") + 1
        if start != -1 and end > start:
            stories = json.loads(text[start:end])
            logger.info("Story splitter extracted %d user stories", len(stories))
            return stories
    except json.JSONDecodeError:
        logger.warning("Failed to parse story JSON from LLM")

    return []


# ── LangGraph node ────────────────────────────────────────────────────────────

async def story_splitter_node(state: ScrumState) -> ScrumState:
    """
    LangGraph node: reads sprint-discuss messages, returns user_stories.
    Registered directly (no factory needed — no Discord channel binding required).
    """
    stories = await split_stories(state.get("raw_messages", {}))
    return {**state, "user_stories": stories}
