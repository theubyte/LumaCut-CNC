import { defineConfig } from '@playwright/test';

// Screenshots in the installed Chrome/Edge against the dev server and the simulator.
// Start the simulator first (tools/sim_pi.py). Real browser, real pixels: this is the design check.
// Several runs side by side: LC_PORT (dev server) and LUMACUT_DEV_PI (simulator) per run.
const port = process.env.LC_PORT ?? '5183';
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: `http://localhost:${port}`,
    channel: process.env.CI ? 'msedge' : 'chrome',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  },
  webServer: { command: `npx vite --port ${port}`, url: `http://localhost:${port}`, reuseExistingServer: true, timeout: 60_000 },
});
