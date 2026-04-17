/**
 * src/tools/createTask.ts — Mastra Tool
 *
 * Creates a new task in SQLite state and optionally syncs to Jira.
 * Called by the Mastra scrum agent when a team member confirms a task.
 */

import { createTool } from "@mastra/core/tools";
import { z } from "zod";
import { upsertTask, nextTaskId } from "../memory/index.js";
import type { TaskItem } from "../types.js";

export const createTaskTool = createTool({
  id: "create_task",
  description:
    "Create a new sprint task and persist it to the database. Call this after the team confirms they want to track a work item.",
  inputSchema: z.object({
    title: z.string().describe("Short imperative task title, 10 words max"),
    owner: z.string().default("unassigned").describe("Discord username of the task owner, or 'unassigned'"),
  }),
  outputSchema: z.object({
    taskId: z.string(),
    message: z.string(),
  }),
  execute: async ({ context }) => {
    const taskId = await nextTaskId();
    const today = new Date().toISOString().split("T")[0];

    const task: TaskItem = {
      id: taskId,
      title: context.title,
      owner: context.owner ?? "unassigned",
      status: "open",
      threadId: null,
      createdDate: today,
      reportIncluded: false,
    };

    await upsertTask(task);

    return {
      taskId,
      message: `Task ${taskId} created: "${context.title}" → owner: ${task.owner}`,
    };
  },
});
