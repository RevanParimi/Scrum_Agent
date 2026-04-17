/**
 * src/bot.ts — Discord bot entry point (TypeScript / discord.js)
 *
 * Replaces bot.py (discord.py).
 *
 * Responsibilities:
 *   1. Connect to Discord via Gateway (WebSocket)
 *   2. Resolve channel objects from env config
 *   3. Start node-cron scheduler once bot is ready
 *   4. Handle slash commands: /report, /sprint, /tasks, /status
 *   5. Auto-create threads in #sprint-discuss on new topic messages
 *   6. Run Mastra scrum agent on thread messages
 *   7. Ingest messages from watched channels for pipeline runs
 */

import "dotenv/config";
import {
  Client,
  GatewayIntentBits,
  Partials,
  REST,
  Routes,
  SlashCommandBuilder,
  type TextChannel,
  type ThreadChannel,
  type Message,
  type Guild,
  type Channel,
  ApplicationCommandOptionType,
} from "discord.js";
import { initDb, upsertTask, nextTaskId, getOpenTasks, getPendingConfirmation, setPendingConfirmation, deletePendingConfirmation } from "./memory/index.js";
import { runThreadAgent } from "./agents/scrumAgent.js";
import { runDailyPipeline } from "./workflows/dailyPipeline.js";
import { startScheduler } from "./scheduler.js";
import { checkPipelineHealth } from "./integrations/pipelineClient.js";
import type { RawMessages, TaskItem } from "./types.js";

// ── Config ────────────────────────────────────────────────────────────────────

const TOKEN = process.env.DISCORD_TOKEN!;
const GUILD_ID = process.env.DISCORD_GUILD_ID!;

const CHANNEL_IDS: Record<string, string> = {
  "sprint-discuss": process.env.CHANNEL_SPRINT_DISCUSS ?? "0",
  standup: process.env.CHANNEL_STANDUP ?? "0",
  tasks: process.env.CHANNEL_TASKS ?? "0",
  blockers: process.env.CHANNEL_BLOCKERS ?? "0",
  "ai-report": process.env.CHANNEL_AI_REPORT ?? "0",
  changelog: process.env.CHANNEL_CHANGELOG ?? "0",
};

const WATCHED_CHANNELS = new Set(["sprint-discuss", "standup", "tasks", "blockers"]);
const READABLE_EXTENSIONS = new Set([".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".yaml", ".yml", ".log", ".xml", ".sh"]);

// ── Discord client ────────────────────────────────────────────────────────────

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMessageReactions,
  ],
  partials: [Partials.Message, Partials.Channel],
});

// Resolved after ready
let guild: Guild | null = null;
let chTasks: TextChannel | null = null;
let chAiReport: TextChannel | null = null;
let chChangelog: TextChannel | null = null;
let chSprintDiscuss: TextChannel | null = null;

// ── Slash command registration ────────────────────────────────────────────────

const commands = [
  new SlashCommandBuilder().setName("report").setDescription("Trigger an immediate daily scrum digest"),
  new SlashCommandBuilder().setName("sprint").setDescription("Trigger the weekly 7-day sprint summary"),
  new SlashCommandBuilder().setName("tasks").setDescription("List all open sprint tasks"),
  new SlashCommandBuilder().setName("status").setDescription("Check bot and pipeline health"),
  new SlashCommandBuilder()
    .setName("task")
    .setDescription("Manually create a task")
    .addStringOption((o) => o.setName("title").setDescription("Task title").setRequired(true))
    .addStringOption((o) => o.setName("owner").setDescription("Owner username").setRequired(false)),
].map((c) => c.toJSON());

