import { randomUUID } from "node:crypto";
import { defineConfig } from "@playwright/test";

// A fresh random run key for each test run (server and test read it from the environment).
process.env.E2E_RUN_KEY ??= randomUUID();

// One e2e test + axe checks against the built app (npm run build first), served by FastAPI in fake mode.
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  use: { baseURL: "http://127.0.0.1:8767", channel: "chrome", headless: true, viewport: { width: 1300, height: 900 } },
  webServer: { command: "./e2e/server.sh", url: "http://127.0.0.1:8767/ping", reuseExistingServer: false, timeout: 60_000 },
});
