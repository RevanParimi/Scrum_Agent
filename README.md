# Scrum Agent v2

AI-augmented Scrum Master that lives in Discord — summarises standups, tracks tasks per module team, flags blockers, and surfaces a web dashboard with the full sprint log.

Built on a **Python-first architecture**: discord.py + LangGraph for the bot and AI pipeline, Flask for the web UI.

---

## Architecture at a glance

```
Discord Server
      │
      ▼
┌──────────────────────────────────┐
│   bot.py  (discord.py)            │  Slash commands, auto-thread,
│                                   │  proposal confirm/reject flow
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│   Python AI Pipeline (LangGraph)  │
│                                   │
│   ingest → summarize →            │
│   task_manager → report_writer    │
│                                   │
│   pipeline/teams.py               │  4 module teams
│   pipeline/thread_agent.py        │  Conversational SM agent
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│   state/sprint_state.json         │  Tasks, proposals, sprint meta
│   TEAM_LOG.md                     │  Auto-generated daily log
└──────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│   ui/app.py  (Flask)              │  Web dashboard → localhost:5050
└──────────────────────────────────┘
```

Full design → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
Dev guide   → [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)

---

## Module Teams

Tasks are grouped into four teams. The bot routes new tasks to the correct team automatically based on title keywords.

| Team | Emoji | Focus | Members |
|------|-------|-------|---------|
| **Data** | 📊 | Market data ingestion, NSE/BSE API, broker connectors | *unassigned* |
| **Agent** | 🤖 | Agent logic, sector weightage, agentic optimization | Akhil |
| **Infrastructure** | 🏗️ | Database schema, system architecture | Prudhvi |
| **Research** | 🔬 | Signal verification, strategy | Siva Sanka |

Team definitions live in [`pipeline/teams.py`](pipeline/teams.py) — update members there.

---

## Quick start

### Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.10 |

### 1 — Install

```bash
git clone https://github.com/RevanParimi/Scrum_Agent.git
cd Scrum_Agent

pip install -r requirements.txt
```

### 2 — Environment variables

```bash
cp .env.example .env
# Edit .env — all required fields are marked below
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Bot token from Discord Developer Portal |
| `DISCORD_GUILD_ID` | ✅ | Server ID (Developer Mode → right-click server) |
| `GROQ_API_KEY` | ✅ | From [console.groq.com](https://console.groq.com) |
| `CHANNEL_SPRINT_DISCUSS` | ✅ | ID of `#sprint-discuss` channel |
| `CHANNEL_STANDUP` | ✅ | ID of `#standup` channel |
| `CHANNEL_TASKS` | ✅ | ID of `#tasks` channel |
| `CHANNEL_BLOCKERS` | ✅ | ID of `#blockers` channel |
| `CHANNEL_AI_REPORT` | ✅ | ID of `#ai-report` channel |
| `CHANNEL_CHANGELOG` | ✅ | ID of `#changelog` channel |
| `TIMEZONE` | Optional | Default `Asia/Kolkata` |

### 3 — Run

```bash
# Terminal 1 — Discord bot
python bot.py

# Terminal 2 — Web dashboard (http://localhost:5050)
python ui/app.py
```

---

## Bot commands

| Command | Who | Description |
|---------|-----|-------------|
| `!report` | manage_messages | Trigger immediate daily scrum digest |
| `!sprint` | manage_messages | Trigger 7-day weekly sprint summary |
| `!tasks` | Everyone | List open tasks grouped by team |
| `!status` | Everyone | Bot health + channel bindings |
| `!cleanup-tasks` | manage_messages | Deduplicate the task list and print canonical tasks |

---

## How tasks are created (propose-first flow)

```
Daily pipeline runs (9 AM)
         │
         ▼
Extract candidate tasks from #standup / #blockers
         │
         ▼
Deduplicate — skip anything already tracked
         │
         ▼
Post proposals to #sprint-discuss:
  "📋 New task proposals — please confirm:
     • [P1] Implement NSE/BSE API (owner: unassigned, team: data)
     Reply ✅ P1 to confirm, ❌ P1 to reject."
         │
         ▼
Team lead replies ✅ P1 → task thread created in #tasks
Team lead replies ❌ P1 → proposal discarded
```

The conversational agent in `#sprint-discuss` also proposes individual tasks in real-time when a team member commits to specific work.

---

## How the bot works in `#sprint-discuss`

```
New message in #sprint-discuss
         │
         ├── Main channel + len ≥ 20?  ──▶  Auto-create thread
         │
         ├── Starts with ✅/❌ Px?  ──▶  Confirm/reject pipeline proposal
         │
         └── Run Groq thread agent
                    │
                    ├── "propose_task"      Bot asks: "Track this?"
                    ├── "confirm_task"      Yes → task in state + thread in #tasks
                    ├── "reject_task"       No  → pending cleared
                    ├── "ask_clarification" Bot asks one focused question
                    ├── "answer_question"   Bot answers sprint status questions
                    ├── "note_decision"     Bot acknowledges a team decision
                    └── "silent"            Bot stays quiet (most messages)
```

---

## Web dashboard

Run `python ui/app.py` and open [http://localhost:5050](http://localhost:5050).

Shows:
- Sprint stats (open / done / blocked / unassigned)
- Tasks grouped by module team with status badges
- Pending proposals awaiting team-lead confirmation
- Full TEAM_LOG.md rendered as HTML
- Per-team detail pages (`/team/data`, `/team/agent`, etc.)

---

## Project structure

```
Scrum_Agent/
│
├── bot.py                        # Discord bot entry point
├── scheduler.py                  # APScheduler daily/weekly jobs
├── run.py                        # Standalone pipeline runner
│
├── pipeline/                     # Python AI pipeline (LangGraph)
│   ├── graph.py                  # LangGraph DAG assembly
│   ├── ingest.py                 # Discord message ingestion
│   ├── summarize.py              # LLM summarization (Groq)
│   ├── task_manager.py           # Task extraction, dedup, proposal flow
│   ├── thread_agent.py           # Conversational SM agent
│   ├── task_proposer.py          # Real-time task detection
│   ├── report_writer.py          # Markdown report + git push
│   ├── teams.py                  # Module team definitions
│   ├── schema.py                 # ScrumState TypedDict
│   └── api.py                    # FastAPI bridge (optional)
│
├── ui/                           # Web dashboard
│   ├── app.py                    # Flask app (port 5050)
│   ├── templates/
│   │   ├── dashboard.html        # Main sprint dashboard
│   │   └── team.html             # Per-team task view
│   └── static/
│       └── style.css             # Dark theme stylesheet
│
├── state/
│   └── sprint_state.json         # Runtime task state + proposals
│
├── prompts/                      # LLM system prompts
│   ├── scrum_master.md
│   └── story_splitter.md
│
├── docs/
│   ├── ARCHITECTURE.md           # System design + data flows
│   └── CONTRIBUTING.md           # Dev onboarding guide
│
├── CHANNELS.md                   # Discord channel reference
├── TEAM_LOG.md                   # Auto-generated daily sprint log
├── .env.example                  # Environment template
└── requirements.txt
```

---

## Tech stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| Bot | Python + discord.py | Direct control, simple async model |
| LLM | Groq / LLaMA 3.3-70B | Fast, generous free tier |
| AI pipeline | LangGraph + LangChain | Best AI/ML Python ecosystem |
| State | JSON file (sprint_state.json) | Zero infra, human-readable |
| Scheduler | APScheduler | Timezone-aware cron jobs |
| Web UI | Flask + markdown2 | Lightweight, no build step |
| Deduplication | Normalized string matching | Prevents duplicate task threads |