async function registerCommands(): Promise<void> {
  const rest = new REST({ version: "10" }).setToken(TOKEN);
  await rest.put(Routes.applicationGuildCommands(client.user!.id, GUILD_ID), { body: commands });
  console.log("[bot] Slash commands registered");
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getChannel(name: string): TextChannel | null {
  const id = CHANNEL_IDS[name];
  if (id && id !== "0" && guild) {
    const ch = guild.channels.cache.get(id);
    if (ch?.isTextBased()) return ch as TextChannel;
  }
  if (guild) {
    const ch = guild.channels.cache.find((c: Channel) => "name" in c && (c as TextChannel).name === name);
    if (ch?.isTextBased()) return ch as TextChannel;
  }
  return null;
}

async function fetchThreadHistory(channel: TextChannel | ThreadChannel, excludeId: string, limit = 15): Promise<string[]> {
  const msgs = await channel.messages.fetch({ limit: limit + 1 });
  return msgs
    .filter((m) => m.id !== excludeId)
    .map((m) => {
      const name = m.author.bot ? "🤖 Scrum Bot" : m.author.displayName ?? m.author.username;
      const attach = m.attachments.size > 0 ? ` [attached: ${[...m.attachments.values()].map((a) => a.name).join(", ")}]` : "";
      return `[${name}]: ${m.content}${attach}`;
    })
    .reverse();
}

async function extractAttachmentText(message: Message): Promise<string | null> {
  for (const attachment of message.attachments.values()) {
    const ext = attachment.name?.includes(".") ? "." + attachment.name.split(".").pop()!.toLowerCase() : "";
    if (READABLE_EXTENSIONS.has(ext)) {
      try {
        const res = await fetch(attachment.url);
        const text = await res.text();
        return `[${attachment.name}]\n${text}`;
      } catch {
        console.warn("[bot] Could not read attachment:", attachment.name);
      }
    }
  }
  return null;
}

async function ingestChannelMessages(targetGuild: Guild, sinceHours = 24): Promise<RawMessages> {
  const after = new Date(Date.now() - sinceHours * 60 * 60 * 1000);
  const result: RawMessages = {};

  for (const [, channel] of targetGuild.channels.cache) {
    if (!channel.isTextBased() || !("name" in channel)) continue;
    const textCh = channel as TextChannel;
    if (!WATCHED_CHANNELS.has(textCh.name)) continue;

    try {
      const msgs = await textCh.messages.fetch({ limit: 100 });
      const filtered = [...msgs.values()]
        .filter((m) => m.createdAt > after && m.content.trim())
        .reverse()
        .map((m) => `[${m.createdAt.toISOString().slice(0, 16)}] ${m.author.displayName ?? m.author.username}: ${m.content}`);

      if (filtered.length > 0) result[textCh.name] = filtered;

      // Active threads
      const threads = await textCh.threads.fetchActive();
      for (const [, thread] of threads.threads) {
        if (thread.archiveTimestamp && thread.archiveTimestamp < after.getTime()) continue;
        const threadMsgs = await thread.messages.fetch({ limit: 50 });
        const threadFiltered = [...threadMsgs.values()]
          .filter((m) => m.createdAt > after && m.content.trim())
          .reverse()
          .map((m) => `[${m.createdAt.toISOString().slice(0, 16)}] ${m.author.displayName ?? m.author.username}: ${m.content}`);
        if (threadFiltered.length > 0) result[`${textCh.name}/${thread.name}`] = threadFiltered;
      }
    } catch (err) {
      console.error(`[bot] Error reading channel ${textCh.name}:`, err);
    }
  }

  return result;
}

async function createTaskThread(task: TaskItem): Promise<void> {
  if (!chTasks) return;
  try {
    const ownerDisplay = task.owner !== "unassigned" ? `\`${task.owner}\`` : "unassigned";
    const body = `**${task.id} — ${task.title}**\nOwner: ${ownerDisplay}  |  Status: \`${task.status}\`  |  Created: ${task.createdDate}`;
    const msg = await chTasks.send(body);
    const thread = await msg.startThread({ name: `${task.id} ${task.title.slice(0, 40)}`, autoArchiveDuration: 1440 });
    await thread.send(`Task **${task.id}** opened. Drop progress updates here.\nOwner: ${ownerDisplay} — reply \`done\` to close.`);
    await upsertTask({ ...task, threadId: Number(thread.id) });
  } catch (err) {
    console.error(`[bot] Failed to create thread for ${task.id}:`, err);
  }
}

// ── Pipeline runners ──────────────────────────────────────────────────────────

async function runDaily(): Promise<void> {
  if (!guild || !chAiReport) { console.error("[bot] Not ready — skipping daily pipeline"); return; }
  try {
    const rawMessages = await ingestChannelMessages(guild, 24);
    const result = await runDailyPipeline(rawMessages);

    // Post report to #ai-report
    const header = `**Sprint Report — ${new Date().toISOString().split("T")[0]}**\n\n`;
    const full = header + result.reportMd;
    const chunks = chunkMessage(full);
    for (const chunk of chunks) await chAiReport.send(chunk);

    // Post brief update to #changelog
    if (chChangelog && (result.decisions.length > 0 || result.blockers.length > 0)) {
      const parts: string[] = [];
      if (result.decisions.length) parts.push(`**Decisions:**\n${result.decisions.map((d) => `  • ${d}`).join("\n")}`);
      if (result.blockers.length) parts.push(`**Blockers:**\n${result.blockers.map((b) => `  • ${b}`).join("\n")}`);
      await chChangelog.send(`**[${new Date().toISOString().split("T")[0]}]** Sprint update\n\n${parts.join("\n\n")}`);
    }

    console.log(`[bot] Daily pipeline complete — ${result.savedTaskIds.length} tasks saved`);
  } catch (err) {
    console.error("[bot] Daily pipeline failed:", err);
  }
}

async function runWeekly(): Promise<void> {
  if (!guild || !chAiReport) { console.error("[bot] Not ready — skipping weekly pipeline"); return; }
  try {
    const rawMessages = await ingestChannelMessages(guild, 168); // 7 days
    const result = await runDailyPipeline(rawMessages, new Date().toISOString().split("T")[0]);
    const header = `**Weekly Sprint Report — ${new Date().toISOString().split("T")[0]}**\n\n`;
    const chunks = chunkMessage(header + result.reportMd);
    for (const chunk of chunks) await chAiReport.send(chunk);
    console.log("[bot] Weekly pipeline complete");
  } catch (err) {
    console.error("[bot] Weekly pipeline failed:", err);
  }
}

function chunkMessage(text: string, limit = 2000): string[] {
  if (text.length <= limit) return [text];
  const chunks: string[] = [];
  while (text.length > 0) {
    if (text.length <= limit) { chunks.push(text); break; }
    const split = text.lastIndexOf("\n", limit);
    const at = split === -1 ? limit : split;
    chunks.push(text.slice(0, at));
    text = text.slice(at).trimStart();
  }
  return chunks;
}

// ── Event: ready ──────────────────────────────────────────────────────────────

client.once("ready", async () => {
  guild = client.guilds.cache.get(GUILD_ID) ?? null;
  if (!guild) { console.error(`[bot] Guild ${GUILD_ID} not found`); process.exit(1); }

  chTasks = getChannel("tasks");
  chAiReport = getChannel("ai-report");
  chChangelog = getChannel("changelog");
  chSprintDiscuss = getChannel("sprint-discuss");

  console.log(`[bot] Logged in as ${client.user!.tag} | Guild: ${guild.name}`);
  console.log(`[bot]   #tasks         → ${chTasks?.name ?? "NOT FOUND"}`);
  console.log(`[bot]   #ai-report     → ${chAiReport?.name ?? "NOT FOUND"}`);
  console.log(`[bot]   #sprint-discuss→ ${chSprintDiscuss?.name ?? "NOT FOUND"}`);

  const healthy = await checkPipelineHealth();
  console.log(`[bot] Python pipeline: ${healthy ? "✅ online" : "⚠️  offline (start with npm run pipeline)"}`);

  await registerCommands();
  startScheduler(runDaily, runWeekly);
  console.log("[bot] Scheduler started");
});

// ── Event: message ────────────────────────────────────────────────────────────

client.on("messageCreate", async (message: Message) => {
  if (message.author.bot) return;
  if (!chSprintDiscuss) return;

  const isSprintDiscuss =
    message.channelId === chSprintDiscuss.id ||
    (message.channel.isThread() && (message.channel as ThreadChannel).parentId === chSprintDiscuss.id);

  if (!isSprintDiscuss) return;

  // Auto-thread for main-channel messages ≥20 chars
  if (!message.channel.isThread() && message.content.length >= 20) {
    try {
      await message.startThread({
        name: message.content.slice(0, 50).replace(/\n/g, " ").trim(),
        autoArchiveDuration: 1440,
      });
    } catch (err) {
      console.warn("[bot] Auto-thread failed:", err);
    }
  }

  // Run Mastra scrum agent asynchronously
  handleSprintDiscuss(message).catch((err) => console.error("[bot] Sprint discuss handler error:", err));
});

async function handleSprintDiscuss(message: Message): Promise<void> {
  const channelId = message.channelId;
  const channel = message.channel as TextChannel | ThreadChannel;

  const [threadHistory, attachmentText, pendingConfirmation, openTasks] = await Promise.all([
    fetchThreadHistory(channel, message.id),
    extractAttachmentText(message),
    getPendingConfirmation(channelId),
    getOpenTasks(),
  ]);

  const result = await runThreadAgent({
    messageContent: message.content,
    author: message.author.displayName ?? message.author.username,
    threadHistory,
    sprintTasks: openTasks,
    pendingConfirmation,
    attachmentText,
  });

  const { action, message: reply } = result;

  if (action === "silent") return;

  if (action === "propose_task") {
    if (!reply) return;
    await message.reply(reply);
    await setPendingConfirmation(channelId, {
      taskTitle: result.taskTitle ?? "Unnamed task",
      taskOwner: result.taskOwner ?? "unassigned",
    });
  } else if (action === "ask_clarification" && reply) {
    await message.reply(reply);
  } else if (action === "confirm_task" && pendingConfirmation) {
    const taskId = await nextTaskId();
    const task: TaskItem = {
      id: taskId,
      title: pendingConfirmation.taskTitle,
      owner: pendingConfirmation.taskOwner,
      status: "open",
      threadId: null,
      createdDate: new Date().toISOString().split("T")[0],
      reportIncluded: false,
    };
    await upsertTask(task);
    await createTaskThread(task);
    await deletePendingConfirmation(channelId);

    const ownerDisplay = task.owner !== "unassigned" ? `\`${task.owner}\`` : "unassigned";
    await message.reply(
      reply || `Done — added **${taskId}: ${task.title}** (owner: ${ownerDisplay}). Thread created in <#${CHANNEL_IDS["tasks"]}>.`
    );
  } else if (action === "reject_task" && pendingConfirmation) {
    await deletePendingConfirmation(channelId);
    if (reply) await message.reply(reply);
  } else if ((action === "answer_question" || action === "note_decision") && reply) {
    await message.reply(reply);
  }
}

// ── Slash command handler ─────────────────────────────────────────────────────

client.on("interactionCreate", async (interaction) => {
  if (!interaction.isChatInputCommand()) return;

  if (interaction.commandName === "report") {
    await interaction.reply("Generating daily scrum digest… (~30s)");
    try {
      await runDaily();
      await interaction.editReply(`Done. Check <#${CHANNEL_IDS["ai-report"]}>.`);
    } catch (err) {
      await interaction.editReply(`Failed: ${err}`);
    }

  } else if (interaction.commandName === "sprint") {
    await interaction.reply("Generating weekly sprint report…");
    try {
      await runWeekly();
      await interaction.editReply("Weekly report complete.");
    } catch (err) {
      await interaction.editReply(`Failed: ${err}`);
    }

  } else if (interaction.commandName === "tasks") {
    const open = await getOpenTasks();
    if (open.length === 0) {
      await interaction.reply("No open tasks.");
      return;
    }
    const lines = ["**Open Tasks**", "```"];
    for (const t of open) {
      lines.push(`${t.id.padEnd(5)} ${t.status.padEnd(12)} ${t.owner.padEnd(15)} ${t.title}`);
    }
    lines.push("```");
    await interaction.reply(lines.join("\n"));

  } else if (interaction.commandName === "status") {
    const healthy = await checkPipelineHealth();
    await interaction.reply(
      `**Scrum Bot Status**\n` +
      `  Bot: ✅ online\n` +
      `  Python pipeline: ${healthy ? "✅ online" : "⚠️ offline"}\n` +
      `  #tasks: ${chTasks ? "✅" : "❌"}\n` +
      `  #ai-report: ${chAiReport ? "✅" : "❌"}\n` +
      `  #sprint-discuss: ${chSprintDiscuss ? "✅" : "❌"}`
    );

  } else if (interaction.commandName === "task") {
    const title = interaction.options.getString("title", true);
    const owner = interaction.options.getString("owner") ?? "unassigned";
    const taskId = await nextTaskId();
    const task: TaskItem = {
      id: taskId,
      title,
      owner,
      status: "open",
      threadId: null,
      createdDate: new Date().toISOString().split("T")[0],
      reportIncluded: false,
    };
    await upsertTask(task);
    await createTaskThread(task);
    await interaction.reply(`Created **${taskId}: ${title}** → owner: \`${owner}\``);
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  await initDb();
  console.log("[bot] SQLite database initialized");
  await client.login(TOKEN);
}

main().catch((err) => {
  console.error("[bot] Fatal startup error:", err);
  process.exit(1);
});
