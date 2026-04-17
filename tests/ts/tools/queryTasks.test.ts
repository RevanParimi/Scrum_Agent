/**
 * tests/ts/tools/queryTasks.test.ts
 *
 * Tests for the queryTasks Mastra Tool.
 * Dummy setup: in-memory SQLite pre-seeded with known tasks.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { initDb, clearDb, upsertTask } from "../../../src/memory/index.js";
import { queryTasksTool } from "../../../src/tools/queryTasks.js";
import type { TaskItem } from "../../../src/types.js";

// ── Seed data ─────────────────────────────────────────────────────────────────

const seedTasks: TaskItem[] = [
  { id: "T1", title: "Build login page",     owner: "alice", status: "open",        threadId: null, createdDate: "2026-04-14", reportIncluded: true },
  { id: "T2", title: "Fix API timeout",      owner: "bob",   status: "in_progress", threadId: null, createdDate: "2026-04-14", reportIncluded: true },
  { id: "T3", title: "Write test cases",     owner: "alice", status: "blocked",     threadId: null, createdDate: "2026-04-15", reportIncluded: false },
  { id: "T4", title: "Deploy to staging",    owner: "carol", status: "done",        threadId: null, createdDate: "2026-04-15", reportIncluded: true },
  { id: "T5", title: "Review PR for search", owner: "bob",   status: "open",        threadId: null, createdDate: "2026-04-16", reportIncluded: false },
];

beforeEach(async () => {
  await initDb();
  await clearDb();
  for (const task of seedTasks) await upsertTask(task);
});

// ── Shared executor helper ────────────────────────────────────────────────────

function exec(input: Parameters<typeof queryTasksTool.execute>[0]["context"]) {
  return queryTasksTool.execute({
    context: input,
    runId: "test",
    mastra: undefined as never,
    resourceId: undefined,
    threadId: undefined,
    runtimeContext: undefined as never,
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("queryTasksTool — filter: open", () => {
  it("returns only non-done tasks", async () => {
    const result = await exec({ filter: "open" });
    expect(result.tasks.map((t) => t.id)).not.toContain("T4");
    expect(result.count).toBe(4);
  });
});

describe("queryTasksTool — filter: all", () => {
  it("returns all tasks including done", async () => {
    const result = await exec({ filter: "all" });
    expect(result.count).toBe(5);
    expect(result.tasks.map((t) => t.id)).toContain("T4");
  });
});

describe("queryTasksTool — filter: blocked", () => {
  it("returns only blocked tasks", async () => {
    const result = await exec({ filter: "blocked" });
    expect(result.count).toBe(1);
    expect(result.tasks[0].id).toBe("T3");
    expect(result.tasks[0].status).toBe("blocked");
  });

  it("returns empty list if no blocked tasks", async () => {
    await upsertTask({ id: "T3", title: "Write test cases", owner: "alice", status: "open", threadId: null, createdDate: "2026-04-15", reportIncluded: false });
    const result = await exec({ filter: "blocked" });
    expect(result.count).toBe(0);
  });
});

describe("queryTasksTool — filter: done", () => {
  it("returns only completed tasks", async () => {
    const result = await exec({ filter: "done" });
    expect(result.count).toBe(1);
    expect(result.tasks[0].id).toBe("T4");
  });
});

describe("queryTasksTool — filter: by_owner", () => {
  it("returns tasks for a specific owner (exact match)", async () => {
    const result = await exec({ filter: "by_owner", owner: "alice" });
    expect(result.count).toBe(2);
    expect(result.tasks.every((t) => t.owner === "alice")).toBe(true);
  });

  it("returns tasks for owner (case-insensitive)", async () => {
    const result = await exec({ filter: "by_owner", owner: "BOB" });
    expect(result.count).toBe(2);
  });

  it("returns empty list for unknown owner", async () => {
    const result = await exec({ filter: "by_owner", owner: "nobody" });
    expect(result.count).toBe(0);
  });
});

describe("queryTasksTool — response shape", () => {
  it("includes expected fields on each task", async () => {
    const result = await exec({ filter: "all" });
    const t = result.tasks[0];
    expect(t).toHaveProperty("id");
    expect(t).toHaveProperty("title");
    expect(t).toHaveProperty("owner");
    expect(t).toHaveProperty("status");
    expect(t).toHaveProperty("createdDate");
  });
});
