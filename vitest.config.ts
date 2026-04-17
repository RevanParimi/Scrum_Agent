import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["tests/ts/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.ts"],
      exclude: ["src/bot.ts"],   // bot needs live Discord — excluded from coverage
    },
    // Use an in-memory SQLite DB for all tests
    env: {
      LIBSQL_URL: "file::memory:?cache=shared",
      GROQ_API_KEY: "test-key",
      PIPELINE_API_URL: "http://localhost:9999",
      DISCORD_TOKEN: "test-token",
      DISCORD_GUILD_ID: "123456789",
    },
  },
});
