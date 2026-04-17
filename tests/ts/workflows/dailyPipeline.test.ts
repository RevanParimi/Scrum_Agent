/**
 * tests/ts/workflows/dailyPipeline.test.ts
 *
 * Tests for the Mastra dailyPipeline workflow.
 *
 * DUMMY PIPELINE: pipelineClient is mocked — no Python server needed.
 * DUMMY DB: in-memory SQLite via vitest.config.ts env.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { initDb, clearDb, upsertTask, getAllTasks, getTaskById, getUnreportedTasks } from "../../../src/memory/index.js";
import type { TaskItem } from "../../../src/types.js";

// ── Mock Python pipeline client ────────────────────────────────────────────────

vi.mock("../../../src/integrations/pipelineClient.js", () => ({
  runFullPipeline: vi.fn().mockResolvedValue({
    summary: "Team discussed auth and blocker on CI.",
    decisions: ["Use JWT for auth"],
    blockers: ["CI pipeline needs env fix"],
    newTasks: [
      { title: "Fix CI environment variable", owner: "bob" },
      { title: "Implement JWT middleware",     owner: "alice" },
    ],
    reportMd: "## 2026-04-16\n### Summary\nTeam discussed auth.",
  }),
}));

import { runDailyPipeline } from "../../../src/workflows/dailyPipeline.js";

// ── Raw messages fixture (dummy Discord data) ─────────────────────────────────

const dummyRawMessages = {
  standup: [
    "[2026-04-16 09:00] alice: working on JWT auth middleware",
    "[2026-04-16 09:01] bob: blocked on CI — env variable missing",
  ],
  blockers: [
    "[2026-04-16 09:05] bob: PIPELINE_URL env var not set in staging",
  ],
};

beforeEach(async () => {
  await initDb();
  await clearDb();
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("runDailyPipeline", () => {
  it("returns summary, decisions and blockers from AI pipeline", async () => {
    const result = await runDailyPipeline(dummyRawMessages);
    expect(result.summary).toContain("auth");
    expect(result.decisions).toContain("Use JWT for auth");
    expect(result.blockers).toHaveLength(1);
  });

  it("persists extracted tasks to the database", async () => {
    await runDailyPipeline(dummyRawMessages);
    const all = await getAllTasks();
    expect(all.length).toBeGreaterThanOrEqual(2);
    const titles = all.map((t) => t.title);
    expect(titles).toContain("Fix CI environment variable");
    expect(titles).toContain("Implement JWT middleware");
  });

  it("assigns correct owners to persisted tasks", async () => {
    await runDailyPipeline(dummyRawMessages);
    const all = await getAllTasks();
    const ciTask = all.find((t) => t.title === "Fix CI environment variable");
    const jwtTask = all.find((t) => t.title === "Implement JWT middleware");
    expect(ciTask?.owner).toBe("bob");
    expect(jwtTask?.owner).toBe("alice");
  });

  it("marks newly created tasks as reportIncluded=true", async () => {
    await runDailyPipeline(dummyRawMessages);
    const all = await getAllTasks();
    const pipelineTasks = all.filter((t) => ["Fix CI environment variable", "Implement JWT middleware"].includes(t.title));
    expect(pipelineTasks.every((t) => t.reportIncluded)).toBe(true);
  });

  it("returns savedTaskIds containing the new task IDs", async () => {
    const result = await runDailyPipeline(dummyRawMessages);
    expect(result.savedTaskIds.length).toBeGreaterThanOrEqual(2);
    for (const id of result.savedTaskIds) {
      expect(id).toMatch(/^T\d+$/);
    }
  });

  it("returns the report markdown from the pipeline", async () => {
    const result = await runDailyPipeline(dummyRawMessages);
    expect(result.reportMd).toContain("2026-04-16");
  });

  it("flushes unreported interactive tasks into the report", async () => {
    // Simulate a task that was confirmed interactively in Discord
    // but hasn't appeared in a report yet
    const interactiveTask: TaskItem = {
      id: "T99",
      title: "Manual task from Discord",
      owner: "carol",
      status: "open",
      threadId: 123456789,
      createdDate: "2026-04-16",
      reportIncluded: false,   // not yet in a report
    };
    await upsertTask(interactiveTask);

    const result = await runDailyPipeline(dummyRawMessages);

    // T99 should now be included in the saved IDs
    expect(result.savedTaskIds).toContain("T99");

    // And should be marked as reported
    const unreported = await getUnreportedTasks();
    expect(unreported.map((t) => t.id)).not.toContain("T99");
  });

  it("uses today's date when reportDate is not provided", async () => {
    const today = new Date().toISOString().split("T")[0];
    await runDailyPipeline(dummyRawMessages);
    const all = await getAllTasks();
    const pipelineTask = all.find((t) => t.title === "Fix CI environment variable");
    expect(pipelineTask?.createdDate).toBe(today);
  });

  it("accepts a custom reportDate", async () => {
    await runDailyPipeline(dummyRawMessages, "2026-03-01");
    const all = await getAllTasks();
    const task = all.find((t) => t.title === "Fix CI environment variable");
    expect(task?.createdDate).toBe("2026-03-01");
  });
});
