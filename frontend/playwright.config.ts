import { defineConfig, devices } from "@playwright/test";
import * as dotenv from "dotenv";
import path from "path";

// Load test environment variables
dotenv.config({ path: path.resolve(__dirname, ".env.test") });

const PORT = process.env.FRONTEND_PORT || 3000;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  timeout: 5 * 60 * 1000,
  
  // Setup hook to run before all tests
  // globalSetup: require.resolve("./tests/globalSetup.ts"), // Removed to avoid race condition. setup is now in webServer command.

  use: {
    baseURL: `http://localhost:${PORT}`,
    actionTimeout: 30000,
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: [
    {
      command: "../scripts/start-backend-e2e.sh",
      port: 8000, 
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
      timeout: 300 * 1000,
      env: {
        // Pass env vars from .env.test
        ...process.env,
        // Ensure we use the test values
        OPENSEARCH_INDEX_NAME: process.env.OPENSEARCH_INDEX_NAME || "documents",
        GOOGLE_OAUTH_CLIENT_ID: "",
        GOOGLE_OAUTH_CLIENT_SECRET: "",
      }
    },
    {
      command: "npm run dev",
      port: Number(PORT),
      reuseExistingServer: !process.env.CI,
      env: {
        PORT: String(PORT),
        VITE_PROXY_TARGET: process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000",
      }
    }
  ],
});
