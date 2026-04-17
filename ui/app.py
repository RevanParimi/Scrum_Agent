"""
ui/app.py — Web dashboard for the Scrum Agent.

Run with:  python -m ui.app   (from the project root)
Or:        python ui/app.py

Shows:
  - Sprint overview (current sprint, dates, open task count)
  - Tasks grouped by module team
  - Pending proposals awaiting team-lead confirmation
  - TEAM_LOG.md rendered as HTML
"""

import json
import sys
from pathlib import Path

# Make the project root importable regardless of how the file is run
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, render_template, redirect, url_for
import markdown2

from pipeline.teams import TEAMS

app = Flask(__name__)

STATE_PATH    = ROOT / "state" / "sprint_state.json"
TEAM_LOG_PATH = ROOT / "TEAM_LOG.md"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"tasks": [], "sprint_number": "?", "pending_proposals": []}


def team_display(team_key: str) -> dict:
    return TEAMS.get(team_key, {"name": team_key.title(), "emoji": "📌", "focus": ""})


@app.route("/")
def dashboard():
    state      = load_state()
    all_tasks  = state.get("tasks", [])
    proposals  = state.get("pending_proposals", [])

    # Group tasks by team
    by_team: dict[str, list] = {}
    for task in all_tasks:
        key = task.get("team", "unassigned")
        by_team.setdefault(key, []).append(task)

    # Stats
    open_count     = sum(1 for t in all_tasks if t.get("status") != "done")
    done_count     = sum(1 for t in all_tasks if t.get("status") == "done")
    blocked_count  = sum(1 for t in all_tasks if t.get("status") == "blocked")
    unassigned_cnt = sum(1 for t in all_tasks if t.get("owner") == "unassigned" and t.get("status") != "done")

    # TEAM_LOG as HTML
    log_html = ""
    if TEAM_LOG_PATH.exists():
        md_text  = TEAM_LOG_PATH.read_text(encoding="utf-8")
        log_html = markdown2.markdown(md_text, extras=["tables", "fenced-code-blocks"])

    return render_template(
        "dashboard.html",
        sprint_number  = state.get("sprint_number", "?"),
        sprint_start   = state.get("sprint_start", "—"),
        sprint_end     = state.get("sprint_end", "—"),
        open_count     = open_count,
        done_count     = done_count,
        blocked_count  = blocked_count,
        unassigned_cnt = unassigned_cnt,
        by_team        = by_team,
        proposals      = proposals,
        teams          = TEAMS,
        team_display   = team_display,
        log_html       = log_html,
        all_tasks      = all_tasks,
    )


@app.route("/team/<team_key>")
def team_view(team_key: str):
    state     = load_state()
    all_tasks = state.get("tasks", [])
    tasks     = [t for t in all_tasks if t.get("team") == team_key]
    team_info = team_display(team_key)
    return render_template(
        "team.html",
        team_key  = team_key,
        team_info = team_info,
        tasks     = tasks,
        sprint_number = state.get("sprint_number", "?"),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5050)
