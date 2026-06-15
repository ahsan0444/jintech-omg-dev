// Playwright config for Tier-2 specs. Wired entirely from the resolved registry env,
// which run-spec.mjs injects into process.env before invoking `npx playwright test`.
//
// Inputs (env):
//   PG_SPEC_DIR        testDir (default <DATA>/specs)
//   PG_BASE_URL        baseURL  (= BASE_URL)
//   PG_STORAGE_STATE   storageState file (= AUTH_STATE_FILE)
//   PG_OUT_DIR         evidence dir (<DATA>/.verify/out) — screenshots + json report
//
// NOTE: requires a Chromium browser binary (npx playwright install), provided by
// /agent-os-setup, not by this harness.

import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import os from 'node:os';

const specDir = process.env.PG_SPEC_DIR || path.join(os.homedir(), '.agent-os', 'omg', 'specs');
const baseURL = process.env.PG_BASE_URL || 'http://localhost';
const storageState = process.env.PG_STORAGE_STATE || undefined;
const outDir = process.env.PG_OUT_DIR || path.join(os.tmpdir(), 'verify-out');
const reportFile = process.env.PG_REPORT_FILE || path.join(outDir, 'pw-report.json');

export default defineConfig({
  testDir: specDir,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['json', { outputFile: reportFile }]],
  outputDir: outDir,
  use: {
    baseURL,
    storageState,
    screenshot: 'only-on-failure',
    trace: 'off',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
