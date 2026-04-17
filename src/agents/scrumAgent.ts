/**
 * src/agents/scrumAgent.ts — Mastra Scrum Master Agent
 *
 * Replaces pipeline/thread_agent.py.
 * Same responsibilities — reads thread context, decides action, returns JSON.
 * Now backed by Mastra Agent + typed tools instead of raw LangChain LLM calls.
 */

import { Agent, type AgentConfig } from "@mastra/core/agent";
import { createGroq } from "@ai-sdk/groq";
import { createTaskTool } from "../tools/createTask.js";
import { queryTasksTool } from "../tools/queryTasks.js";
import { jiraSyncTool } from "../tools/jiraSync.js";
import type { AgentResult, TaskItem, PendingConfirmation } from "../types.js";

// ── LLM provider ──────────────────────────────────────────────────────────────

const groq = createGroq({ apiKey: process.env.GROQ_API_KEY ?? "" });

// ── System prompt (mirrors prompts/scrum_master.md intent) ───────────────────

const SYSTEM_PROMPT = `You are a Scrum Master embedded in your team's #sprint-discuss Discord channel.
You are a team member, not a bot. Read the conversation carefully and only contribute when genuinely useful.

Your responsibilities:
1. Identify concrete work commitments → propose tracking them as tasks (after confirming with the team)
2. Ask ONE clarifying question when a message is ambiguous before assuming it's a task
3. Answer direct sprint questions (task status, owners, blockers, what was decided)
4. Note important decisions the team locks in
5. Stay silent the rest of the time

GOLDEN RULES:
- PROPOSE a task ONLY when someone is clearly committing to specific, deliverable work
- NEVER propose tasks for: "ignore X", vague ideas, status updates on done work, casual discussion
- ALWAYS ask first if you're not sure — one good question beats a wrong task
- Check thread history: if you already asked about something, don't ask again
- Be brief — max 2 sentences, natural tone, use first names
- When someone shares a file, read it and extract any task commitments from it

PENDING CONFIRMATION:
If context includes "PENDING CONFIRMATION", the latest message may be answering your earlier question.
- Yes signals (yes / yeah / sure / yep / do it / add it / track it / correct / go ahead) → confirm_task
- No signals (no / nah / nope / skip / don't / not a task / just discussion / ignore it) → reject_task
- Ambiguous → silent

RESPOND with valid JSON only — no markdown, no extra text:
{
  "action": "propose_task" | "ask_clarification" | "confirm_task" | "reject_task" | "answer_question" | "note_decision" | "silent",
  "message": "your natural reply (omit if silent)",
  "task_title": "imperative phrase ≤8 words (only for propose_task or confirm_task)",
  "task_owner": "discord_username or unassigned (only for propose_task or confirm_task)"
}`;

// ── Agent definition ──────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const scrumAgent: Agent<string, any> = new Agent({
  name: "ScrumMasterAgent",
  instructions: SYSTEM_PROMPT,
  model: groq("llama-3.3-70b-versatile"),
  tools: {
    create_task: createTaskTool,
    query_tasks: queryTasksTool,
    jira_sync: jiraSyncTool,
  },
});

// ── Main inference function ───────────────────────────────────────────────────

export async function runThreadAgent(params: {
  messageContent: string;
  author: string;
  threadHistory: string[];
  sprintTasks: TaskItem[];
  pendingConfirmation?: PendingConfirmation | null;
  attachmentText?: string | null;
}): Promise<AgentResult> {
  const { messageContent, author, threadHistory, sprintTasks, pendingConfirmation, attachmentText } = params;

  const historyBlock = threadHistory.length > 0 ? threadHistory.join("\n") : "(start of thread)";

  const openTasks = sprintTasks
    .filter((t) => ["open", "in_progress"].includes(t.status))
    .slice(-10)
    .map((t) => `  ${t.id}: ${t.title} → ${t.owner}`)
    .join("\n") || "  (none yet)";

  const pendingBlock = pendingConfirmation
    ? `\nPENDING CONFIRMATION: You already asked whether to track "${pendingConfirmation.taskTitle}" as a task for ${pendingConfirmation.taskOwner}. Check if the latest message is answering that.\n`
    : "";

  const attachmentBlock = attachmentText
    ? `\nFILE ATTACHMENT shared by ${author}:\n${attachmentText.slice(0, 2000)}\n`
    : "";

  const userPrompt = `=== THREAD HISTORY (oldest → latest) ===
${historyBlock}
${pendingBlock}${attachmentBlock}
=== CURRENT SPRINT TASKS ===
${openTasks}

=== LATEST MESSAGE from ${author} ===
${messageContent}

Decide what to do. Respond ONLY with valid JSON.`;

  try {
    const response = await scrumAgent.generate([{ role: "user", content: userPrompt }]);
    const text = response.text ?? "";
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}") + 1;

    if (start !== -1 && end > start) {
      const parsed = JSON.parse(text.slice(start, end)) as Record<string, unknown>;
      return {
        action: (parsed.action as AgentResult["action"]) ?? "silent",
        message: parsed.message as string | undefined,
        taskTitle: (parsed.task_title as string) ?? undefined,
        taskOwner: (parsed.task_owner as string) ?? undefined,
      };
    }
  } catch (err) {
    console.warn("[scrumAgent] inference failed:", err);
  }

  return { action: "silent" };
}
