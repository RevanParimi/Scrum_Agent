# Discord Channel Reference

Quick reference for what each channel does, how the bot uses it, and what to post where.

---

## Channel Map

| Channel | Env Var | Direction | Purpose |
|---|---|---|---|
| `#sprint-discuss` | `CHANNEL_SPRINT_DISCUSS` | Read + Auto-thread | General sprint discussion, design submissions, peer review |
| `#standup` | `CHANNEL_STANDUP` | Read | Daily standup messages (ingested by pipeline) |
| `#tasks` | `CHANNEL_TASKS` | Read + Write | Task board — bot creates threads per task here |
| `#blockers` | `CHANNEL_BLOCKERS` | Read | Blocker reports (ingested by pipeline) |
| `#ai-report` | `CHANNEL_AI_REPORT` | Write | Bot posts daily and weekly AI-generated reports |
| `#changelog` | `CHANNEL_CHANGELOG` | Write | Bot posts summaries after each pipeline run |

---

## Per-Channel Behavior

### `#sprint-discuss`
- **Auto-threading:** Any message ≥ 20 characters gets its own thread automatically (24h archive).
- **Best for:** Design submissions, peer reviews, open-ended discussions, sprint retrospectives.
- **Peer review flow:** Post your design → bot creates a thread → teammates reply in thread → on next pipeline run, the bot reads the thread and acts as PO+SM:
  - **Product Owner:** writes a user story (`As a user, I can...`) + acceptance criteria
  - **Scrum Master:** breaks the story into 3–6 concrete subtasks with owners
  - Subtasks appear in `#tasks` as individual threads alongside standup action items.

### `#standup`
- **Read-only by bot** — ingested during daily pipeline (last 24h window).
- **Best for:** "Yesterday I did X, today I'm doing Y, blockers: none."
- **Not threaded** — keep messages flat and direct.

### `#tasks`
- **Bot writes here** — creates one thread per extracted task (e.g., `T1 · Fix login bug`).
- **Best for:** Tracking task status. Update status by posting in the task thread.
- **Do not manually create tasks** — the bot extracts them from standup/discuss and manages threads.

### `#blockers`
- **Read-only by bot** — ingested alongside standup during pipeline.
- **Best for:** Calling out blockers explicitly so they appear in the AI report.
- **Tip:** One message per blocker, name the owner.

### `#ai-report`
- **Bot writes here only** — do not post manually.
- Daily report posted at 9:00 AM, weekly sprint summary posted Fridays at 6:00 PM.
- Trigger manually with `!report` (daily) or `!sprint` (weekly) if you have `manage_messages`.

### `#changelog`
- **Bot writes here only** — short summary appended after every pipeline run.
- Useful for confirming the bot ran and what it processed.

---

## Use Cases → Channel

| What you want to do | Channel |
|---|---|
| Submit a design for peer review | `#sprint-discuss` |
| Review someone else's design | Reply in their `#sprint-discuss` thread |
| See user stories generated from a design | `#tasks` — subtasks appear after next pipeline run |
| Post your daily standup | `#standup` |
| Report a blocker | `#blockers` |
| See all open tasks | `!tasks` in any channel, or browse `#tasks` threads |
| See the latest AI report | `#ai-report` |
| Trigger a report now | `!report` or `!sprint` (requires manage_messages) |
| Check bot is alive | `!status` in any channel |

---

## Channels Ingested by the Pipeline

The daily pipeline reads from these channels (last 24h by default, last 7 days for sprint report):

- `#standup`
- `#tasks` (threads)
- `#blockers`
- `#sprint-discuss` (threads)

Anything posted outside these channels is **not** seen by the bot.
