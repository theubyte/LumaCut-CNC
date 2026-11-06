import { defineConfig } from '@playwright/test';

// Screenshots in the installed Chrome/Edge against the dev server and the simulator.
// Start the simulator first (tools/sim_pi.py). Real browser, real pixels: this is the design check.
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: 'http://localhost:5183',
    channel: process.env.CI ? 'msedge' : 'chrome',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  },
  webServer: { command: 'npm run dev', url: 'http://localhost:5183', reuseExistingServer: true, timeout: 60_000 },
});
