# Discord Channel Reference

Quick reference for what each channel does, how the bot uses it, and what to post where.

---

## Channel Map

| Channel | Env Var | Direction | Purpose |
|---|---|---|---|
| `#sprint-discuss` | `CHANNEL_SPRINT_DISCUSS` | Read + Write + Auto-thread | Sprint discussion, task proposals, peer review |
| `#standup` | `CHANNEL_STANDUP` | Read | Daily standup messages (ingested by pipeline) |
| `#tasks` | `CHANNEL_TASKS` | Read + Write | Task board — bot creates threads per confirmed task |
| `#blockers` | `CHANNEL_BLOCKERS` | Read | Blocker reports (ingested by pipeline) |
| `#ai-report` | `CHANNEL_AI_REPORT` | Write | Bot posts daily and weekly AI-generated reports |
| `#changelog` | `CHANNEL_CHANGELOG` | Write | Bot posts summaries after each pipeline run |

---

## Per-Channel Behavior

### `#sprint-discuss`

**Auto-threading:** Any message ≥ 20 characters gets its own thread automatically (24h archive).

**Conversational agent:** The bot participates as a Scrum Master — reading thread history before deciding to respond. It may:
- Propose tracking a message as a task ("Should I track this as a sprint task?")
- Ask one clarifying question when something is ambiguous
- Answer sprint status questions
- Note a team decision

**Pipeline task proposals:** After each daily pipeline run, the bot posts candidate new tasks here for team-lead confirmation:
```
📋 New task proposals from today's standup — please confirm or reject:

• [P1] Implement NSE/BSE API  (owner: unassigned, team: data)
• [P2] Build broker connectors  (owner: unassigned, team: data)

Reply ✅ P1 to confirm, ❌ P1 to reject (use the proposal ID).
Unconfirmed proposals expire after 24 hours.
```

**Confirming/rejecting proposals:** Team leads reply directly in `#sprint-discuss`:
- `✅ P1` → task thread created in `#tasks`
- `❌ P1` → proposal discarded, no task created

---

### `#standup`
- **Read-only by bot** — ingested during daily pipeline (last 24h window).
- **Best for:** "Yesterday I did X, today I'm doing Y, blockers: none."
- Keep messages flat and direct. No threading needed.

---

### `#tasks`
- **Bot writes here** — creates one thread per confirmed task (e.g., `T3 · Implement NSE/BSE API`).
- Tasks are **not auto-created** — they must be confirmed in `#sprint-discuss` first.
- Update task status by posting `done` or `in progress` in the task thread.

---

### `#blockers`
- **Read-only by bot** — ingested alongside standup during pipeline.
- **Best for:** Calling out blockers explicitly so they appear in the AI report.
- One message per blocker, name the owner.

---

### `#ai-report`
- **Bot writes here only** — do not post manually.
- Daily report posted at 9:00 AM (IST), weekly sprint summary posted Fridays at 6:00 PM.
- Trigger manually with `!report` (daily) or `!sprint` (weekly) if you have `manage_messages`.

---

### `#changelog`
- **Bot writes here only** — short summary appended after every pipeline run.
- Useful for confirming the bot ran and what it processed.

---

## Use Cases → Channel

| What you want to do | Channel |
|---|---|
| Discuss something sprint-related | `#sprint-discuss` |
| Submit a design for peer review | `#sprint-discuss` |
| Confirm a pipeline task proposal | `#sprint-discuss` — reply `✅ P1` |
| Reject a pipeline task proposal | `#sprint-discuss` — reply `❌ P1` |
| Post your daily standup | `#standup` |
| Report a blocker | `#blockers` |
| See all open tasks | `!tasks` in any channel, or browse `#tasks` threads |
| See the latest AI report | `#ai-report` |
| Trigger a report now | `!report` or `!sprint` (requires manage_messages) |
| Check bot is alive | `!status` in any channel |
| Deduplicate the task list | `!cleanup-tasks` (requires manage_messages) |

---

## Task Proposal Flow (end-to-end)

```
Daily pipeline (9 AM)
    │
    ├── Extracts candidates from #standup / #blockers
    ├── Deduplicates against existing tasks
    └── Posts proposals to #sprint-discuss as P1, P2, ...
                  │
                  ├── Team lead replies ✅ P1
                  │       └── Bot creates task thread in #tasks (T8, T9, ...)
                  └── Team lead replies ❌ P1
                          └── Proposal discarded, nothing created
```

Tasks can also be proposed in real-time:
```
Team member posts commitment in #sprint-discuss
    │
    └── Bot detects it, asks "Should I track this?"
              │
              ├── Team replies yes → bot creates task in #tasks
              └── Team replies no  → bot drops it
```

---

## Channels Ingested by the Pipeline

The daily pipeline reads from these channels (last 24h by default, last 7 days for sprint report):

- `#standup`
- `#tasks` (threads)
- `#blockers`
- `#sprint-discuss` (threads)

Anything posted outside these channels is **not** seen by the bot.
