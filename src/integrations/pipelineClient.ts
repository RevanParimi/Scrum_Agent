/**
 * src/integrations/pipelineClient.ts — HTTP client for Python FastAPI pipeline
 *
 * TypeScript bot layer calls these functions; the Python AI pipeline
 * handles all LLM work and returns structured results.
 */

import axios, { type AxiosInstance } from "axios";
import type {
  RawMessages,
  SummarizeResponse,
  ExtractTasksPayload,
  ExtractTasksResponse,
  FullPipelinePayload,
  FullPipelineResponse,
} from "../types.js";

const BASE_URL = process.env.PIPELINE_API_URL ?? "http://localhost:8000";

const http: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 120_000,   // LLM calls can be slow
  headers: { "Content-Type": "application/json" },
});

export async function checkPipelineHealth(): Promise<boolean> {
  try {
    const res = await http.get("/health");
    return res.data?.status === "ok";
  } catch {
    return false;
  }
}

export async function summarizeMessages(rawMessages: RawMessages): Promise<SummarizeResponse> {
  const res = await http.post<SummarizeResponse>("/pipeline/summarize", {
    raw_messages: rawMessages,
  });
  return res.data;
}

export async function extractTasks(payload: ExtractTasksPayload): Promise<ExtractTasksResponse> {
  const res = await http.post<ExtractTasksResponse>("/pipeline/extract-tasks", {
    summary: payload.summary,
    raw_messages: payload.rawMessages,
  });
  return res.data;
}

export async function runFullPipeline(payload: FullPipelinePayload): Promise<FullPipelineResponse> {
  const res = await http.post<FullPipelineResponse>("/pipeline/run", {
    raw_messages: payload.rawMessages,
    report_date: payload.reportDate,
  });
  // Normalise snake_case → camelCase from Python response
  const data = res.data as unknown as Record<string, unknown>;
  return {
    summary: data["summary"] as string,
    decisions: data["decisions"] as string[],
    blockers: data["blockers"] as string[],
    newTasks: (data["new_tasks"] ?? data["newTasks"]) as FullPipelineResponse["newTasks"],
    reportMd: (data["report_md"] ?? data["reportMd"]) as string,
  };
}
