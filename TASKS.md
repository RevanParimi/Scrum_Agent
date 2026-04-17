# Task Tracker

Canonical task list for the Scrum Agent project. Updated manually or via sprint reset.

---

## Sprint 3 — Active Tasks (2026-04-12 → 2026-04-25)

| ID | Title | Team | Owner | Status |
|----|-------|------|-------|--------|
| T1 | Verify alternate signals | Research | Siva Sanka | open |
| T2 | Design Agent 01 database schema | Infrastructure | Prudhvi | open |
| T3 | Implement NSE/BSE API integration | Data | unassigned | open |
| T4 | Integrate AMFI website data | Data | unassigned | open |
| T5 | Build broker API connectors | Data | unassigned | open |
| T6 | Implement sector weightage logic | Agent | Akhil | open |
| T7 | Implement optimistic agentic approach | Agent | Akhil | open |

---

## UI Dashboard — Completed

These features are built and running at `http://localhost:5050` (`python ui/app.py`).

| # | Feature | File(s) |
|---|---------|---------|
| ✅ | Flask app serving sprint state + TEAM_LOG.md | `ui/app.py` |
| ✅ | Dark-theme dashboard with sidebar navigation | `ui/templates/dashboard.html`, `ui/static/style.css` |
| ✅ | Sprint stats row (Open / Done / Blocked / Unassigned) | `ui/templates/dashboard.html` |
| ✅ | Tasks grouped by module team with status badges | `ui/templates/dashboard.html` |
| ✅ | Per-team detail page (`/team/<key>`) | `ui/templates/team.html` |
| ✅ | Pending pipeline proposals section (shows P1, P2… awaiting Discord confirm) | `ui/templates/dashboard.html` |
| ✅ | TEAM_LOG.md rendered as HTML with styled tables | `ui/templates/dashboard.html` |
| ✅ | Responsive layout (sidebar hidden on mobile) | `ui/static/style.css` |

---

## UI Dashboard — Planned (not yet built)

| # | Feature | Notes |
|---|---------|-------|
| ⬜ | Task status updates from UI | Currently read-only; status is updated by replying in the Discord task thread |
| ⬜ | Authentication / login wall | No auth yet — UI is intended for internal/local use |
| ⬜ | Auto-refresh / WebSocket | Page requires manual reload to reflect new tasks or proposals |
| ⬜ | Burndown chart per team | Velocity tracking across sprints; needs sprint history in state |
| ⬜ | Sprint selector (view past sprints) | TEAM_LOG.md has history but no UI filter for it |
| ⬜ | Owner assignment from UI | Allow assigning `unassigned` tasks directly in the browser |
| ⬜ | Proposal confirm/reject buttons | Mirror the Discord `✅ Px / ❌ Px` flow in the browser |

---

## Bot & Pipeline — Completed

| # | Feature | File(s) |
|---|---------|---------|
| ✅ | Task deduplication before creation | `pipeline/task_manager.py → is_duplicate_task()` |
| ✅ | Propose-first flow: pipeline posts proposals to #sprint-discuss | `pipeline/task_manager.py → post_task_proposals()` |
| ✅ | Team-lead confirmation: `✅ Px` / `❌ Px` in #sprint-discuss | `bot.py → _handle_proposal_reply()` |
| ✅ | Module team routing (keyword + member map) | `pipeline/teams.py` |
| ✅ | `!cleanup-tasks` admin command (dedup on demand) | `bot.py → cmd_cleanup_tasks()` |
| ✅ | `#sprint-discuss` name-based fallback when channel ID unset | `bot.py → on_message()` |
| ✅ | Per-message agent action logging in console | `bot.py → _handle_sprint_discuss()` |
| ✅ | `team` field on all tasks in sprint_state.json | `pipeline/task_manager.py`, `state/sprint_state.json` |

---

## Bot & Pipeline — Planned

| # | Feature | Notes |
|---|---------|-------|
| ⬜ | Proposal expiry (24h auto-reject) | `pending_proposals[]` entries older than 24h should be cleaned up on each pipeline run |
| ⬜ | Task status sync from Discord thread replies | `done` reply in task thread → update `status` in sprint_state.json |
| ⬜ | Jira two-way sync per team | Each team maps to a separate Jira project key |
| ⬜ | GraphRAG: tasks as graph nodes | Phase 2 — see `docs/ARCHITECTURE.md §10` |
| ⬜ | Team velocity / burndown reporting | Track done-per-sprint per team; add to weekly report |
| ⬜ | Slack bridge for proposals | Post `✅/❌` proposal flow to Slack if team prefers it |
