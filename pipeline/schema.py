"""
Shared state schema for the LangGraph scrum pipeline.
All nodes read from and write to ScrumState.
"""

from typing import TypedDict, Optional
from datetime import date


class TaskItem(TypedDict):
    id: str                  # e.g. "T7"
    title: str
    owner: str               # Discord username or "unassigned"
    status: str              # "open" | "in_progress" | "done" | "blocked"
    thread_id: Optional[int] # Discord thread ID once created
    created_date: str        # ISO date string


class UserStory(TypedDict):
    title: str               # "As a [user], I can [action] so that [value]"
    source: str              # "sprint-discuss/<thread-name>"
    acceptance_criteria: list[str]
    subtasks: list[dict]     # [{"title": str, "owner": str}]


class ScrumState(TypedDict):
    # --- Ingest ---
    raw_messages: dict[str, list[str]]   # {"channel/thread": ["msg1", "msg2"]}
    fetch_since_hours: int               # how many hours back to fetch

    # --- Summarize ---
    summary: str                         # free-text digest from Claude
    decisions: list[str]                 # bullet list of locked decisions
    blockers: list[str]                  # flagged blockers

    # --- Story splitting (PO + SM) ---
    user_stories: list[UserStory]        # stories extracted from #sprint-discuss

    # --- Tasks ---
    tasks: list[TaskItem]                # current sprint task list
    new_tasks: list[TaskItem]            # tasks created this run

    # --- Report ---
    report_md: str                       # full markdown for TEAM_LOG.md entry
    report_date: str                     # ISO date string


def empty_state(fetch_since_hours: int = 24) -> ScrumState:
    """Return a clean ScrumState to start a pipeline run."""
    return ScrumState(
        raw_messages={},
        fetch_since_hours=fetch_since_hours,
        summary="",
        decisions=[],
        blockers=[],
        user_stories=[],
        tasks=[],
        new_tasks=[],
        report_md="",
        report_date=str(date.today()),
    )
