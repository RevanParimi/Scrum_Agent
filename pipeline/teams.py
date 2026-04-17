"""
teams.py — Scrum team module definitions.

Defines the four module teams and their responsibilities. Used by
task_manager, report_writer, and the web UI to group tasks by team.
"""

from __future__ import annotations

TEAMS: dict[str, dict] = {
    "data": {
        "name": "Data Team",
        "emoji": "📊",
        "focus": "Market data ingestion and broker connectivity",
        "channels": ["#tasks", "#standup"],
        "members": [],
    },
    "agent": {
        "name": "Agent Team",
        "emoji": "🤖",
        "focus": "Agent logic, sector weightage, and agentic optimization",
        "channels": ["#tasks", "#standup"],
        "members": ["Akhil"],
    },
    "infrastructure": {
        "name": "Infrastructure Team",
        "emoji": "🏗️",
        "focus": "Database schema, system architecture, and DevOps",
        "channels": ["#tasks", "#standup"],
        "members": ["Prudhvi"],
    },
    "research": {
        "name": "Research Team",
        "emoji": "🔬",
        "focus": "Signal verification, market research, and strategy",
        "channels": ["#tasks", "#standup"],
        "members": ["Siva Sanka"],
    },
}

MEMBER_TEAM_MAP: dict[str, str] = {
    member.lower(): team_key
    for team_key, team in TEAMS.items()
    for member in team["members"]
}


def get_team_for_member(display_name: str) -> str:
    """Return team key for a member's display name, or 'data' as default."""
    return MEMBER_TEAM_MAP.get(display_name.lower(), "data")


def get_team_for_task_title(title: str) -> str:
    """Infer a team from a task title using keyword heuristics."""
    title_lower = title.lower()
    if any(k in title_lower for k in ("api", "amfi", "broker", "nse", "bse", "data", "ingest", "fetch")):
        return "data"
    if any(k in title_lower for k in ("agent", "weightage", "sector", "optimistic", "agentic", "model")):
        return "agent"
    if any(k in title_lower for k in ("schema", "database", "db", "infra", "architecture", "deploy")):
        return "infrastructure"
    if any(k in title_lower for k in ("signal", "verify", "research", "strategy", "backtest")):
        return "research"
    return "data"
