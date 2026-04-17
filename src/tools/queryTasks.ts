/**
 * src/tools/queryTasks.ts — Mastra Tool
 *
 * Lets the scrum agent answer questions like:
 *   "What are the open tasks?"
 *   "What is Alice working on?"
 *   "Are there any blocked tasks?"
 */

import { createTool } from "@mastra/core/tools";
import { z } from "zod";
import { getAllTasks, getOpenTasks } from "../memory/index.js";

export const queryTasksTool = createTool({
  id: "query_tasks",
  description:
    "Query the current sprint task list. Use this to answer team questions about task status, owners, or blockers.",
  inputSchema: z.object({
    filter: z
      .enum(["all", "open", "blocked", "done", "by_owner"])
      .default("open")
      .describe("Which tasks to return"),
    owner: z.string().optional().describe("Filter by owner username (only used when filter = by_owner)"),
  }),
  outputSchema: z.object({
    tasks: z.array(
      z.object({
        id: z.string(),
        title: z.string(),
        owner: z.string(),
        status: z.string(),
        createdDate: z.string(),
        jiraKey: z.string().optional(),
      })
    ),
    count: z.number(),
  }),
  execute: async ({ context }) => {
    const allTasks = context.filter === "open" ? await getOpenTasks() : await getAllTasks();

    let filtered = allTasks;

    if (context.filter === "blocked") {
      filtered = allTasks.filter((t) => t.status === "blocked");
    } else if (context.filter === "done") {
      filtered = allTasks.filter((t) => t.status === "done");
    } else if (context.filter === "by_owner" && context.owner) {
      const ownerLower = context.owner.toLowerCase();
      filtered = allTasks.filter((t) => t.owner.toLowerCase().includes(ownerLower));
    }

    return {
      tasks: filtered.map((t) => ({
        id: t.id,
        title: t.title,
        owner: t.owner,
        status: t.status,
        createdDate: t.createdDate,
        ...(t.jiraKey && { jiraKey: t.jiraKey }),
      })),
      count: filtered.length,
    };
  },
});
