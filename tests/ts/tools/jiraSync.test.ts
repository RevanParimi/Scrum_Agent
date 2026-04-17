/**
 * tests/ts/tools/jiraSync.test.ts
 *
 * Tests for the jiraSync Mastra Tool.
 * DUMMY JIRA: axios is mocked — no real Jira/iTrack connection needed.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { initDb, clearDb, upsertTask, getTaskById } from "../../../src/memory/index.js";
import type { TaskItem } from "../../../src/types.js";

// ── Mock axios before importing the module under test ─────────────────────────
vi.mock("axios", async () => {
  const actual = await vi.importActual<typeof import("axios")>("axios");
  return {
    ...actual,
    default: {
      ...actual.default,
      create: () => ({
        get: vi.fn(),
        post: vi.fn().mockResolvedValue({
          data: { key: "SCRUM-99", id: "10099" },
        }),
      }),
    },
  };
});

// ── Mock jira.ts createIssue so we don't need real Jira creds ─────────────────
vi.mock("../../../src/integrations/jira.js", () => ({
  createIssue: vi.fn().mockResolvedValue({
    key: "SCRUM-42",
    id: "10042",
    summary: "Fix auth bug",
    status: "To Do",
    assignee: null,
    issueType: "Task",
    priority: "Medium",
    created: "2026-04-16T00:00:00.000Z",
    updated: "2026-04-16T00:00:00.000Z",
  }),
}));

import { jiraSyncTool } from "../../../src/tools/jiraSync.js";

// ── Seed task ─────────────────────────────────────────────────────────────────

const seedTask: TaskItem = {
  id: "T5",
  title: "Fix auth bug",
  owner: "alice",
  status: "open",
  threadId: null,
  createdDate: "2026-04-16",
  reportIncluded: true,
};

function exec(input: Parameters<typeof jiraSyncTool.execute>[0]["context"]) {
  return jiraSyncTool.execute({
    context: input,
    runId: "test",
    mastra: undefined as never,
    resourceId: undefined,
    threadId: undefined,
    runtimeContext: undefined as never,
  });
}

beforeEach(async () => {
  await initDb();
  await clearDb();
  await upsertTask(seedTask);
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("jiraSyncTool", () => {
  it("returns the Jira key from the dummy response", async () => {
    const result = await exec({ taskId: "T5", issueType: "Task" });
    expect(result.jiraKey).toBe("SCRUM-42");
  });

  it("includes task ID and Jira key in the message", async () => {
    const result = await exec({ taskId: "T5", issueType: "Task" });
    expect(result.message).toContain("T5");
    expect(result.message).toContain("SCRUM-42");
  });

  it("writes the Jira key back to the local task record", async () => {
    await exec({ taskId: "T5", issueType: "Task" });
    const saved = await getTaskById("T5");
    expect(saved!.jiraKey).toBe("SCRUM-42");
  });

  it("throws a clear error for a non-existent task ID", async () => {
    await expect(exec({ taskId: "T999", issueType: "Task" })).rejects.toThrow("T999 not found");
  });
});
