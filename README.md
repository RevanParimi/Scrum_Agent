# Discord Scrum Master Bot

An AI-powered Discord bot that acts as an automated Scrum Master. It monitors team conversations, synthesises daily stand-ups, extracts action items, tracks blockers, and generates reports — all without human intervention.

---

## How It Works

The bot runs a **4-node LangGraph pipeline** triggered on a schedule or on demand:

```
ingest → summarize → task_manager → report_writer → END
```

| Node | File | What it does |
|---|---|---|
| **ingest** | `pipeline/ingest.py` | Fetches recent messages from watched Discord channels and their active threads |
| **summarize** | `pipeline/summarize.py` | Sends raw messages to Claude (Sonnet) and extracts `summary`, `decisions`, `blockers` as JSON |
| **task_manager** | `pipeline/task_manager.py` | Uses Claude (Haiku) to extract action items, creates Discord task threads, persists to `state/sprint_state.json` |
| **report_writer** | `pipeline/report_writer.py` | Builds a Markdown report, appends to `TEAM_LOG.md`, commits + pushes via Git, posts to Discord |

---

## Project Structure

```
discord-scrum-master/
├── bot.py                   # Entry point — Discord client, commands, events
├── scheduler.py             # APScheduler cron definitions
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
├── railway.toml             # Railway.app deployment config
├── TEAM_LOG.md              # Auto-generated daily reports (git-tracked)
│
├── pipeline/
│   ├── __init__.py
│   ├── graph.py             # LangGraph assembly and pipeline runners
│   ├── schema.py            # ScrumState and TaskItem TypedDicts
│   ├── ingest.py            # Node 1: fetch Discord messages
│   ├── summarize.py         # Node 2: Claude summarization
│   ├── task_manager.py      # Node 3: task extraction + thread creation
│   └── report_writer.py     # Node 4: report generation + Git + Discord
│
├── prompts/
│   └── scrum_master.md      # System prompt for Claude
│
└── state/
    └── sprint_state.json    # Persistent task + sprint state (JSON file)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Discord SDK | discord.py 2.3.2 |
| AI orchestration | LangGraph 0.2.28 |
| AI framework | LangChain (langchain-core 0.3.15) |
| AI models | Claude via langchain-anthropic 0.2.4 |
| Scheduling | APScheduler 3.10.4 |
| Git automation | GitPython 3.1.43 |
| Async file I/O | aiofiles 23.2.1 |
| Config | python-dotenv 1.0.1 |
| Deployment | Railway.app |

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in all values:

```env
# Discord
DISCORD_TOKEN=          # Bot token from Discord Developer Portal
DISCORD_GUILD_ID=       # Your server's Guild ID (integer)

# Channel IDs (integer) — bot reads from and writes to these
CHANNEL_SPRINT_DISCUSS= # Main discussion channel (auto-threads new topics)
CHANNEL_STANDUP=        # Daily standups
CHANNEL_TASKS=          # Task board (bot creates threads here)
CHANNEL_BLOCKERS=       # Blocker reporting
CHANNEL_AI_REPORT=      # Where reports are posted
CHANNEL_CHANGELOG=      # Where summaries are posted

# Anthropic
ANTHROPIC_API_KEY=      # sk-ant-... key

# Config
TEAM_LOG_REPO_PATH=.    # Repo path for TEAM_LOG.md commits (default: current dir)
TIMEZONE=Asia/Kolkata   # Scheduler timezone (IANA format)
```

### 3. Discord bot permissions required

In the [Discord Developer Portal](https://discord.com/developers/applications) → your app → **OAuth2 → URL Generator**:

- Scopes: `bot`
- Bot Permissions to check:
  - **General:** View Channels
  - **Text:** Send Messages, Create Public Threads, Send Messages in Threads, Manage Messages, Manage Threads, Embed Links, Read Message History

Also under **Bot → Privileged Gateway Intents**, enable:
- **Message Content Intent** (required to read message text)

Generate the invite URL and open it in a browser to add the bot to your server.

> `Attach Files` is **not** needed — the bot only sends text. Add it later if you introduce file exports.

### 4. Verify Guild ID

After adding the bot to your server, confirm `DISCORD_GUILD_ID` in `.env` matches the correct server:

- Discord → right-click your **server icon** → **Copy Server ID**
- Requires **Developer Mode** enabled: Settings → Advanced → Developer Mode

If the bot starts but logs `Guild not found`, this is the cause.

### 5. Run

```bash
python bot.py
```

Expected startup output:
```
Logged in as YourBot#1234 | Guild: YourServerName
  #tasks       → <TextChannel id=... name='tasks'>
  #ai-report   → <TextChannel id=... name='ai-report'>
  #changelog   → <TextChannel id=... name='changelog'>
APScheduler started
```

If any channel shows as `None`, the corresponding `CHANNEL_*` ID in `.env` is wrong or unset.

---

## Bot Commands

| Command | Permission | Description |
|---|---|---|
| `!report` | manage_messages | Trigger an immediate daily digest |
| `!sprint` | manage_messages | Trigger the weekly 7-day sprint summary |
| `!tasks` | everyone | List all open tasks from `sprint_state.json` |
| `!status` | everyone | Confirm bot is alive and show resolved channels |

---

## Automated Schedule

| Time | Action |
|---|---|
| Daily at 9:00 AM (configurable timezone) | Runs `run_daily_pipeline` — fetches last 24 hours |
| Friday at 6:00 PM | Runs `run_sprint_report` — fetches last 7 days |

Schedule is defined in `scheduler.py` using APScheduler's `AsyncIOScheduler`.

---

## Data Models

### `ScrumState` (shared pipeline state)

```python
class ScrumState(TypedDict):
    raw_messages: dict[str, list[str]]  # {"channel/thread": ["msg1", ...]}
    fetch_since_hours: int

    summary: str
    decisions: list[str]
    blockers: list[str]

    tasks: list[TaskItem]               # cumulative sprint tasks
    new_tasks: list[TaskItem]           # tasks created this run

    report_md: str                      # full Markdown for TEAM_LOG.md
    report_date: str                    # ISO date string
