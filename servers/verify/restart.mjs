#!/usr/bin/env node
// restart.mjs — restart the omg dev container and wait until READY.
//
//   node restart.mjs --repo omg              default: restart + poll readiness
//   node restart.mjs --repo omg --check-only SKIP restart; only probe readiness
//                                            (validate against an already-running app
//                                             WITHOUT disrupting it)
//
// READY only when BOTH:
//   - container is Up   (`podman ps --filter name=^omg$ --format {{.Status}}` contains "Up")
//   - health.probe matches HEALTH_EXPECT (SSO 302 -> /loginsso counts as up)
//
// Exit 0 = READY, 1 = NOT_READY. Prints READY/NOT_READY + elapsed seconds.

import { spawn } from 'node:child_process';
import { loadRepo } from './lib/registry.mjs';
import { probe } from './lib/health.mjs';
import { parseArgs, splitCmd } from './lib/args.mjs';

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** Run a command (array args, no shell). Resolves { code, stdout, stderr }. */
function run(cmdArr, { timeoutMs = 60000 } = {}) {
  return new Promise((resolve) => {
    if (!cmdArr.length) {
      resolve({ code: 127, stdout: '', stderr: 'empty command' });
      return;
    }
    const [bin, ...rest] = cmdArr;
    let stdout = '';
    let stderr = '';
    let child;
    try {
      child = spawn(bin, rest, { shell: false });
    } catch (err) {
      resolve({ code: 127, stdout: '', stderr: (err && err.message) || String(err) });
      return;
    }
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* ignore */ }
    }, timeoutMs);
    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ code: 127, stdout, stderr: (err && err.message) || String(err) });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code: code == null ? 1 : code, stdout, stderr });
    });
  });
}

/** Is the container Up? Uses an exact-name filter regex. */
async function containerUp(containerName) {
  const res = await run([
    'podman', 'ps',
    '--filter', `name=^${containerName}$`,
    '--format', '{{.Status}}',
  ]);
  if (res.code !== 0) return { up: false, status: res.stderr.trim() || `podman ps exit ${res.code}` };
  const status = res.stdout.trim();
  return { up: /\bUp\b/i.test(status), status: status || '(not found)' };
}

async function main() {
  const args = parseArgs();
  const repoName = args.repo || 'omg';
  const checkOnly = !!args['check-only'];
  const repo = loadRepo(repoName);
  const env = repo.env;

  const healthUrl = env.HEALTH_URL || env.BASE_URL;
  const healthExpect = env.HEALTH_EXPECT || 'status:200';
  const appContainer = env.APP_CONTAINER || 'omg';
  const waitTimeout = parseInt(env.WAIT_TIMEOUT || '180', 10);
  const pollInterval = parseInt(env.POLL_INTERVAL || '3', 10);

  const start = Date.now();
  const elapsed = () => Math.round((Date.now() - start) / 1000);

  if (!checkOnly) {
    // Attempt primary restart, then fallback.
    const primary = splitCmd(env.RESTART_CMD);
    console.log(`[restart] running: ${primary.join(' ')}`);
    let res = await run(primary);
    if (res.code !== 0) {
      console.log(`[restart] primary failed (exit ${res.code}); trying fallback`);
      const fallback = splitCmd(env.RESTART_CMD_FALLBACK);
      if (fallback.length) {
        console.log(`[restart] running: ${fallback.join(' ')}`);
        res = await run(fallback);
      }
      if (res.code !== 0) {
        console.log(`NOT_READY (restart command failed) elapsed=${elapsed()}s`);
        process.exit(1);
      }
    }
  } else {
    console.log('[restart] --check-only: skipping restart, probing running app only');
  }

  // Poll for readiness: container Up AND health matches.
  const deadline = Date.now() + waitTimeout * 1000;
  let lastReason = 'no probe yet';
  // Run at least one iteration even if timeout is 0.
  do {
    const c = await containerUp(appContainer);
    if (!c.up) {
      lastReason = `container not Up (status: ${c.status})`;
    } else {
      const h = await probe(healthUrl, healthExpect);
      if (h.ok) {
        console.log(`READY (container Up; health ${h.observed}) elapsed=${elapsed()}s`);
        process.exit(0);
      }
      lastReason = `health not matched (${h.error ? h.error : h.observed}; expected ${healthExpect})`;
    }
    if (Date.now() + pollInterval * 1000 > deadline) break;
    await sleep(pollInterval * 1000);
  } while (Date.now() < deadline);

  console.log(`NOT_READY (${lastReason}) elapsed=${elapsed()}s`);
  process.exit(1);
}

main().catch((err) => {
  console.log(`NOT_READY (error: ${(err && err.message) || err})`);
  process.exit(1);
});
