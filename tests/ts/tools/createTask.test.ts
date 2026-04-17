/**
 * tests/ts/tools/createTask.test.ts
 *
 * Tests for the createTask Mastra Tool.
 * Dummy setup: in-memory SQLite, no Discord/Jira.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { initDb, clearDb, getAllTasks, getTaskById } from "../../../src/memory/index.js";
import { createTaskTool } from "../../../src/tools/createTask.js";

beforeEach(async () => {
  await initDb();
  await clearDb();
});

describe("createTaskTool", () => {
  it("creates a task and returns its ID", async () => {
    const result = await createTaskTool.execute({
      context: { title: "Implement login screen", owner: "alice" },
      runId: "test-run",
      mastra: undefined as never,
      resourceId: undefined,
      threadId: undefined,
      runtimeContext: undefined as never,
    });

    expect(result.taskId).toMatch(/^T\d+$/);
    expect(result.message).toContain("alice");
    expect(result.message).toContain("Implement login screen");
  });

  it("persists the task to the database", async () => {
    const result = await createTaskTool.execute({
      context: { title: "Write unit tests", owner: "bob" },
      runId: "test-run",
      mastra: undefined as never,
      resourceId: undefined,
      threadId: undefined,
      runtimeContext: undefined as never,
    });

    const saved = await getTaskById(result.taskId);
    expect(saved).not.toBeNull();
    expect(saved!.title).toBe("Write unit tests");
    expect(saved!.owner).toBe("bob");
    expect(saved!.status).toBe("open");
    expect(saved!.reportIncluded).toBe(false);
  });

  it("uses 'unassigned' as default owner", async () => {
    const result = await createTaskTool.execute({
      context: { title: "Investigate performance issue", owner: "unassigned" },
      runId: "test-run",
      mastra: undefined as never,
      resourceId: undefined,
      threadId: undefined,
      runtimeContext: undefined as never,
    });

    const saved = await getTaskById(result.taskId);
    expect(saved!.owner).toBe("unassigned");
  });

  it("creates tasks with sequential IDs", async () => {
    const r1 = await createTaskTool.execute({
      context: { title: "Task One", owner: "alice" },
      runId: "run1",
      mastra: undefined as never,
      resourceId: undefined,
      threadId: undefined,
      runtimeContext: undefined as never,
    });
    const r2 = await createTaskTool.execute({
      context: { title: "Task Two", owner: "bob" },
      runId: "run2",
      mastra: undefined as never,
      resourceId: undefined,
      threadId: undefined,
      runtimeContext: undefined as never,
    });

    const all = await getAllTasks();
    expect(all).toHaveLength(2);
    expect(r1.taskId).not.toBe(r2.taskId);
  });

  it("sets createdDate to today's ISO date", async () => {
    const today = new Date().toISOString().split("T")[0];
    const result = await createTaskTool.execute({
      context: { title: "Deploy to staging", owner: "carol" },
      runId: "test-run",
      mastra: undefined as never,
      resourceId: undefined,
      threadId: undefined,
      runtimeContext: undefined as never,
    });
    const saved = await getTaskById(result.taskId);
    expect(saved!.createdDate).toBe(today);
  });
});
