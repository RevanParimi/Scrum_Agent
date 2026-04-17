/**
 * src/integrations/jira.ts — Typed Jira / iTrack REST client
 *
 * Covers the operations Scrum Masters need most:
 *   - Create issues (tasks, user stories, bugs)
 *   - Update issue status / assignee
 *   - Fetch sprint issues
 *   - Add comments
 *
 * Uses Jira Cloud REST API v3. For iTrack (Jira Server), set
 * JIRA_BASE_URL to your on-prem host — the API is compatible.
 */

import axios, { type AxiosInstance } from "axios";

// ── Config ────────────────────────────────────────────────────────────────────

function getJiraClient(): AxiosInstance {
  const base = process.env.JIRA_BASE_URL;
  const email = process.env.JIRA_USER_EMAIL;
  const token = process.env.JIRA_API_TOKEN;

  if (!base || !email || !token) {
    throw new Error("Missing JIRA_BASE_URL, JIRA_USER_EMAIL, or JIRA_API_TOKEN in environment");
  }

  return axios.create({
    baseURL: `${base}/rest/api/3`,
    auth: { username: email, password: token },
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    timeout: 30_000,
  });
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type IssueType = "Task" | "Story" | "Bug" | "Epic" | "Sub-task";
export type IssueStatus = "To Do" | "In Progress" | "Done" | "Blocked";

export interface JiraIssue {
  key: string;         // e.g. "SCRUM-42"
  id: string;
  summary: string;
  status: string;
  assignee: string | null;
  issueType: string;
  priority: string;
  created: string;
  updated: string;
  storyPoints?: number;
  sprintName?: string;
}

export interface CreateIssueOptions {
  summary: string;
  issueType?: IssueType;
  description?: string;
  assigneeAccountId?: string;
  priority?: "Highest" | "High" | "Medium" | "Low" | "Lowest";
  labels?: string[];
  storyPoints?: number;
  epicKey?: string;
}

export interface SprintInfo {
  id: number;
  name: string;
  state: "active" | "closed" | "future";
  startDate?: string;
  endDate?: string;
}

// ── Issue operations ──────────────────────────────────────────────────────────

export async function createIssue(options: CreateIssueOptions): Promise<JiraIssue> {
  const jira = getJiraClient();
  const projectKey = process.env.JIRA_PROJECT_KEY ?? "SCRUM";

  const body: Record<string, unknown> = {
    fields: {
      project: { key: projectKey },
      summary: options.summary,
      issuetype: { name: options.issueType ?? "Task" },
      priority: { name: options.priority ?? "Medium" },
      ...(options.description && {
        description: {
          type: "doc",
          version: 1,
          content: [{ type: "paragraph", content: [{ type: "text", text: options.description }] }],
        },
      }),
      ...(options.assigneeAccountId && { assignee: { accountId: options.assigneeAccountId } }),
      ...(options.labels && { labels: options.labels }),
      ...(options.storyPoints && { story_points: options.storyPoints }),
      ...(options.epicKey && { "Epic Link": options.epicKey }),
    },
  };

  const res = await jira.post("/issue", body);
  return getIssue(res.data.key);
}

export async function getIssue(key: string): Promise<JiraIssue> {
  const jira = getJiraClient();
  const res = await jira.get(`/issue/${key}`, {
    params: { fields: "summary,status,assignee,issuetype,priority,created,updated,story_points,sprint" },
  });
  return mapIssue(res.data);
}

export async function updateIssueStatus(key: string, transitionName: string): Promise<void> {
  const jira = getJiraClient();
  // Get available transitions
  const transRes = await jira.get(`/issue/${key}/transitions`);
  const transition = transRes.data.transitions.find(
    (t: { name: string }) => t.name.toLowerCase() === transitionName.toLowerCase()
  );
  if (!transition) {
    throw new Error(`Transition "${transitionName}" not found for issue ${key}`);
  }
  await jira.post(`/issue/${key}/transitions`, { transition: { id: transition.id } });
}

export async function addComment(key: string, text: string): Promise<void> {
  const jira = getJiraClient();
  await jira.post(`/issue/${key}/comment`, {
    body: {
      type: "doc",
      version: 1,
      content: [{ type: "paragraph", content: [{ type: "text", text }] }],
    },
  });
}

export async function getSprintIssues(sprintId?: number): Promise<JiraIssue[]> {
  const jira = getJiraClient();
  const projectKey = process.env.JIRA_PROJECT_KEY ?? "SCRUM";

  let jql: string;
  if (sprintId) {
    jql = `project = ${projectKey} AND sprint = ${sprintId} ORDER BY created DESC`;
  } else {
    jql = `project = ${projectKey} AND sprint in openSprints() ORDER BY created DESC`;
  }

  const res = await jira.get("/search", {
    params: { jql, maxResults: 100, fields: "summary,status,assignee,issuetype,priority,created,updated" },
  });
  return res.data.issues.map(mapIssue);
}

export async function getActiveSprint(): Promise<SprintInfo | null> {
  const jira = getJiraClient();
  const projectKey = process.env.JIRA_PROJECT_KEY ?? "SCRUM";

  try {
    // Find the board ID for the project first
    const boardRes = await jira.get("/rest/agile/1.0/board", {
      params: { projectKeyOrId: projectKey },
      baseURL: process.env.JIRA_BASE_URL,
    });
    const boardId = boardRes.data.values?.[0]?.id;
    if (!boardId) return null;

    const sprintRes = await jira.get(`/rest/agile/1.0/board/${boardId}/sprint`, {
      params: { state: "active" },
      baseURL: process.env.JIRA_BASE_URL,
    });
    const sprint = sprintRes.data.values?.[0];
    if (!sprint) return null;

    return {
      id: sprint.id,
      name: sprint.name,
      state: sprint.state,
      startDate: sprint.startDate,
      endDate: sprint.endDate,
    };
  } catch {
    return null;
  }
}

// ── Row mapper ────────────────────────────────────────────────────────────────

function mapIssue(raw: Record<string, unknown>): JiraIssue {
  const fields = raw.fields as Record<string, unknown>;
  const status = (fields.status as Record<string, unknown>)?.name as string;
  const assignee = fields.assignee as Record<string, unknown> | null;
  const issuetype = (fields.issuetype as Record<string, unknown>)?.name as string;
  const priority = (fields.priority as Record<string, unknown>)?.name as string;

  return {
    key: raw.key as string,
    id: raw.id as string,
    summary: fields.summary as string,
    status,
    assignee: (assignee?.displayName as string) ?? null,
    issueType: issuetype,
    priority,
    created: fields.created as string,
    updated: fields.updated as string,
  };
}
