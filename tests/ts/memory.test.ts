/**
 * tests/ts/memory.test.ts
 *
 * Tests for src/memory/index.ts — SQLite state layer.
 * Uses an in-memory LibSQL DB (configured in vitest.config.ts).
 * No Discord, no Jira, no LLM required.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  initDb,
  clearDb,
  upsertTask,
  getTaskById,
  getAllTasks,
  getOpenTasks,
  updateTaskStatus,
  nextTaskId,
  getUnreportedTasks,
  markTasksReported,
  getPendingConfirmation,
  setPendingConfirmation,
  deletePendingConfirmation,
  getSprintNumber,
  setSprintNumber,
  getLastReportDate,
  setLastReportDate,
} from "../../src/memory/index.js";
import type { TaskItem } from "../../src/types.js";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeTask(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    id: "T1",
    title: "Set up CI pipeline",
    owner: "alice",
    status: "open",
    threadId: null,
    createdDate: "2026-04-16",
    reportIncluded: false,
    ...overrides,
  };
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(async () => {
  await initDb();
  await clearDb();   // wipe all rows so each test starts fresh
});

// ── Sprint meta ───────────────────────────────────────────────────────────────

describe("Sprint metadata", () => {
  it("returns sprint number 1 by default", async () => {
    const n = await getSprintNumber();
    expect(n).toBe(1);
  });

  it("persists and retrieves sprint number", async () => {
    await setSprintNumber(5);
    expect(await getSprintNumber()).toBe(5);
  });

  it("returns null last report date initially", async () => {
    expect(await getLastReportDate()).toBeNull();
  });

  it("persists and retrieves last report date", async () => {
    await setLastReportDate("2026-04-16");
    expect(await getLastReportDate()).toBe("2026-04-16");
  });
});

// ── Task CRUD ─────────────────────────────────────────────────────────────────

describe("Task persistence", () => {
  it("inserts and retrieves a task by ID", async () => {
    const task = makeTask();
    await upsertTask(task);
    const found = await getTaskById("T1");
    expect(found).not.toBeNull();
    expect(found!.title).toBe("Set up CI pipeline");
    expect(found!.owner).toBe("alice");
    expect(found!.status).toBe("open");
  });

  it("returns null for a non-existent task ID", async () => {
    const found = await getTaskById("T999");
    expect(found).toBeNull();
  });

  it("upserts (updates) an existing task", async () => {
    await upsertTask(makeTask());
    await upsertTask(makeTask({ status: "in_progress" }));
    const found = await getTaskById("T1");
    expect(found!.status).toBe("in_progress");
  });

  it("retrieves all tasks", async () => {
    await upsertTask(makeTask({ id: "T1" }));
    await upsertTask(makeTask({ id: "T2", title: "Write tests" }));
    const all = await getAllTasks();
    expect(all).toHaveLength(2);
  });

  it("returns only non-done tasks in getOpenTasks", async () => {
    await upsertTask(makeTask({ id: "T1", status: "open" }));
    await upsertTask(makeTask({ id: "T2", status: "done" }));
    await upsertTask(makeTask({ id: "T3", status: "in_progress" }));
    const open = await getOpenTasks();
    expect(open).toHaveLength(2);
    expect(open.map((t) => t.id)).not.toContain("T2");
  });

  it("updates task status", async () => {
    await upsertTask(makeTask());
    await updateTaskStatus("T1", "done");
    const found = await getTaskById("T1");
    expect(found!.status).toBe("done");
  });

  it("stores and retrieves threadId and jiraKey", async () => {
    await upsertTask(makeTask({ threadId: 987654321, jiraKey: "SCRUM-42" }));
    const found = await getTaskById("T1");
    expect(found!.threadId).toBe(987654321);
    expect(found!.jiraKey).toBe("SCRUM-42");
  });
});

// ── Task ID generation ────────────────────────────────────────────────────────

describe("nextTaskId", () => {
  it("returns T1 when no tasks exist", async () => {
    const id = await nextTaskId();
    expect(id).toBe("T1");
  });

  it("increments from the highest existing ID", async () => {
    await upsertTask(makeTask({ id: "T3" }));
    await upsertTask(makeTask({ id: "T7" }));
    const id = await nextTaskId();
    expect(id).toBe("T8");
  });
});

// ── Unreported tasks ──────────────────────────────────────────────────────────

describe("Unreported task tracking", () => {
  it("returns tasks where reportIncluded=false", async () => {
    await upsertTask(makeTask({ id: "T1", reportIncluded: false }));
    await upsertTask(makeTask({ id: "T2", reportIncluded: true }));
    const unreported = await getUnreportedTasks();
    expect(unreported).toHaveLength(1);
    expect(unreported[0].id).toBe("T1");
  });

  it("markTasksReported sets reportIncluded=true", async () => {
    await upsertTask(makeTask({ id: "T1", reportIncluded: false }));
    await upsertTask(makeTask({ id: "T2", reportIncluded: false }));
    await markTasksReported(["T1", "T2"]);
    const unreported = await getUnreportedTasks();
    expect(unreported).toHaveLength(0);
  });

  it("markTasksReported with empty array does nothing", async () => {
    await upsertTask(makeTask({ id: "T1", reportIncluded: false }));
    await markTasksReported([]);
    const unreported = await getUnreportedTasks();
    expect(unreported).toHaveLength(1);
  });
});

// ── Pending confirmations ─────────────────────────────────────────────────────

describe("Pending confirmation (per-channel task proposals)", () => {
  const channelId = "111222333444555666";
  const confirmation = { taskTitle: "Fix auth bug", taskOwner: "bob" };

  it("returns null when no confirmation exists", async () => {
    const result = await getPendingConfirmation(channelId);
    expect(result).toBeNull();
  });

  it("sets and retrieves a pending confirmation", async () => {
    await setPendingConfirmation(channelId, confirmation);
    const result = await getPendingConfirmation(channelId);
    expect(result).not.toBeNull();
    expect(result!.taskTitle).toBe("Fix auth bug");
    expect(result!.taskOwner).toBe("bob");
  });

  it("overwrites an existing confirmation (upsert)", async () => {
    await setPendingConfirmation(channelId, confirmation);
    await setPendingConfirmation(channelId, { taskTitle: "Write docs", taskOwner: "carol" });
    const result = await getPendingConfirmation(channelId);
    expect(result!.taskTitle).toBe("Write docs");
  });

  it("deletes a pending confirmation", async () => {
    await setPendingConfirmation(channelId, confirmation);
    await deletePendingConfirmation(channelId);
    expect(await getPendingConfirmation(channelId)).toBeNull();
  });

  it("silently ignores deleting a non-existent confirmation", async () => {
    await expect(deletePendingConfirmation("nonexistent-channel")).resolves.toBeUndefined();
  });
});
