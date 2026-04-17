# Contributing to Scrum Agent

This guide is for developers joining the project. It covers local setup, code organisation, how to extend each layer, and how to write and run tests.

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [Local setup](#2-local-setup)
3. [Project layout](#3-project-layout)
4. [Environment variables](#4-environment-variables)
5. [Running in development](#5-running-in-development)
6. [Running tests](#6-running-tests)
7. [TypeScript bot layer — how to extend](#7-typescript-bot-layer--how-to-extend)
   - [Add a Mastra Tool](#71-add-a-mastra-tool)
   - [Add a Mastra Workflow step](#72-add-a-mastra-workflow-step)
   - [Add a Discord slash command](#73-add-a-discord-slash-command)
   - [Add a Jira integration function](#74-add-a-jira-integration-function)
8. [Python AI pipeline — how to extend](#8-python-ai-pipeline--how-to-extend)
   - [Add a new FastAPI endpoint](#81-add-a-new-fastapi-endpoint)
   - [Add a new LangGraph node](#82-add-a-new-langgraph-node)
9. [Database — how to extend](#9-database--how-to-extend)
10. [Writing tests](#10-writing-tests)
    - [TypeScript tests (Vitest)](#101-typescript-tests-vitest)
    - [Python tests (pytest)](#102-python-tests-pytest)
11. [TypeScript → Python bridge](#11-typescript--python-bridge)
12. [Key design rules](#12-key-design-rules)
13. [Branching and PR conventions](#13-branching-and-pr-conventions)
14. [Phase 2 GraphRAG — contribution notes](#14-phase-2-graphrag--contribution-notes)

---

## 1. Prerequisites

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Node.js | 20 | TypeScript bot runtime |
| npm | 9 | Package management |
| Python | 3.10 | AI pipeline |
| pip | 23 | Python package management |
| Git | any | Version control, TEAM_LOG push |

Recommended editor: **VS Code** with the ESLint and Pylance extensions.

---

## 2. Local setup

```bash
# 1. Clone
git clone <repo-url>
cd Scrum_Agent-main

# 2. Install TypeScript dependencies
npm install

# 3. Install Python AI pipeline dependencies
pip install -r requirements.txt
pip install fastapi uvicorn          # FastAPI bridge (not in requirements.txt)

# 4. Copy and fill environment variables
cp .env.example .env
# Edit .env — see section 4 for full variable reference

# 5. (Optional) Create the Discord application and register bot
#    See: https://discord.com/developers/applications
#    Add bot to server with scopes: bot, applications.commands
#    Permissions: Send Messages, Create Threads, Read Message History, Manage Threads
```

The SQLite database (`state/scrum.db`) is created automatically on first bot start.

---

## 3. Project layout

```
Scrum_Agent-main/
│
├── src/                              # TypeScript bot layer
│   ├── bot.ts                        # Entry point: discord.js client, slash commands, event handlers
│   ├── scheduler.ts                  # node-cron daily (09:00) + weekly (Fri 18:00) jobs
│   ├── types.ts                      # Shared TypeScript interfaces (TaskItem, AgentResult, etc.)
│   │
│   ├── agents/
│   │   └── scrumAgent.ts             # Mastra Agent: LLM inference + tool routing
│   │
│   ├── tools/
│   │   ├── createTask.ts             # Mastra Tool: persist a task to SQLite
│   │   ├── queryTasks.ts             # Mastra Tool: query tasks with filters
│   │   └── jiraSync.ts               # Mastra Tool: create Jira issue + write key back to DB
│   │
│   ├── workflows/
│   │   └── dailyPipeline.ts          # Mastra Workflow: run_pipeline → persist_tasks
│   │
│   ├── memory/
│   │   └── index.ts                  # LibSQL/SQLite state: tasks, sprint_meta, pending_confirmations
│   │
│   └── integrations/
│       ├── pipelineClient.ts         # HTTP client: TypeScript → Python FastAPI
│       └── jira.ts                   # Typed Jira Cloud REST v3 client
│
├── pipeline/                         # Python AI pipeline
│   ├── api.py                        # FastAPI entry point (HTTP bridge)
│   ├── graph.py                      # LangGraph pipeline definition
│   ├── ingest.py                     # Discord message formatting
│   ├── summarize.py                  # LLM summarization (LangChain + Groq)
│   ├── task_manager.py               # Task extraction + sprint state
│   ├── report_writer.py              # Markdown report + git push
│   └── schema.py                     # ScrumState TypedDict shared across Python modules
│
├── prompts/                          # LLM system prompts (plain Markdown)
│   ├── scrum_master.md               # System prompt for the conversational Scrum Master agent
│   └── story_splitter.md             # System prompt for story decomposition (Phase 2)
│
├── tests/
│   ├── ts/                           # Vitest TypeScript tests
│   │   ├── memory.test.ts            # 21 tests: SQLite CRUD
│   │   ├── agents/scrumAgent.test.ts # 14 tests: agent action routing
│   │   ├── tools/createTask.test.ts  # 5 tests: task creation tool
│   │   ├── tools/queryTasks.test.ts  # 8 tests: task query + filters
│   │   ├── tools/jiraSync.test.ts    # 4 tests: Jira sync (mocked)
│   │   ├── integrations/
│   │   │   └── pipelineClient.test.ts# 8 tests: HTTP client
│   │   └── workflows/
│   │       └── dailyPipeline.test.ts # 9 tests: workflow step logic
│   │
│   └── python/                       # pytest Python tests
│       ├── conftest.py               # Shared fixtures: TestClient, LLM mocks, discord stub
│       ├── test_api.py               # 12 tests: FastAPI endpoints
│       └── test_pipeline.py          # 27 tests: summarize, task_manager, report_writer
│
├── docs/
│   ├── ARCHITECTURE.md               # System design, data flows, DB schema
│   └── CONTRIBUTING.md               # This file
│
├── state/
│   └── scrum.db                      # Runtime SQLite DB (auto-created, git-ignored)
│
├── .env.example                      # Environment variable template
├── package.json                      # Node.js project + scripts
├── tsconfig.json                     # TypeScript compiler config
├── vitest.config.ts                  # Vitest test environment config
├── requirements.txt                  # Python dependencies
└── pytest.ini                        # pytest configuration
```

---

## 4. Environment variables

Copy `.env.example` to `.env` and fill in the values.

### Required (bot will not start without these)

| Variable | Description | Where to get |
|----------|-------------|-------------|
| `DISCORD_TOKEN` | Bot token | Discord Developer Portal → Application → Bot |
| `DISCORD_GUILD_ID` | Server ID | Discord → Developer Mode → right-click server → Copy ID |
| `GROQ_API_KEY` | Groq LLM API key | [console.groq.com](https://console.groq.com) |
| `CHANNEL_SPRINT_DISCUSS` | `#sprint-discuss` channel ID | Developer Mode → right-click channel → Copy ID |
| `CHANNEL_STANDUP` | `#standup` channel ID | same |
| `CHANNEL_TASKS` | `#tasks` channel ID | same |
| `CHANNEL_BLOCKERS` | `#blockers` channel ID | same |
| `CHANNEL_AI_REPORT` | `#ai-report` channel ID | same |
| `CHANNEL_CHANGELOG` | `#changelog` channel ID | same |

### Optional (Jira integration)

| Variable | Description |
|----------|-------------|
| `JIRA_BASE_URL` | e.g. `https://your-org.atlassian.net` |
| `JIRA_USER_EMAIL` | Jira account email |
| `JIRA_API_TOKEN` | Account Settings → Security → API tokens |
| `JIRA_PROJECT_KEY` | e.g. `SCRUM` |

### Optional (runtime tuning)

| Variable | Default | Description |
|----------|---------|-------------|
| `DAILY_DIGEST_HOUR` | `9` | Hour (24h) for daily digest cron |
| `WEEKLY_REPORT_HOUR` | `18` | Hour (24h) for Friday weekly report cron |
| `TIMEZONE` | `Asia/Kolkata` | IANA timezone for cron jobs |
| `PIPELINE_URL` | `http://localhost:8000` | Base URL for Python FastAPI |
| `LIBSQL_URL` | `file:state/scrum.db` | LibSQL database path |

---

## 5. Running in development

You need two terminals.

```bash
# Terminal 1 — Python AI pipeline (hot reload via uvicorn)
npm run pipeline
# equivalent: python pipeline/api.py
# starts on http://localhost:8000

# Terminal 2 — TypeScript Discord bot (hot reload via tsx watch)
npm run dev
# equivalent: tsx watch src/bot.ts
```

Verify the bridge is working:

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"scrum-pipeline"}
```

### Production build

```bash
npm run build        # tsc → dist/
npm start            # node dist/bot.js

# Python pipeline in a separate process or container:
python pipeline/api.py
```

---

## 6. Running tests

All tests use **dummy tools** — no real Discord, Jira, Groq, or LLM connection is required.

```bash
# TypeScript (Vitest) — 68 tests
npm test

# TypeScript in watch mode (re-runs on file save)
npm run test:watch

# TypeScript with HTML coverage report (opens dist/coverage/index.html)
npm run test:coverage

# Python (pytest) — 39 tests
npm run test:python
# or directly:
python -m pytest tests/python -v
```

Expected output:

```
TypeScript: 68 passed
Python:     39 passed
```

---

## 7. TypeScript bot layer — how to extend

### 7.1 Add a Mastra Tool

A Mastra Tool is a typed function that the LLM agent can call directly.

**File**: `src/tools/yourTool.ts`

```typescript
import { createTool } from "@mastra/core/tools";
import { z }           from "zod";

export const yourTool = createTool({
  id:          "your_tool_id",          // snake_case, used in system prompt
  description: "One sentence the LLM reads to decide when to call this tool.",
  inputSchema: z.object({
    param1: z.string().describe("What this parameter means"),
    param2: z.number().optional(),
  }),
  outputSchema: z.object({
    result: z.string(),
  }),
  execute: async ({ context }) => {
    const { param1, param2 } = context;
    // ... do work (DB read/write, HTTP call, etc.)
    return { result: "done" };
  },
});
```

**Register the tool in the agent** (`src/agents/scrumAgent.ts`):

```typescript
import { yourTool } from "../tools/yourTool.js";

export const scrumAgent: Agent<string, any> = new Agent({
  // ...
  tools: {
    create_task: createTaskTool,
    query_tasks: queryTasksTool,
    jira_sync:   jiraSyncTool,
    your_tool:   yourTool,            // ← add here
  },
});
```

**Mention the tool in the system prompt** so the LLM knows to use it. Open `prompts/scrum_master.md` and add a line like:

```
- Call your_tool when the user asks about X.
```

**Write a test**: copy `tests/ts/tools/createTask.test.ts` as a template.

---

### 7.2 Add a Mastra Workflow step

Workflow steps are chained via `.then()`. Each step's `outputSchema` must match the next step's `inputSchema` exactly.

**File**: `src/workflows/dailyPipeline.ts`

```typescript
import { createStep } from "@mastra/core/workflows";
import { z }          from "zod";

const yourStep = createStep({
  id: "your_step",
  inputSchema: z.object({
    // must match all fields from the previous step's outputSchema
    summary:       z.string(),
    decisions:     z.array(z.string()),
    blockers:      z.array(z.string()),
    newTaskDrafts: z.array(z.any()),
    reportMd:      z.string(),
    reportDate:    z.string(),
    // + any new fields you need
  }),
  outputSchema: z.object({
    // forward all fields you want downstream steps to see
    summary:    z.string(),
    reportDate: z.string(),
    yourResult: z.string(),
  }),
  execute: async ({ inputData }) => {
    // do work
    return {
      summary:    inputData.summary,
      reportDate: inputData.reportDate,
      yourResult: "computed",
    };
  },
});
```

**Wire the step into the workflow**:

```typescript
export const dailyPipelineWorkflow = createWorkflow({ ... })
  .then(runPipelineStep)
  .then(persistTasksStep)
  .then(yourStep)       // ← chain here
  .commit();
```

> **Key rule**: always forward `reportDate` explicitly through every step. Mastra's `.then()` maps the previous step's output to the next step's input — fields not in the output schema are dropped.

---

### 7.3 Add a Discord slash command

**Step 1 — Declare the command** in `src/bot.ts` inside `registerCommands()`:

```typescript
const yourCommand = new SlashCommandBuilder()
  .setName("yourcommand")
  .setDescription("What this command does")
  .addStringOption(opt =>
    opt.setName("param").setDescription("A parameter").setRequired(false)
  );

// Add to the commands array:
const commands = [
  reportCmd, sprintCmd, tasksCmd, statusCmd, taskCmd,
  yourCommand,    // ← add here
].map(c => c.toJSON());
```

**Step 2 — Handle the interaction** in the `interactionCreate` handler:

```typescript
client.on("interactionCreate", async interaction => {
  if (!interaction.isChatInputCommand()) return;
  const { commandName } = interaction;

  // ...existing handlers...

  if (commandName === "yourcommand") {
    const param = interaction.options.getString("param") ?? "";
    await interaction.deferReply();
    // do async work
    await interaction.editReply(`Result: ${param}`);
  }
});
```

**Step 3 — Register with Discord**: commands are registered on bot startup via `registerCommands()`. No manual Discord Portal step needed.

---

### 7.4 Add a Jira integration function

**File**: `src/integrations/jira.ts`

All Jira REST v3 calls share the same `axiosInstance` with basic auth already configured. Add your function:

```typescript
export async function yourJiraFunction(issueKey: string): Promise<SomeType> {
  const response = await axiosInstance.get<SomeType>(
    `/rest/api/3/issue/${issueKey}/your-endpoint`
  );
  return response.data;
}
```

Import and call it from a tool or `src/bot.ts` as needed.

---

## 8. Python AI pipeline — how to extend

### 8.1 Add a new FastAPI endpoint

**File**: `pipeline/api.py`

```python
from pydantic import BaseModel

class YourRequest(BaseModel):
    field_one: str
    field_two: list[str] = []

class YourResponse(BaseModel):
    result: str

@app.post("/pipeline/your-endpoint", response_model=YourResponse)
async def your_endpoint(payload: YourRequest) -> YourResponse:
    # call pipeline functions
    result = await your_pipeline_function(payload.field_one, payload.field_two)
    return YourResponse(result=result)
```

**Expose it from TypeScript** in `src/integrations/pipelineClient.ts`:

```typescript
export async function yourPipelineCall(params: YourParams): Promise<YourResult> {
  const res = await apiClient.post<{ result: string }>("/pipeline/your-endpoint", {
    field_one: params.fieldOne,
    field_two: params.fieldTwo,
  });
  return { result: res.data.result };
}
```

Note: Python uses `snake_case` in JSON; TypeScript uses `camelCase` internally. Always convert at the pipelineClient boundary.

---

### 8.2 Add a new LangGraph node

**File**: `pipeline/graph.py`

```python
from pipeline.schema import ScrumState

async def your_node(state: ScrumState) -> ScrumState:
    """One-line description of what this node does."""
    # read from state
    messages = state.get("raw_messages", {})
    # call LLM or do processing
    result = await some_function(messages)
    # write back to state
    return {**state, "your_field": result}
```

**Wire the node into the graph**:

```python
builder = StateGraph(ScrumState)
builder.add_node("summarize_node",       summarize_node)
builder.add_node("extract_action_items", extract_action_items)
builder.add_node("your_node",            your_node)        # ← add here
builder.add_node("build_report",         build_report_markdown)

builder.add_edge("summarize_node",       "extract_action_items")
builder.add_edge("extract_action_items", "your_node")      # ← wire here
builder.add_edge("your_node",            "build_report")
```

**Add the new field to `ScrumState`** (`pipeline/schema.py`):

```python
class ScrumState(TypedDict, total=False):
    raw_messages:   dict
    summary:        str
    decisions:      list[str]
    blockers:       list[str]
    action_items:   list[dict]
    report_md:      str
    your_field:     str          # ← add here
```

---

## 9. Database — how to extend

The database is managed in `src/memory/index.ts`.

### Add a new column to an existing table

1. Add the column to the `CREATE TABLE IF NOT EXISTS` statement.
2. Add the new field to the relevant TypeScript interface in `src/types.ts`.
3. Update `upsertTask()` (or the relevant upsert function) to include the field.
4. Because SQLite `CREATE TABLE IF NOT EXISTS` does not add columns to an existing DB, you must also run an `ALTER TABLE` migration for any existing `state/scrum.db`.

Example — adding a `priority` column:

```typescript
// In initDb():
await client.execute(`
  CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    owner           TEXT NOT NULL DEFAULT 'unassigned',
    status          TEXT NOT NULL DEFAULT 'open',
    thread_id       INTEGER,
    created_date    TEXT,
    report_included INTEGER NOT NULL DEFAULT 0,
    jira_key        TEXT,
    sprint_number   INTEGER,
    priority        TEXT NOT NULL DEFAULT 'medium'   -- new column
  )
`);
```

### Add a new table

```typescript
// In initDb():
await client.execute(`
  CREATE TABLE IF NOT EXISTS your_table (
    id    TEXT PRIMARY KEY,
    data  TEXT NOT NULL
  )
`);

// In clearDb() (for test isolation):
await client.execute("DELETE FROM your_table");
```

---

## 10. Writing tests

### 10.1 TypeScript tests (Vitest)

Tests live in `tests/ts/`. Each file uses `import { describe, it, expect, vi, beforeEach } from "vitest"`.

#### DB isolation pattern

Every test file that touches the database must reset state before each test:

```typescript
import { initDb, clearDb } from "../../../src/memory/index.js";

beforeEach(async () => {
  await initDb();
  await clearDb();   // wipes all rows — prevents bleed between tests
});
```

The in-memory URL (`file::memory:?cache=shared` in `vitest.config.ts`) shares one SQLite instance across the process. `clearDb()` is the only safe way to isolate tests.

#### Mocking external modules — `vi.hoisted` pattern

If you need to mock a module and refer to the mock functions inside the `vi.mock()` factory, you **must** use `vi.hoisted()`:

```typescript
// BAD — ReferenceError at runtime because vi.mock runs before const declarations
const mockFn = vi.fn();
vi.mock("some-module", () => ({ fn: mockFn }));

// GOOD — vi.hoisted runs before vi.mock, so the variable is available
const { mockFn } = vi.hoisted(() => ({ mockFn: vi.fn() }));
vi.mock("some-module", () => ({ fn: mockFn }));
```

#### Template for a new tool test

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { initDb, clearDb } from "../../../src/memory/index.js";
import { yourTool } from "../../../src/tools/yourTool.js";

beforeEach(async () => {
  await initDb();
  await clearDb();
});

describe("yourTool", () => {
  it("does what it says", async () => {
    const result = await yourTool.execute!({ context: { param1: "value" } } as any);
    expect(result.result).toBe("expected");
  });
});
```

#### Template for a new integration test (with mocked HTTP)

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockPost } = vi.hoisted(() => ({ mockPost: vi.fn() }));

vi.mock("axios", async () => {
  const actual = await vi.importActual<typeof import("axios")>("axios");
  return {
    ...actual,
    default: { ...actual.default, create: () => ({ get: vi.fn(), post: mockPost }) },
  };
});

import { yourPipelineCall } from "../../../src/integrations/pipelineClient.js";

beforeEach(() => vi.clearAllMocks());

describe("yourPipelineCall", () => {
  it("POSTs to the correct endpoint", async () => {
    mockPost.mockResolvedValueOnce({ data: { result: "ok" } });
    const result = await yourPipelineCall({ fieldOne: "x", fieldTwo: [] });
    expect(mockPost).toHaveBeenCalledWith("/pipeline/your-endpoint", expect.any(Object));
    expect(result.result).toBe("ok");
  });
});
```

---

### 10.2 Python tests (pytest)

Tests live in `tests/python/`. Shared fixtures are in `conftest.py`.

#### Available fixtures

| Fixture | What it provides |
|---------|-----------------|
| `client` | `fastapi.testclient.TestClient` wrapping the FastAPI app — no real server needed |
| `mock_groq_summarize` | Patches `langchain_groq.ChatGroq`; yields the `ainvoke` mock for summarization |
| `mock_groq_tasks` | Same, for task extraction calls |

#### Why `langchain_groq.ChatGroq` and not `pipeline.X.ChatGroq`

`ChatGroq` is instantiated **inside async functions** in the pipeline code, not at module top-level. Python's `unittest.mock.patch` replaces attributes on the target module at import time — if `ChatGroq` was never bound as a module-level name, patching `pipeline.summarize.ChatGroq` does nothing. Patching `langchain_groq.ChatGroq` (the source) intercepts every construction regardless of where the import happens.

#### Template for a new endpoint test

```python
class TestYourEndpoint:
    PAYLOAD = {"field_one": "value", "field_two": []}

    def test_returns_200(self, client, mock_groq_summarize):
        resp = client.post("/pipeline/your-endpoint", json=self.PAYLOAD)
        assert resp.status_code == 200

    def test_returns_expected_fields(self, client, mock_groq_summarize):
        resp = client.post("/pipeline/your-endpoint", json=self.PAYLOAD)
        data = resp.json()
        assert "result" in data

    def test_rejects_missing_field(self, client):
        resp = client.post("/pipeline/your-endpoint", json={})
        assert resp.status_code == 422   # Pydantic validation error
```

#### Template for a new pipeline function test

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_your_pipeline_function():
    with patch("langchain_groq.ChatGroq") as MockClass:
        instance = MagicMock()
        instance.ainvoke = AsyncMock(return_value=MagicMock(content='{"key":"value"}'))
        MockClass.return_value = instance

        from pipeline.your_module import your_function
        result = await your_function({"standup": ["alice: working on X"]})

    assert result["key"] == "value"
```

---

## 11. TypeScript → Python bridge

The bridge is a plain HTTP connection. TypeScript calls Python; Python never calls TypeScript.

```
TypeScript (src/integrations/pipelineClient.ts)
    │
    │  POST http://localhost:8000/pipeline/run
    │  Body: { raw_messages: {...}, report_date: "2026-04-16" }
    │
    ▼
Python (pipeline/api.py)
    │
    │  FastAPI receives, validates (Pydantic), calls pipeline
    │
    ▼
Python (pipeline/graph.py)   LangGraph pipeline
    │
    ▼
Response: { summary, decisions, blockers, new_tasks, report_md }
    │
    ▼
TypeScript normalises snake_case → camelCase
    new_tasks → newTasks
    report_md → reportMd
```

### Adding a new bridge endpoint checklist

- [ ] Add Pydantic request + response models to `pipeline/api.py`
- [ ] Add the `@app.post(...)` route handler
- [ ] Add a corresponding function in `src/integrations/pipelineClient.ts`
- [ ] Convert camelCase → snake_case in the TypeScript request
- [ ] Convert snake_case → camelCase in the TypeScript response
- [ ] Write a test in `tests/ts/integrations/pipelineClient.test.ts` (mock axios)
- [ ] Write a test in `tests/python/test_api.py` (use `client` fixture)

---

## 12. Key design rules

| Rule | Reason |
|------|--------|
| Use `vi.hoisted()` whenever a mock variable is used inside `vi.mock()` | Vitest hoists `vi.mock` before variable declarations — variables aren't in scope without `vi.hoisted` |
| Patch `langchain_groq.ChatGroq`, not `pipeline.X.ChatGroq` | ChatGroq is imported inside async functions; module-level patching doesn't intercept it |
| Always call `clearDb()` in `beforeEach` for DB tests | `file::memory:?cache=shared` shares one SQLite; rows from a previous test are visible to the next |
| Forward `reportDate` explicitly in every Workflow step output | Mastra `.then()` maps step N output to step N+1 input — only declared output fields are forwarded |
| Keep `@ai-sdk/groq` at version `^1.0.0` | v3.x returns `LanguageModelV3` which is incompatible with Mastra 0.10.x's `LanguageModelV1` expectation |
| Use `Agent<string, any>` explicit type on `scrumAgent` | Without the type annotation, TypeScript infers a complex inlined type that cannot be named — causes TS2742 |
| All Jira calls are optional/graceful | Jira may not be configured; `jira.ts` checks env vars before making requests and returns `null` on failure |

---

## 13. Branching and PR conventions

```
main          production-ready code
  └── feat/short-description    new features
  └── fix/short-description     bug fixes
  └── chore/short-description   dependency updates, config, docs
```

**Before opening a PR:**

```bash
npm test                   # all 68 TypeScript tests pass
npm run test:python        # all 39 Python tests pass
npm run build              # TypeScript compiles without errors
```

**PR description must include:**

- What changed and why
- Which tests cover the change
- Any new environment variables required

---

## 14. Phase 2 GraphRAG — contribution notes

Phase 2 replaces the flat SQLite `tasks` table with a knowledge graph.

```
Phase 1 (current)              Phase 2 (planned)
─────────────────              ─────────────────
SQLite flat tasks table   →    Graph nodes: task, story, epic, sprint
                               Edges: task→story→epic→sprint
                               Metadata: assignees, dates, status, blockers

Query: "open tasks"       →    Query: "What caused the delay in Epic X?"
       ↓                               ↓
  SQL SELECT                    Graph traversal + LLM synthesis (GraphRAG)

Storage: SQLite           →    Neo4j or Rust-based graph engine
```

### Forward-compatibility notes

The current SQLite schema already includes GraphRAG-ready fields:

| Column | GraphRAG role |
|--------|--------------|
| `jira_key` | Node identity in Jira hierarchy |
| `sprint_number` | Edge: task → sprint |
| `report_included` | Audit / temporal metadata |

### Contributing to Phase 2

1. The graph engine (Neo4j / Rust) will be a new `src/graph/` directory.
2. `src/memory/index.ts` will be extended with a `GraphStore` class that mirrors the current `upsertTask` / `getAllTasks` API so callers in `bot.ts` require minimal changes.
3. LangGraph nodes in `pipeline/graph.py` will be extended with a retrieval step that queries the graph before LLM inference.
4. Performance-critical traversal code (if Rust-based) will live in `src/graph/native/` and be called via Node.js N-API bindings.

Do not merge Phase 2 changes into `main` until the GraphRAG integration tests pass with both real and in-memory graph backends.
