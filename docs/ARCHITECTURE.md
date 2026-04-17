# Architecture

System design, data flows, module responsibilities, and key design decisions for the Scrum Agent.

---

## 1. System overview

```
┌─────────────────────────────────────────────────────────────┐
│                       EXTERNAL WORLD                         │
│   Discord Server              Groq (LLaMA 3.3-70B)          │
│   (messages, threads)         (inference)                    │
└───────┬───────────────────────────────────────┬─────────────┘
        │                                       │
        ▼                                       ▼
┌──────────────────────────────────────────────────────────┐
│               bot.py  (discord.py)                        │
│                                                           │
│  on_message → auto-thread + conversational agent          │
│  on_message → proposal confirm/reject (✅/❌ Px)          │
│  !report / !sprint / !tasks / !status / !cleanup-tasks    │
│  APScheduler → daily 09:00 + weekly Fri 18:00             │
└──────────────────────┬───────────────────────────────────┘
                       │ calls pipeline functions directly
                       ▼
┌──────────────────────────────────────────────────────────┐
│            Python AI Pipeline  (LangGraph)                │
│                                                           │
│  graph.py: ingest → summarize → task_manager → report     │
│                                                           │
│  ingest.py          fetch Discord messages (24h / 7d)     │
│  summarize.py       Groq LLM → summary, decisions,        │
│                     blockers                              │
│  task_manager.py    extract candidates → deduplicate →    │
│                     propose to #sprint-discuss            │
│  thread_agent.py    real-time conversational SM agent     │
│  task_proposer.py   single-message task detection         │
│  report_writer.py   markdown → TEAM_LOG.md + git push     │
│  teams.py           module team definitions               │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  state/sprint_state.json                                  │
│  ├── tasks[]            canonical task list               │
│  ├── pending_proposals[]  awaiting team-lead confirm      │
│  ├── pending_confirmations{}  interactive flow state      │
│  └── sprint metadata                                      │
│                                                           │
│  TEAM_LOG.md            auto-appended daily report        │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  ui/app.py  (Flask — localhost:5050)                      │
│  ├── /               sprint dashboard                     │
│  └── /team/<key>     per-team task view                   │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Module team structure

Tasks are routed to one of four teams at creation time.

```
pipeline/teams.py
│
├── data          📊  NSE/BSE API, AMFI data, broker connectors
├── agent         🤖  sector weightage, agentic optimization
├── infrastructure 🏗️  database schema, system architecture
└── research      🔬  signal verification, market strategy
```

Routing logic (in order of precedence):
1. If `owner` is a known team member → use their team
2. Keyword match on task title → `get_team_for_task_title()`
3. Default → `data`

To add a member to a team, edit the `members` list in `pipeline/teams.py`.

---

## 3. Data flow — Daily pipeline (9 AM)

```
APScheduler fires → bot._run_daily()
      │
      ▼
pipeline/graph.py → run_daily_pipeline(guild, tasks_ch, ai_report_ch,
                                        changelog_ch, sprint_discuss_ch)
      │
      ├── ingest_node
      │     reads #standup, #blockers, #sprint-discuss, #tasks (24h)
      │     returns raw_messages { channel: [msg, ...] }
      │
      ├── summarize_node
      │     Groq LLaMA → summary (str), decisions ([]), blockers ([])
      │
      ├── task_manager_node
      │     extract_action_items(summary, standup+blockers only)
      │       → [{ title, owner }]
      │     deduplicate against existing tasks
      │     IF sprint_discuss_channel:
      │       post proposals to #sprint-discuss as P1, P2, ...
      │       save to pending_proposals[] in sprint_state.json
      │     ELSE (fallback):
      │       create task threads in #tasks immediately
      │     mark confirmed interactive tasks as report_included=true
      │
      └── report_writer_node
            build markdown report
            append to TEAM_LOG.md
            git commit + push
            post to #ai-report (chunked if > 2000 chars)
            post summary to #changelog
```

---

## 4. Data flow — Task proposal confirmation

```
bot posts in #sprint-discuss:
  "📋 New task proposals: [P1] Implement NSE/BSE API ..."
           │
           ▼
Team lead replies: "✅ P1"
           │
           ▼
