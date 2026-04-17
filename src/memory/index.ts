/**
 * src/memory/index.ts — Sprint state persistence via LibSQL (SQLite)
 *
 * Replaces the fragile sprint_state.json with a proper SQLite database.
 * Two tables:
 *   sprint_state   — single-row KV blob (sprint metadata)
 *   tasks          — one row per task, queryable by status/owner
 *   pending_confirmations — per-channel pending task proposals
 */

import { createClient, type Client } from "@libsql/client";
import type { TaskItem, SprintState, PendingConfirmation } from "../types.js";
import * as path from "path";
import * as fs from "fs";

// ── DB client (singleton) ────────────────────────────────────────────────────

let _client: Client | null = null;

function getClient(): Client {
  if (_client) return _client;
  const dbPath = process.env.LIBSQL_URL ?? "file:./state/scrum.db";
  // Ensure state directory exists
  if (dbPath.startsWith("file:")) {
    const filePath = dbPath.replace("file:", "");
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  }
  _client = createClient({ url: dbPath });
  return _client;
}

// ── Schema bootstrap ─────────────────────────────────────────────────────────

/** Drop and recreate all tables — used in tests to reset state between cases. */
export async function clearDb(): Promise<void> {
  const db = getClient();
  await db.batch([
    { sql: "DELETE FROM tasks",                  args: [] },
    { sql: "DELETE FROM sprint_meta",            args: [] },
    { sql: "DELETE FROM pending_confirmations",  args: [] },
  ]);
}

export async function initDb(): Promise<void> {
  const db = getClient();
  await db.batch([
    {
      sql: `CREATE TABLE IF NOT EXISTS sprint_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )`,
      args: [],
    },
    {
      sql: `CREATE TABLE IF NOT EXISTS tasks (
        id               TEXT PRIMARY KEY,
        title            TEXT NOT NULL,
        owner            TEXT NOT NULL DEFAULT 'unassigned',
        status           TEXT NOT NULL DEFAULT 'open',
        thread_id        INTEGER,
        created_date     TEXT NOT NULL,
        report_included  INTEGER NOT NULL DEFAULT 0,
        jira_key         TEXT,
        sprint_number    INTEGER NOT NULL DEFAULT 1
      )`,
      args: [],
    },
    {
      sql: `CREATE TABLE IF NOT EXISTS pending_confirmations (
        channel_id   TEXT PRIMARY KEY,
        task_title   TEXT NOT NULL,
        task_owner   TEXT NOT NULL DEFAULT 'unassigned',
        created_at   TEXT NOT NULL
      )`,
      args: [],
    },
  ]);
}

// ── Sprint meta ───────────────────────────────────────────────────────────────

async function getMeta(key: string): Promise<string | null> {
  const db = getClient();
  const result = await db.execute({ sql: "SELECT value FROM sprint_meta WHERE key = ?", args: [key] });
  return (result.rows[0]?.value as string) ?? null;
}

async function setMeta(key: string, value: string): Promise<void> {
  const db = getClient();
  await db.execute({
    sql: "INSERT OR REPLACE INTO sprint_meta (key, value) VALUES (?, ?)",
    args: [key, value],
  });
}

export async function getSprintNumber(): Promise<number> {
  return parseInt((await getMeta("sprint_number")) ?? "1", 10);
}

export async function setSprintNumber(n: number): Promise<void> {
  await setMeta("sprint_number", String(n));
}

export async function getLastReportDate(): Promise<string | null> {
  return getMeta("last_report_date");
}

export async function setLastReportDate(d: string): Promise<void> {
  await setMeta("last_report_date", d);
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export async function getAllTasks(): Promise<TaskItem[]> {
  const db = getClient();
  const result = await db.execute("SELECT * FROM tasks ORDER BY id");
  return result.rows.map(rowToTask);
}

export async function getOpenTasks(): Promise<TaskItem[]> {
  const db = getClient();
  const result = await db.execute({
    sql: "SELECT * FROM tasks WHERE status != 'done' ORDER BY id",
    args: [],
  });
  return result.rows.map(rowToTask);
}

export async function getTaskById(id: string): Promise<TaskItem | null> {
  const db = getClient();
  const result = await db.execute({ sql: "SELECT * FROM tasks WHERE id = ?", args: [id] });
  return result.rows[0] ? rowToTask(result.rows[0]) : null;
}

export async function upsertTask(task: TaskItem): Promise<void> {
  const db = getClient();
  await db.execute({
    sql: `INSERT OR REPLACE INTO tasks
          (id, title, owner, status, thread_id, created_date, report_included, jira_key, sprint_number)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    args: [
      task.id,
      task.title,
      task.owner,
      task.status,
      task.threadId ?? null,
      task.createdDate,
      task.reportIncluded ? 1 : 0,
      task.jiraKey ?? null,
      await getSprintNumber(),
    ],
  });
}

export async function updateTaskStatus(id: string, status: TaskItem["status"]): Promise<void> {
  const db = getClient();
  await db.execute({ sql: "UPDATE tasks SET status = ? WHERE id = ?", args: [status, id] });
}

export async function nextTaskId(): Promise<string> {
  const db = getClient();
  const result = await db.execute("SELECT id FROM tasks ORDER BY id");
  const nums = result.rows
    .map((r) => parseInt((r.id as string).replace(/\D/g, ""), 10))
    .filter((n) => !isNaN(n));
  const max = nums.length > 0 ? Math.max(...nums) : 0;
  return `T${max + 1}`;
}

export async function getUnreportedTasks(): Promise<TaskItem[]> {
  const db = getClient();
  const result = await db.execute({
    sql: "SELECT * FROM tasks WHERE report_included = 0",
    args: [],
  });
  return result.rows.map(rowToTask);
}

export async function markTasksReported(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const db = getClient();
  const placeholders = ids.map(() => "?").join(",");
  await db.execute({
    sql: `UPDATE tasks SET report_included = 1 WHERE id IN (${placeholders})`,
    args: ids,
  });
}

// ── Pending confirmations ─────────────────────────────────────────────────────

export async function getPendingConfirmation(channelId: string): Promise<PendingConfirmation | null> {
  const db = getClient();
  const result = await db.execute({
    sql: "SELECT * FROM pending_confirmations WHERE channel_id = ?",
    args: [channelId],
  });
  if (!result.rows[0]) return null;
  return {
    taskTitle: result.rows[0].task_title as string,
    taskOwner: result.rows[0].task_owner as string,
  };
}

export async function setPendingConfirmation(channelId: string, confirmation: PendingConfirmation): Promise<void> {
  const db = getClient();
  await db.execute({
    sql: `INSERT OR REPLACE INTO pending_confirmations (channel_id, task_title, task_owner, created_at)
          VALUES (?, ?, ?, ?)`,
    args: [channelId, confirmation.taskTitle, confirmation.taskOwner, new Date().toISOString()],
  });
}

export async function deletePendingConfirmation(channelId: string): Promise<void> {
  const db = getClient();
  await db.execute({
    sql: "DELETE FROM pending_confirmations WHERE channel_id = ?",
    args: [channelId],
  });
}

// ── Row mapper ─────────────────────────────────────────────────────────────────

function rowToTask(row: Record<string, unknown>): TaskItem {
  return {
    id: row.id as string,
    title: row.title as string,
    owner: row.owner as string,
    status: row.status as TaskItem["status"],
    threadId: row.thread_id != null ? Number(row.thread_id) : null,
    createdDate: row.created_date as string,
    reportIncluded: Boolean(row.report_included),
    jiraKey: (row.jira_key as string) ?? undefined,
  };
}
