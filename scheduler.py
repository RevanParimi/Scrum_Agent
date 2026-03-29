"""
scheduler.py — APScheduler cron jobs

Runs inside the same process as the Discord bot.
All jobs are async and call the LangGraph pipeline.

Schedule (configurable via env):
  - Daily digest:      09:00 IST  (TIMEZONE=Asia/Kolkata)
  - Weekly report:     Friday 18:00 IST
  - On-demand:         !report command in Discord (handled in bot.py)
"""

import logging
import os
from typing import Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")


def create_scheduler(
    daily_pipeline_fn: Callable[[], Awaitable[None]],
    weekly_pipeline_fn: Callable[[], Awaitable[None]],
) -> AsyncIOScheduler:
    """
    Build and return a configured APScheduler instance.

    Args:
        daily_pipeline_fn:   async callable — runs the 24h scrum digest
        weekly_pipeline_fn:  async callable — runs the 7-day sprint report

    The scheduler is NOT started here — call scheduler.start() in bot.py
    after the Discord client is ready.
    """
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Daily standup digest — 9:00 AM local time
    scheduler.add_job(
        daily_pipeline_fn,
        trigger=CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        id="daily_digest",
        name="Daily scrum digest",
        replace_existing=True,
        misfire_grace_time=300,   # 5-minute grace if process was sleeping
    )
    logger.info("Scheduled daily digest at 09:00 %s", TIMEZONE)

    # Weekly sprint report — Friday 6:00 PM local time
    scheduler.add_job(
        weekly_pipeline_fn,
        trigger=CronTrigger(day_of_week="fri", hour=18, minute=0, timezone=TIMEZONE),
        id="weekly_report",
        name="Weekly sprint report",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Scheduled weekly report on Fridays at 18:00 %s", TIMEZONE)

    return scheduler