```

### `TaskItem`

```python
class TaskItem(TypedDict):
    id: str               # "T1", "T2", etc.
    title: str            # ≤10 words, imperative form
    owner: str            # Discord username or "unassigned"
    status: str           # "open" | "in_progress" | "blocked" | "done"
    thread_id: int | None # Discord thread ID
    created_date: str     # ISO date
```

### `state/sprint_state.json` (persisted to disk)

```json
{
  "sprint_number": 1,
  "sprint_start": null,
  "sprint_end": null,
  "tasks": [],
  "last_report_date": "YYYY-MM-DD",
  "last_ingested_message_ids": {}
}
```

---

## AI Configuration

Two Claude models are used depending on the task:

| Node | Model | Reason |
|---|---|---|
| `summarize.py` | `claude-sonnet-4-6` | Full analysis, nuanced reasoning |
| `task_manager.py` | `claude-haiku-4-5-20251001` | Fast, cheap extraction |

Both use `ChatAnthropic` from `langchain-anthropic`. The system prompt lives in `prompts/scrum_master.md`.

Token limits: 2048 max tokens for summarization, 1024 for task extraction.
Context cap: raw messages are truncated at 60,000 characters before being sent to Claude.

---

## Key Architectural Patterns

1. **Factory nodes** — `ingest.py`, `task_manager.py`, and `report_writer.py` expose `make_*_node()` factory functions that close over Discord channel objects resolved at bot startup. This decouples pipeline logic from Discord state.

2. **LangGraph state machine** — `pipeline/graph.py` assembles nodes into a directed graph. State flows through all nodes and is accumulated (not replaced) at each step.

3. **File-backed persistence** — `sprint_state.json` is a plain JSON file. There is no database. All reads and writes go through this file.

4. **Git-backed report log** — `TEAM_LOG.md` is committed and pushed by the bot after each pipeline run using GitPython.

5. **JSON resilience** — Claude's output is parsed with a fallback. If the response is not valid JSON, the node falls back gracefully rather than crashing the pipeline.

---

## Requirements for New Features

Before adding any new feature, read and understand these constraints:

### Environment
- All new environment variables must be added to `.env.example` with a comment.
- Always use `os.environ.get("VAR", default)` for optional config. Use `os.environ["VAR"]` only for required values (it will raise on startup if missing — this is intentional).

### Pipeline nodes
- Every pipeline node must be a function with signature `async def node(state: ScrumState) -> ScrumState` (or a partial thereof via a factory).
- Nodes must not have side effects outside of: (a) writing to `ScrumState`, (b) calling the Discord API, (c) calling the Claude API, (d) writing to `sprint_state.json` or `TEAM_LOG.md`.
- Register new nodes in `pipeline/graph.py`.

### State changes
- New fields on `ScrumState` go in `pipeline/schema.py`. Add them to both the `TypedDict` class and the `empty_state()` factory.
- New fields on `TaskItem` also go in `pipeline/schema.py`.

### Discord channel access
- All channel objects must be resolved in `bot.py:on_ready()` and passed into pipeline functions — never fetched inside pipeline nodes.
- New channels need a corresponding `CHANNEL_*` env var and a `get_channel("name")` call in `on_ready`.

### AI prompts
- If a new node requires a system prompt, add it as a `.md` file in `prompts/`.
- Do not hardcode prompts as inline strings inside node files.
- Choose the right model: Haiku for fast/cheap extraction, Sonnet for reasoning-heavy tasks.

### Scheduling
- New scheduled jobs go in `scheduler.py`. Use `AsyncIOScheduler` and pass async callbacks.
- Timezone is always read from `TIMEZONE` env var — never hardcode a timezone.

### Persistence
- The only persistence layer is `state/sprint_state.json`. Use `json.loads` / `json.dumps` with `encoding="utf-8"`.
- Do not introduce a database without explicit discussion — the file-based approach is intentional for simplicity and Railway compatibility.

### Commands
- New bot commands use the `@bot.command` decorator with `@commands.has_permissions(...)` where appropriate.
- Commands that trigger the pipeline should call the existing `_run_daily()` or `_run_weekly()` helpers in `bot.py`, or a new equivalent helper — not the pipeline directly.

### Error handling
- All pipeline nodes must catch exceptions and log them. Non-fatal errors (Git push failure, Discord post failure) must not crash the pipeline.
- Fatal errors (channel not resolved, missing required env var) should prevent the bot from starting, not fail silently at runtime.

### Testing locally
- Run `python bot.py` directly. There is no test suite — test manually against a real Discord server.
- You will need a real `DISCORD_TOKEN` and a real guild. There is no mock/stub mode.

---

## Deployment (Railway)

The `railway.toml` configures:
- Builder: NIXPACKS
- Start command: `python bot.py`
- Auto-restart on failure (5 retries)

Set all `.env` values as Railway environment variables in the Railway dashboard. Do not commit `.env`.

---

## Files Never to Commit

`.gitignore` excludes:
- `.env`
- `venv/`, `__pycache__/`
- `*.pyc`

`TEAM_LOG.md` and `state/sprint_state.json` **are** committed by the bot itself automatically. Do not add them to `.gitignore`.
