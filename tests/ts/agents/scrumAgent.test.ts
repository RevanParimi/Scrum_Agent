/**
 * tests/ts/agents/scrumAgent.test.ts
 *
 * Tests for runThreadAgent — the Mastra Scrum Master agent.
 *
 * DUMMY LLM: Mastra Agent.generate() is mocked via vi.hoisted.
 * No real Groq/LLM API calls are made. Each test controls the exact
 * JSON the "LLM" returns so we verify how responses are parsed and
 * routed without touching external services.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { TaskItem } from "../../../src/types.js";

// ── vi.hoisted: declare mock BEFORE vi.mock factory runs ──────────────────────

const { mockGenerate } = vi.hoisted(() => ({
  mockGenerate: vi.fn(),
}));

vi.mock("@mastra/core/agent", () => ({
  Agent: class MockAgent {
    generate = mockGenerate;
  },
  AgentConfig: {},
}));

import { runThreadAgent } from "../../../src/agents/scrumAgent.js";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const openTasks: TaskItem[] = [
  { id: "T1", title: "Build login page", owner: "alice", status: "open", threadId: null, createdDate: "2026-04-14", reportIncluded: true },
  { id: "T2", title: "Fix API timeout",  owner: "bob",   status: "open", threadId: null, createdDate: "2026-04-14", reportIncluded: true },
];

function llmReturns(json: object) {
  mockGenerate.mockResolvedValueOnce({ text: JSON.stringify(json) });
}

function llmReturnsInProse(json: object) {
  mockGenerate.mockResolvedValueOnce({
    text: `Here is my decision:\n\`\`\`json\n${JSON.stringify(json)}\n\`\`\``,
  });
}

beforeEach(() => vi.clearAllMocks());

// ── Action routing ────────────────────────────────────────────────────────────

describe("runThreadAgent — action routing", () => {
  it("returns silent when LLM returns action=silent", async () => {
    llmReturns({ action: "silent" });
    const result = await runThreadAgent({ messageContent: "hey all just a quick update", author: "dave", threadHistory: [], sprintTasks: openTasks });
    expect(result.action).toBe("silent");
    expect(result.message).toBeUndefined();
  });

  it("returns propose_task with task details", async () => {
    llmReturns({ action: "propose_task", message: "Should I track this for Alice?", task_title: "Build login page", task_owner: "alice" });
    const result = await runThreadAgent({ messageContent: "Alice, can you build the login page?", author: "bob", threadHistory: [], sprintTasks: openTasks });
    expect(result.action).toBe("propose_task");
    expect(result.message).toContain("Alice");
    expect(result.taskTitle).toBe("Build login page");
    expect(result.taskOwner).toBe("alice");
  });

  it("returns confirm_task when team says yes", async () => {
    llmReturns({ action: "confirm_task", message: "Done, task created!" });
    const result = await runThreadAgent({
      messageContent: "yep go ahead",
      author: "alice",
      threadHistory: [],
      sprintTasks: openTasks,
      pendingConfirmation: { taskTitle: "Build login page", taskOwner: "alice" },
    });
    expect(result.action).toBe("confirm_task");
  });

  it("returns reject_task when team declines", async () => {
    llmReturns({ action: "reject_task", message: "Got it, won't track it." });
    const result = await runThreadAgent({
      messageContent: "nah skip it",
      author: "alice",
      threadHistory: [],
      sprintTasks: openTasks,
      pendingConfirmation: { taskTitle: "Build login page", taskOwner: "alice" },
    });
    expect(result.action).toBe("reject_task");
  });

  it("returns ask_clarification with a question", async () => {
    llmReturns({ action: "ask_clarification", message: "Is this for mobile or web?" });
    const result = await runThreadAgent({ messageContent: "need to fix the navigation", author: "carol", threadHistory: [], sprintTasks: openTasks });
    expect(result.action).toBe("ask_clarification");
    expect(result.message).toBeTruthy();
  });

  it("returns answer_question with sprint context", async () => {
    llmReturns({ action: "answer_question", message: "T1 is owned by alice — status: open." });
    const result = await runThreadAgent({ messageContent: "who owns the login page?", author: "dave", threadHistory: [], sprintTasks: openTasks });
    expect(result.action).toBe("answer_question");
    expect(result.message).toContain("alice");
  });

  it("returns note_decision for locked decisions", async () => {
    llmReturns({ action: "note_decision", message: "Noted — using JWT for auth." });
    const result = await runThreadAgent({ messageContent: "we are going with JWT, final decision", author: "lead", threadHistory: [], sprintTasks: openTasks });
    expect(result.action).toBe("note_decision");
  });
});

// ── Robustness ────────────────────────────────────────────────────────────────

describe("runThreadAgent — robustness", () => {
  it("returns silent when LLM throws", async () => {
    mockGenerate.mockRejectedValueOnce(new Error("LLM API rate limit"));
    const result = await runThreadAgent({ messageContent: "anything", author: "user", threadHistory: [], sprintTasks: [] });
    expect(result.action).toBe("silent");
  });

  it("extracts JSON even when LLM wraps it in prose", async () => {
    llmReturnsInProse({ action: "silent" });
    const result = await runThreadAgent({ messageContent: "casual message", author: "user", threadHistory: [], sprintTasks: [] });
    expect(result.action).toBe("silent");
  });

  it("returns silent when LLM returns plain text with no JSON", async () => {
    mockGenerate.mockResolvedValueOnce({ text: "oops, just plain text" });
    const result = await runThreadAgent({ messageContent: "anything", author: "user", threadHistory: [], sprintTasks: [] });
    expect(result.action).toBe("silent");
  });

  it("includes attachment text in the prompt", async () => {
    llmReturns({ action: "silent" });
    await runThreadAgent({ messageContent: "here is the spec", author: "alice", threadHistory: [], sprintTasks: [], attachmentText: "# Feature Spec\nBuild OAuth2 login" });
    const callArg = mockGenerate.mock.calls[0][0];
    expect(callArg[0].content).toContain("Feature Spec");
  });

  it("includes PENDING CONFIRMATION block when a confirmation is pending", async () => {
    llmReturns({ action: "confirm_task" });
    await runThreadAgent({
      messageContent: "yes",
      author: "bob",
      threadHistory: [],
      sprintTasks: [],
      pendingConfirmation: { taskTitle: "Fix login", taskOwner: "bob" },
    });
    const callArg = mockGenerate.mock.calls[0][0];
    expect(callArg[0].content).toContain("PENDING CONFIRMATION");
    expect(callArg[0].content).toContain("Fix login");
  });

  it("includes thread history in the prompt", async () => {
    llmReturns({ action: "silent" });
    await runThreadAgent({
      messageContent: "follow up",
      author: "carol",
      threadHistory: ["[alice]: we decided on JWT", "[bob]: agreed"],
      sprintTasks: [],
    });
    const callArg = mockGenerate.mock.calls[0][0];
    expect(callArg[0].content).toContain("we decided on JWT");
  });
});
