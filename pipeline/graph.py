"""
graph.py — LangGraph pipeline assembly

Wires the four scrum nodes into a directed graph:
  ingest → summarize → tasks → report

Each node is created via its factory function so Discord channel objects
are properly bound at runtime (after the bot connects).
"""

import logging
from typing import Optional

import discord
from langgraph.graph import StateGraph, END

from pipeline.schema import ScrumState, empty_state
from pipeline.ingest import make_ingest_node
from pipeline.summarize import summarize_node
from pipeline.story_splitter import story_splitter_node
from pipeline.task_manager import make_task_node
from pipeline.report_writer import make_report_node

logger = logging.getLogger(__name__)


def build_pipeline(
    guild: discord.Guild,
    tasks_channel: discord.TextChannel,
    ai_report_channel: discord.TextChannel,
    changelog_channel: Optional[discord.TextChannel] = None,
) -> StateGraph:
    """
    Assemble and compile the full scrum pipeline graph.

    Args:
        guild:              The Discord Guild (server) to read messages from
        tasks_channel:      #tasks channel — where task threads are created
        ai_report_channel:  #ai-report channel — where the report is posted
        changelog_channel:  #changelog channel — optional brief update post

    Returns:
        A compiled LangGraph runnable
    """
    graph = StateGraph(ScrumState)

    graph.add_node("ingest",         make_ingest_node(guild))
    graph.add_node("summarize",      summarize_node)
    graph.add_node("story_splitter", story_splitter_node)
    graph.add_node("task_manager",   make_task_node(tasks_channel))
    graph.add_node("report",         make_report_node(ai_report_channel, changelog_channel))

    graph.set_entry_point("ingest")
    graph.add_edge("ingest",         "summarize")
    graph.add_edge("summarize",      "story_splitter")
    graph.add_edge("story_splitter", "task_manager")
    graph.add_edge("task_manager",   "report")
    graph.add_edge("report",         END)

    return graph.compile()


async def run_daily_pipeline(
    guild: discord.Guild,
    tasks_channel: discord.TextChannel,
    ai_report_channel: discord.TextChannel,
    changelog_channel: Optional[discord.TextChannel] = None,
    since_hours: int = 24,
) -> ScrumState:
    """
    Run the full daily scrum pipeline and return the final state.
    Safe to call from APScheduler or a Discord command handler.
    """
    pipeline = build_pipeline(guild, tasks_channel, ai_report_channel, changelog_channel)
    initial_state = empty_state(fetch_since_hours=since_hours)

    logger.info("Starting scrum pipeline (last %dh)", since_hours)
    final_state = await pipeline.ainvoke(initial_state)
    logger.info("Scrum pipeline complete")

    return final_state


async def run_sprint_report(
    guild: discord.Guild,
    tasks_channel: discord.TextChannel,
    ai_report_channel: discord.TextChannel,
    changelog_channel: Optional[discord.TextChannel] = None,
) -> ScrumState:
    """
    Weekly sprint report — fetches the last 7 days of messages.
    """
    return await run_daily_pipeline(
        guild, tasks_channel, ai_report_channel, changelog_channel,
        since_hours=168,  # 7 days
    )
