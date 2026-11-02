import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
// The static site (make static-site) is tested when PREPAY_STATIC_SITE names its root directory.
const STATIC_ROOT = process.env.PREPAY_STATIC_SITE;
const STATIC_PORT = 8766;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /screenshots|static/ },
    { name: "screenshots", use: { ...devices["Desktop Chrome"] }, testMatch: /screenshots/ },
    ...(STATIC_ROOT
      ? [
          {
            name: "static",
            use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${STATIC_PORT}/PrePay/` },
            testMatch: /static/,
          },
        ]
      : []),
  ],
  webServer: [
    {
      command: `uv run --frozen prepay serve --bundle build/demo --web-dist web/dist --port ${PORT}`,
      cwd: "..",
      url: `http://127.0.0.1:${PORT}/api/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { PREPAY_RATE_LIMIT_PER_MINUTE: "1000" },
    },
    ...(STATIC_ROOT
      ? [
          {
            command: `python -m http.server ${STATIC_PORT} --bind 127.0.0.1 --directory "${STATIC_ROOT}"`,
            url: `http://127.0.0.1:${STATIC_PORT}/PrePay/index.html`,
            timeout: 30_000,
            reuseExistingServer: !process.env.CI,
          },
        ]
      : []),
  ],
});
