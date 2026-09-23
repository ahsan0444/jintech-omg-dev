#!/usr/bin/env node
// auth.mjs — validate a captured Playwright storageState session WITHOUT driving the IdP.
//
//   node auth.mjs validate --repo omg
//
// Exit codes:
//   0  AUTH_OK       session live
//   3  AUTH_MISSING  state file absent (run capture-auth.mjs)
//   2  AUTH_EXPIRED  probe path 3xx-redirects to the expiry signal (/loginsso) => re-capture
//   1  error
//
// NEVER logs cookie values or any storageState contents.

// Static imports: node built-ins + dependency-free locals only. Everything that needs
// node_modules (registry -> js-yaml, @playwright/test) is imported after ensureDeps().
import { existsSync } from 'node:fs';
import { parseArgs } from './lib/args.mjs';
import { ensureDeps } from './lib/preflight.mjs';

async function main() {
  ensureDeps();
  const { chromium } = await import('@playwright/test');
  const { loadRepo } = await import('./lib/registry.mjs');
  const { checkSession, authProbe } = await import('./lib/session.mjs');
  const args = parseArgs();
  const repoName = args.repo || 'omg';
  const repo = loadRepo(repoName);
  const { expirySignal } = authProbe(repo);
  const stateFile = repo.authStateFile;

  if (!existsSync(stateFile)) {
    console.log('AUTH_MISSING: no captured session. Run capture-auth.mjs --repo ' + repoName);
    process.exit(3);
  }

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ storageState: stateFile });
    const s = await checkSession(context.request, repo);
    if (s.expired) {
      console.log('AUTH_EXPIRED: re-capture (session redirected to ' + expirySignal + ')');
      await browser.close();
      process.exit(2);
    }

    console.log('AUTH_OK: session live (probe ' + s.probePath + ' -> status ' + s.status + ')');
    await browser.close();
    process.exit(0);
  } catch (err) {
    if (browser) { try { await browser.close(); } catch { /* ignore */ } }
    console.log('AUTH_ERROR: ' + ((err && err.message) || err));
    process.exit(1);
  }
}

main();
