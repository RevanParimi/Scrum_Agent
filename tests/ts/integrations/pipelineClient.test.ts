/**
 * tests/ts/integrations/pipelineClient.test.ts
 *
 * Tests for the HTTP client that calls the Python FastAPI pipeline.
 * DUMMY PIPELINE: axios is fully mocked via vi.hoisted — no real Python server.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ── vi.hoisted: declare mocks before vi.mock factory runs ─────────────────────

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet:  vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock("axios", async () => {
  const actual = await vi.importActual<typeof import("axios")>("axios");
  return {
    ...actual,
    default: {
      ...actual.default,
      create: () => ({ get: mockGet, post: mockPost }),
    },
  };
});

import {
  checkPipelineHealth,
  summarizeMessages,
  extractTasks,
  runFullPipeline,
} from "../../../src/integrations/pipelineClient.js";

beforeEach(() => vi.clearAllMocks());

// ── Health check ──────────────────────────────────────────────────────────────

describe("checkPipelineHealth", () => {
  it("returns true when API returns status=ok", async () => {
    mockGet.mockResolvedValueOnce({ data: { status: "ok" } });
    expect(await checkPipelineHealth()).toBe(true);
  });

  it("returns false when API is unreachable", async () => {
    mockGet.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    expect(await checkPipelineHealth()).toBe(false);
  });

  it("returns false when API returns unexpected status", async () => {
    mockGet.mockResolvedValueOnce({ data: { status: "degraded" } });
    expect(await checkPipelineHealth()).toBe(false);
  });
});

// ── Summarize ─────────────────────────────────────────────────────────────────

describe("summarizeMessages", () => {
  it("POSTs raw_messages and returns structured summary", async () => {
    mockPost.mockResolvedValueOnce({
      data: { summary: "Team discussed auth.", decisions: ["Use JWT"], blockers: ["CI broken"] },
    });
    const result = await summarizeMessages({
      standup:  ["[09:00] alice: working on JWT auth"],
      blockers: ["[09:05] bob: CI is broken"],
    });
    expect(result.summary).toBe("Team discussed auth.");
    expect(result.decisions).toContain("Use JWT");
    expect(result.blockers).toHaveLength(1);
    expect(mockPost).toHaveBeenCalledWith("/pipeline/summarize", { raw_messages: expect.any(Object) });
  });
});

// ── Extract tasks ─────────────────────────────────────────────────────────────

describe("extractTasks", () => {
  it("POSTs summary+messages and returns task list", async () => {
    mockPost.mockResolvedValueOnce({
      data: { tasks: [{ title: "Fix CI", owner: "bob" }, { title: "Implement JWT", owner: "alice" }] },
    });
    const result = await extractTasks({ summary: "Team working on auth and CI.", rawMessages: { standup: ["alice: auth"] } });
    expect(result.tasks).toHaveLength(2);
    expect(result.tasks[0].title).toBe("Fix CI");
  });
});

// ── Full pipeline ─────────────────────────────────────────────────────────────

describe("runFullPipeline", () => {
  it("normalises snake_case to camelCase from Python response", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        summary: "Good sprint.",
        decisions: ["Ship X"],
        blockers: [],
        new_tasks: [{ title: "Deploy X", owner: "carol" }],
        report_md: "## 2026-04-16\nGood sprint.",
      },
    });
    const result = await runFullPipeline({ rawMessages: { standup: ["carol: deploying"] }, reportDate: "2026-04-16" });
    expect(result.summary).toBe("Good sprint.");
    expect(result.newTasks).toHaveLength(1);
    expect(result.newTasks[0].title).toBe("Deploy X");
    expect(result.reportMd).toContain("2026-04-16");
  });

  it("POSTs to /pipeline/run with correct snake_case payload", async () => {
    mockPost.mockResolvedValueOnce({
      data: { summary: "", decisions: [], blockers: [], new_tasks: [], report_md: "" },
    });
    await runFullPipeline({ rawMessages: { standup: ["test"] }, reportDate: "2026-04-16" });
    expect(mockPost).toHaveBeenCalledWith("/pipeline/run", {
      raw_messages: { standup: ["test"] },
      report_date: "2026-04-16",
    });
  });
});
