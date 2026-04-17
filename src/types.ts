/**
 * types.ts — Shared TypeScript types
 * Mirrors pipeline/schema.py so both layers stay in sync.
 */

// ── Task ──────────────────────────────────────────────────────────────────────

export type TaskStatus = "open" | "in_progress" | "done" | "blocked";

export interface TaskItem {
  id: string;           // e.g. "T7"
  title: string;
  owner: string;        // Discord username or "unassigned"
  status: TaskStatus;
  threadId: number | null;   // Discord thread ID once created
  createdDate: string;       // ISO date string
  reportIncluded: boolean;   // whether this task appeared in a report
  jiraKey?: string;          // e.g. "SCRUM-42" once synced to Jira
}

// ── User Story (Phase 2 GraphRAG) ─────────────────────────────────────────────

export interface UserStory {
  id: string;           // e.g. "US-12"
  title: string;        // "As a [user], I can [action] so that [value]"
  source: string;       // "sprint-discuss/<thread-name>"
  acceptanceCriteria: string[];
  subtasks: Array<{ title: string; owner: string }>;
  epicId?: string;
  sprintId?: string;
  jiraKey?: string;
}

// ── Sprint state (stored in SQLite via Mastra) ────────────────────────────────

export interface SprintState {
  sprintNumber: number;
  sprintStart: string | null;
  sprintEnd: string | null;
  lastReportDate: string | null;
  tasks: TaskItem[];
  pendingConfirmations: Record<string, PendingConfirmation>;
}

export interface PendingConfirmation {
  taskTitle: string;
  taskOwner: string;
}

// ── Pipeline API payloads (matching pipeline/api.py Pydantic models) ──────────

export interface RawMessages {
  [channelOrThread: string]: string[];
}

export interface SummarizeResponse {
  summary: string;
  decisions: string[];
  blockers: string[];
}

export interface ExtractTasksPayload {
  summary: string;
  rawMessages: RawMessages;
}

export interface ExtractTasksResponse {
  tasks: Array<{ title: string; owner: string }>;
}

export interface FullPipelinePayload {
  rawMessages: RawMessages;
  reportDate?: string;
}

export interface FullPipelineResponse {
  summary: string;
  decisions: string[];
  blockers: string[];
  newTasks: Array<{ title: string; owner: string }>;
  reportMd: string;
}

// ── Discord channel config ────────────────────────────────────────────────────

export interface ChannelConfig {
  sprintDiscuss: string;
  standup: string;
  tasks: string;
  blockers: string;
  aiReport: string;
  changelog: string;
}

// ── Scrum agent action (mirrors thread_agent.py action enum) ─────────────────

export type AgentAction =
  | "propose_task"
  | "ask_clarification"
  | "confirm_task"
  | "reject_task"
  | "answer_question"
  | "note_decision"
  | "silent";

export interface AgentResult {
  action: AgentAction;
  message?: string;
  taskTitle?: string;
  taskOwner?: string;
}
