/**
 * src/workflows/dailyPipeline.ts — Mastra Workflow
 *
 * Replaces pipeline/graph.py (LangGraph).
 * Steps: run_pipeline (Python AI) → persist_tasks (SQLite)
 *
 * Discord ingestion happens in TypeScript (discord.js) before this workflow.
 * AI summarization + task extraction is delegated to the Python FastAPI bridge.
 */

import { createWorkflow, createStep } from "@mastra/core/workflows";
import { z } from "zod";
import {
  upsertTask,
  nextTaskId,
  getOpenTasks,
  getUnreportedTasks,
  markTasksReported,
} from "../memory/index.js";
import { runFullPipeline } from "../integrations/pipelineClient.js";
import type { TaskItem, RawMessages } from "../types.js";

// ── Shared schemas ─────────────────────────────────────────────────────────────

const rawMessagesSchema = z.record(z.string(), z.array(z.string()));

const taskDraftSchema = z.object({ title: z.string(), owner: z.string() });

// ── Step 1: Call Python pipeline (summarize + extract tasks) ──────────────────

const runPipelineStep = createStep({
  id: "run_pipeline",
  description: "Send ingested Discord messages to Python AI pipeline",
  inputSchema: z.object({
    rawMessages: rawMessagesSchema,
    reportDate: z.string(),
  }),
  outputSchema: z.object({
    summary: z.string(),
    decisions: z.array(z.string()),
    blockers: z.array(z.string()),
    newTaskDrafts: z.array(taskDraftSchema),
    reportMd: z.string(),
    reportDate: z.string(),   // passed through so step 2 can use it
  }),
  execute: async ({ inputData }) => {
    const result = await runFullPipeline({
      rawMessages: inputData.rawMessages,
      reportDate: inputData.reportDate,
    });
    return {
      summary: result.summary,
      decisions: result.decisions,
      blockers: result.blockers,
      newTaskDrafts: result.newTasks,
      reportMd: result.reportMd,
      reportDate: inputData.reportDate,
    };
  },
});

// ── Step 2: Persist new tasks to SQLite ───────────────────────────────────────

const persistTasksStep = createStep({
  id: "persist_tasks",
  description: "Save extracted tasks to SQLite; collect any unreported interactive tasks",
  inputSchema: z.object({
    summary: z.string(),
    decisions: z.array(z.string()),
    blockers: z.array(z.string()),
    newTaskDrafts: z.array(taskDraftSchema),
    reportMd: z.string(),
    reportDate: z.string(),
  }),
  outputSchema: z.object({
    savedTaskIds: z.array(z.string()),
    allOpenTasks: z.array(
      z.object({ id: z.string(), title: z.string(), owner: z.string(), status: z.string() })
    ),
  }),
  execute: async ({ inputData }) => {
    const today = inputData.reportDate;

    // Collect interactive tasks confirmed via Discord but not yet reported
    const unreported = await getUnreportedTasks();
    const savedTaskIds: string[] = unreported.map((t) => t.id);

    // Save pipeline-extracted tasks
    for (const draft of inputData.newTaskDrafts) {
      const taskId = await nextTaskId();
      const task: TaskItem = {
        id: taskId,
        title: draft.title,
        owner: draft.owner ?? "unassigned",
        status: "open",
        threadId: null,
        createdDate: today,
        reportIncluded: true,
      };
      await upsertTask(task);
      savedTaskIds.push(taskId);
    }

    // Mark unreported interactive tasks as now in a report
    await markTasksReported(unreported.map((t) => t.id));

    const allOpenTasks = await getOpenTasks();
    return {
      savedTaskIds,
      allOpenTasks: allOpenTasks.map((t) => ({
        id: t.id,
        title: t.title,
        owner: t.owner,
        status: t.status,
      })),
    };
  },
});

// ── Workflow assembly ─────────────────────────────────────────────────────────

export const dailyPipelineWorkflow = createWorkflow({
  id: "daily_pipeline",
  description: "Daily scrum digest: Discord messages → Python AI → SQLite tasks",
  inputSchema: z.object({
    rawMessages: rawMessagesSchema,
    reportDate: z.string(),
  }),
  outputSchema: z.object({
    savedTaskIds: z.array(z.string()),
    allOpenTasks: z.array(
      z.object({ id: z.string(), title: z.string(), owner: z.string(), status: z.string() })
    ),
  }),
})
  .then(runPipelineStep)
  .then(persistTasksStep)
  .commit();

// ── Runner helper (called from scheduler + !report command) ───────────────────

export async function runDailyPipeline(
  rawMessages: RawMessages,
  reportDate?: string
): Promise<{
  summary: string;
  decisions: string[];
  blockers: string[];
  savedTaskIds: string[];
  reportMd: string;
}> {
  const date = reportDate ?? new Date().toISOString().split("T")[0];

  const run = dailyPipelineWorkflow.createRun();
  const result = await run.start({ inputData: { rawMessages, reportDate: date } });

  if (result.status !== "success") {
    throw new Error(`Pipeline workflow failed: ${JSON.stringify(result)}`);
  }

  const pipelineStep = result.steps["run_pipeline"];
  const persistStep = result.steps["persist_tasks"];

  if (pipelineStep?.status !== "success" || persistStep?.status !== "success") {
    throw new Error("One or more pipeline steps failed");
  }

  return {
    summary: pipelineStep.output.summary,
    decisions: pipelineStep.output.decisions,
    blockers: pipelineStep.output.blockers,
    savedTaskIds: persistStep.output.savedTaskIds,
    reportMd: pipelineStep.output.reportMd,
  };
}