bot.py → on_message → _handle_proposal_reply()
  ├── regex: ✅ P1 → confirm_match
  ├── lookup pending_proposals[] for proposal_id = "P1"
  ├── create task (next_task_id, today's date, team from proposal)
  ├── create_task_thread() in #tasks
  ├── remove P1 from pending_proposals
  └── reply: "✅ T8 created: Implement NSE/BSE API (team: data)"
```

Rejection flow:
```
Team lead replies: "❌ P1"
  └── proposal removed from pending_proposals, no task created
```

---

## 5. Data flow — Conversational agent (`#sprint-discuss`)

```
Team member posts a message
          │
          ├── Main channel + len ≥ 20? → auto-create thread (1440 min)
          │
          ├── Starts with ✅/❌ Px? → _handle_proposal_reply() (returns early)
          │
          └── _handle_sprint_discuss(message)
                    │
                    ├── fetch_thread_history()     last 15 messages
                    ├── extract_attachment_text()  read shared files
                    ├── load pending_confirmations from state
                    ├── load open tasks for context
                    │
                    ▼
              pipeline/thread_agent.py → run_thread_agent()
                    │   builds context block (history + tasks + pending)
                    │   Groq LLaMA → JSON action
                    │
                    ├── "propose_task"    → reply + save pending_confirmation
                    ├── "confirm_task"    → create_confirmed_task() + reply
                    ├── "reject_task"     → clear pending + optional reply
                    ├── "ask_clarification" → reply only
                    ├── "answer_question" → reply only
                    ├── "note_decision"   → reply only
                    └── "silent"          → no action (logged)
```

---

## 6. Task deduplication

Deduplication runs in `pipeline/task_manager.py → is_duplicate_task()` before any task is created.

Algorithm:
```python
def _normalize(text):
    # lowercase → strip punctuation → collapse whitespace
    ...

def is_duplicate_task(title, existing_tasks):
    norm_new = _normalize(title)
    for task in existing_tasks:
        norm_existing = _normalize(task["title"])
        if norm_new == norm_existing:
            return True
        # Substring match for long titles (> 10 chars)
        if len(norm_new) > 10 and (norm_new in norm_existing or norm_existing in norm_new):
            return True
    return False
```

`deduplicate_task_list()` is also available for admin cleanup via `!cleanup-tasks`.

---

## 7. State schema (`state/sprint_state.json`)

```json
{
  "sprint_number": 3,
  "sprint_start": "2026-04-12",
  "sprint_end": "2026-04-25",
  "teams": { ... },
  "tasks": [
    {
      "id": "T1",
      "title": "Verify alternate signals",
      "owner": "Siva Sanka",
      "team": "research",
      "status": "open",
      "thread_id": 1492035688785252434,
      "created_date": "2026-04-10",
      "report_included": true
    }
  ],
  "pending_proposals": [
    {
      "proposal_id": "P1",
      "title": "Implement NSE/BSE API",
      "owner": "unassigned",
      "team": "data",
      "proposed_date": "2026-04-17"
    }
  ],
  "pending_confirmations": {
    "1234567890": {
      "task_title": "Build backtesting harness",
      "task_owner": "Akhil"
    }
  },
  "last_report_date": "2026-04-17",
  "last_ingested_message_ids": {}
}
```

`tasks[].team` is the key addition — maps every task to one of the four module teams.  
`pending_proposals[]` holds pipeline-extracted candidates awaiting team-lead confirmation.

---

## 8. Web dashboard (`ui/`)

```
ui/
├── app.py                 Flask application (port 5050)
├── templates/
│   ├── dashboard.html     Main sprint view
│   └── team.html          Per-team view
└── static/
    └── style.css          Dark theme CSS variables
```

Routes:
- `GET /` — full sprint dashboard (stats, tasks by team, proposals, TEAM_LOG.md)
- `GET /team/<team_key>` — per-team task list

Data sources (read-only, no DB needed):
- `state/sprint_state.json` — tasks and proposals
- `TEAM_LOG.md` — rendered via markdown2
- `pipeline/teams.py` — team metadata

---

## 9. Key design decisions

| Decision | Rationale |
|----------|-----------|
| Propose-first task creation | Prevents auto-accumulation of duplicate/wrong tasks; team leads stay in control |
| Deduplication before proposal | Same task shouldn't appear in multiple pipeline runs; normalized string match is cheap and reliable |
| `#sprint-discuss` as confirmation channel | Natural place — team leads already use it; no new channel or command needed |
| JSON state over SQLite | Human-readable, easy to inspect/edit, zero infra; race conditions are rare with single-process bot |
| team field on tasks | Enables per-team filtering in UI and reports without separate tables |
| Flask dashboard | No build step, renders TEAM_LOG.md directly; replaces need for external project management view |
| Groq / LLaMA 3.3-70B | Fast inference, generous free tier; used for both summarization and conversational agent |

---

## 10. Phase 2 — Planned

- **GraphRAG:** Tasks as graph nodes with edges (task → story → epic → sprint) for richer queries
- **Team velocity tracking:** Burndown per module team across sprints
- **Jira sync:** Two-way task sync per team (Data team → Jira project SCRUM-DATA, etc.)
- **Slack bridge:** Post proposals to Slack if team leads prefer it over Discord
