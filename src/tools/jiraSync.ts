/**
 * src/tools/jiraSync.ts — Mastra Tool
 *
 * Syncs a local sprint task to Jira/iTrack.
 * Scrum master can ask: "sync task T5 to Jira"
 * Agent calls this tool, creates the Jira issue, stores the key back.
 */

import { createTool } from "@mastra/core/tools";
import { z } from "zod";
import { getTaskById, upsertTask } from "../memory/index.js";
import { createIssue } from "../integrations/jira.js";

export const jiraSyncTool = createTool({
  id: "jira_sync",
  description:
    "Create a Jira/iTrack issue for a local sprint task and link them. Use when team wants a task tracked in both Discord and Jira.",
  inputSchema: z.object({
    taskId: z.string().describe("Local task ID, e.g. T5"),
    issueType: z.enum(["Task", "Story", "Bug"]).default("Task"),
  }),
  outputSchema: z.object({
    jiraKey: z.string(),
    message: z.string(),
  }),
  execute: async ({ context }) => {
    const task = await getTaskById(context.taskId);
    if (!task) throw new Error(`Task ${context.taskId} not found`);

    const issue = await createIssue({
      summary: task.title,
      issueType: context.issueType,
      description: `Created by Scrum Agent from Discord. Local ID: ${task.id}. Owner: ${task.owner}`,
    });

    // Store the Jira key back in local DB
    await upsertTask({ ...task, jiraKey: issue.key });

    return {
      jiraKey: issue.key,
      message: `Synced ${task.id} → Jira ${issue.key}: "${task.title}"`,
    };
  },
});
