#!/usr/bin/env node
// capture-auth.mjs — MANUAL developer step. Opens a HEADED browser, you complete SSO,
// then it saves a Playwright storageState to AUTH_STATE_FILE.
//
//   node capture-auth.mjs --repo omg
//
// Polls auth_probe_path until it no longer redirects to /loginsso (timeout 300s), then
// saves state ONLY to ~/.agent-os/omg/.auth/state.json (gitignored, private).
//
// Prints ONLY the path. NEVER prints cookies / storageState contents.
//
// NOTE: requires a Chromium browser binary (npx playwright install) which is handled by
// /agent-os-setup, not by this harness.

// Static imports: node built-ins + dependency-free locals only. Everything that needs
// node_modules (registry -> js-yaml, @playwright/test) is imported after ensureDeps().
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { parseArgs } from './lib/args.mjs';
import { ensureDeps } from './lib/preflight.mjs';

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function main() {
  ensureDeps();
  const { chromium } = await import('@playwright/test');
  const { loadRepo } = await import('./lib/registry.mjs');
  const args = parseArgs();
  const repoName = args.repo || 'omg';
  const repo = loadRepo(repoName);
  const env = repo.env;
  const auth = repo.auth || {};

  const baseUrl = env.BASE_URL;
  const probePath = auth.auth_probe_path || '/jobs';
  const expirySignal =
    (auth.storage_state && auth.storage_state.expiry_signal_redirect) || '/loginsso';
  const stateFile = repo.authStateFile;
  const timeoutMs = 300000; // 300s

  // Ensure the .auth directory exists.
  mkdirSync(path.dirname(stateFile), { recursive: true });

  const probeUrl = new URL(probePath, baseUrl).toString();

  console.log('[capture-auth] launching headed browser at ' + baseUrl);
  console.log('[capture-auth] complete the SSO login in the window; waiting up to 300s...');

  const browser = await chromium.launch({ headless: false });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});

    const deadline = Date.now() + timeoutMs;
    let authed = false;
    while (Date.now() < deadline) {
      // Probe with manual redirects; authed when probe path no longer 302s to /loginsso.
      const res = await context.request.get(probeUrl, { maxRedirects: 0 }).catch(() => null);
      if (res) {
        const status = res.status();
        const location = res.headers()['location'] || '';
        const is3xx = status >= 300 && status < 400;
        if (!(is3xx && location.includes(expirySignal))) {
          authed = true;
          break;
        }
      }
      await sleep(3000);
    }

    if (!authed) {
      console.log('[capture-auth] TIMEOUT: SSO not completed within 300s. Nothing saved.');
      await browser.close();
      process.exit(1);
    }

    await context.storageState({ path: stateFile });
    await browser.close();
    // Print ONLY the path — never the contents.
    console.log('[capture-auth] saved storageState to: ' + stateFile);
    process.exit(0);
  } catch (err) {
    try { await browser.close(); } catch { /* ignore */ }
    console.log('[capture-auth] ERROR: ' + ((err && err.message) || err));
    process.exit(1);
  }
}

main();
