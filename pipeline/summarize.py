"""
summarize.py — LangGraph Node 2

Sends the raw Discord messages to Claude with the scrum master system prompt.
Extracts: free-text summary, decisions list, blockers list.
"""

import json
import logging
import os
from pathlib import Path

#from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from pipeline.schema import ScrumState

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "scrum_master.md"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048

# Hard cap on context fed to Claude (characters) to stay within token limits
MAX_CONTEXT_CHARS = 60_000


def load_system_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "You are an expert AI Scrum Master. Be concise and actionable."


def build_context_block(raw_messages: dict[str, list[str]]) -> str:
    """Flatten channel→messages dict into a readable text block for Claude."""
    parts = []
    total_chars = 0
    for source, messages in raw_messages.items():
        block = f"\n### {source}\n" + "\n".join(messages)
        if total_chars + len(block) > MAX_CONTEXT_CHARS:
            logger.warning("Context truncated at source: %s", source)
            break
        parts.append(block)
        total_chars += len(block)
    return "\n".join(parts)


def parse_structured_response(text: str) -> tuple[str, list[str], list[str]]:
    """
    Extract summary, decisions, and blockers from Claude's JSON response.
    Falls back to raw text if JSON parsing fails.
    """
    try:
        # Claude is instructed to respond with a JSON block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
            summary = data.get("summary", text)
            decisions = data.get("decisions", [])
            blockers = data.get("blockers", [])
            return summary, decisions, blockers
    except json.JSONDecodeError:
        logger.warning("Could not parse JSON from Claude response, using raw text")

    # Fallback: return full text as summary with empty lists
    return text.strip(), [], []


async def summarize_node(state: ScrumState) -> ScrumState:
    """LangGraph node — calls Claude to summarize Discord context."""

    raw_messages = state.get("raw_messages", {})
    if not raw_messages:
        logger.info("No messages to summarize, skipping")
        return {**state, "summary": "No activity in this period.", "decisions": [], "blockers": []}

    system_prompt = load_system_prompt()
    context_block = build_context_block(raw_messages)

    human_message = f"""Here are the recent Discord messages from the team:

{context_block}

---
Respond ONLY with valid JSON in this exact format:
{{
  "summary": "2-4 sentence digest of what the team discussed and accomplished",
  "decisions": ["Decision 1", "Decision 2"],
  "blockers": ["Blocker 1", "Blocker 2"]
}}

If there are no decisions or blockers, return empty arrays [].
"""

    #llm = ChatAnthropic(
    #    model=MODEL,
    #    max_tokens=MAX_TOKENS,
    #    anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
    #)
    from langchain_groq import ChatGroq
    llm = ChatGroq(
        model="llama-3.3-70b-versatile", 
        api_key=os.environ["GROQ_API_KEY"]
    )

    logger.info("Calling Claude for summarization (%d chars of context)", len(context_block))
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_message),
    ])

    summary, decisions, blockers = parse_structured_response(response.content)
    logger.info("Summarize complete — %d decisions, %d blockers", len(decisions), len(blockers))

    return {
        **state,
        "summary": summary,
        "decisions": decisions,
        "blockers": blockers,
    }
