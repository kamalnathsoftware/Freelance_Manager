import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8765;
const WEB_PORT = 3100;
const py = process.env.E2E_PYTHON ?? "../backend/.venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH || undefined },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Real API on a throwaway SQLite DB, migrated + seeded with the demo workspace.
      command: `bash -c "cd ../backend && rm -f e2e.db && ${py} -m alembic upgrade head && ${py} -m app.seed && ${py} -m uvicorn app.main:app --port ${API_PORT}"`,
      url: `http://localhost:${API_PORT}/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        ENVIRONMENT: "test", DATABASE_URL: "sqlite+aiosqlite:///./e2e.db", SECRET_KEY: "e2e-secret-key-e2e-secret-key-1234",
        CORS_ORIGINS: `["http://localhost:${WEB_PORT}"]`, WEB_BASE_URL: `http://localhost:${WEB_PORT}`, RATE_LIMIT_PER_MINUTE: "100000", AUTH_RATE_LIMIT_PER_MINUTE: "100000",
        UPLOAD_DIR: "/tmp/fm-e2e-uploads",
      },
    },
    {
      command: `bash -c "npx next build && npx next start -p ${WEB_PORT}"`,
      url: `http://localhost:${WEB_PORT}/login`,
      timeout: 300_000,
      reuseExistingServer: !process.env.CI,
      env: { NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
