/**
 * src/scheduler.ts — node-cron scheduler
 *
 * Replaces scheduler.py (APScheduler).
 * Fires daily digest at 09:00 and weekly sprint report on Fridays 18:00.
 * Both jobs call back into bot.ts via the provided callbacks.
 */

import cron from "node-cron";

type AsyncJob = () => Promise<void>;

const TIMEZONE = process.env.TIMEZONE ?? "Asia/Kolkata";
const DAILY_HOUR = parseInt(process.env.DAILY_DIGEST_HOUR ?? "9", 10);
const WEEKLY_HOUR = parseInt(process.env.WEEKLY_REPORT_HOUR ?? "18", 10);

export function startScheduler(dailyJob: AsyncJob, weeklyJob: AsyncJob): void {
  // Daily digest — 09:00 local time every day
  const dailyCron = `0 ${DAILY_HOUR} * * *`;
  cron.schedule(
    dailyCron,
    async () => {
      console.log(`[scheduler] Firing daily digest at ${new Date().toISOString()}`);
      try {
        await dailyJob();
      } catch (err) {
        console.error("[scheduler] Daily digest failed:", err);
      }
    },
    { timezone: TIMEZONE }
  );
  console.log(`[scheduler] Daily digest scheduled: ${dailyCron} (${TIMEZONE})`);

  // Weekly sprint report — Friday 18:00 local time
  const weeklyCron = `0 ${WEEKLY_HOUR} * * 5`;
  cron.schedule(
    weeklyCron,
    async () => {
      console.log(`[scheduler] Firing weekly sprint report at ${new Date().toISOString()}`);
      try {
        await weeklyJob();
      } catch (err) {
        console.error("[scheduler] Weekly report failed:", err);
      }
    },
    { timezone: TIMEZONE }
  );
  console.log(`[scheduler] Weekly report scheduled: ${weeklyCron} (${TIMEZONE})`);
}
