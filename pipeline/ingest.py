"""
ingest.py — LangGraph Node 1

Reads recent messages from all configured Discord channels and their active
threads. Returns raw_messages dict keyed by "channel" or "channel/thread".
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord

from pipeline.schema import ScrumState

logger = logging.getLogger(__name__)

# Channel names we care about (must match your Discord server exactly)
WATCHED_CHANNELS = {
    "sprint-discuss",
    "standup",
    "tasks",
    "blockers",
}

# Max messages to fetch per channel / thread
CHANNEL_MSG_LIMIT = 100
THREAD_MSG_LIMIT = 50


async def fetch_channel_messages(
    channel: discord.TextChannel,
    after: Optional[datetime] = None,
    limit: int = CHANNEL_MSG_LIMIT,
) -> list[str]:
    """Fetch text messages from a channel, newest-last."""
    messages = []
    try:
        async for msg in channel.history(limit=limit, after=after, oldest_first=True):
            if msg.content.strip():
                author = msg.author.display_name
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                messages.append(f"[{ts}] {author}: {msg.content}")
    except discord.Forbidden:
        logger.warning("No read permission for channel: %s", channel.name)
    except Exception as exc:
        logger.error("Error reading channel %s: %s", channel.name, exc)
    return messages


async def fetch_thread_messages(
    thread: discord.Thread,
    after: Optional[datetime] = None,
    limit: int = THREAD_MSG_LIMIT,
) -> list[str]:
    """Fetch text messages from a thread, newest-last."""
    messages = []
    try:
        async for msg in thread.history(limit=limit, after=after, oldest_first=True):
            if msg.content.strip():
                author = msg.author.display_name
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                messages.append(f"[{ts}] {author}: {msg.content}")
    except discord.Forbidden:
        logger.warning("No read permission for thread: %s", thread.name)
    except Exception as exc:
        logger.error("Error reading thread %s: %s", thread.name, exc)
    return messages


async def fetch_all_context(guild: discord.Guild, since_hours: int = 24) -> dict[str, list[str]]:
    """
    Walk all watched channels and their active threads.
    Returns:
        {
            "standup": ["[2026-03-29 09:00] alice: working on auth..."],
            "sprint-discuss/oauth-flow": ["[2026-03-29 10:00] bob: ..."],
            ...
        }
    """
    after_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    context: dict[str, list[str]] = {}

    for channel in guild.text_channels:
        if channel.name not in WATCHED_CHANNELS:
            continue

        # Main channel messages
        msgs = await fetch_channel_messages(channel, after=after_dt)
        if msgs:
            context[channel.name] = msgs

        # Active threads inside this channel
        try:
            for thread in channel.threads:
                # Only fetch threads that had activity in the window
                if thread.archive_timestamp and thread.archive_timestamp < after_dt:
                    continue
                thread_msgs = await fetch_thread_messages(thread, after=after_dt)
                if thread_msgs:
                    key = f"{channel.name}/{thread.name}"
                    context[key] = thread_msgs
        except Exception as exc:
            logger.error("Error listing threads for %s: %s", channel.name, exc)

    logger.info("Ingest complete — %d channel/thread contexts fetched", len(context))
    return context


# ── LangGraph node ────────────────────────────────────────────────────────────

def make_ingest_node(guild: discord.Guild):
    """
    Factory that binds the Discord guild to a LangGraph-compatible node.

    Usage:
        graph.add_node("ingest", make_ingest_node(guild))
    """
    async def ingest_node(state: ScrumState) -> ScrumState:
        since_hours = state.get("fetch_since_hours", 24)
        raw_messages = await fetch_all_context(guild, since_hours=since_hours)
        return {**state, "raw_messages": raw_messages}

    return ingest_node
