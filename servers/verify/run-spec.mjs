#!/usr/bin/env node
// run-spec.mjs — Tier-2 verification. Runs ONE Playwright spec as a child process,
// parses the JSON reporter, reduces to the result-file shape. NEVER dumps the page.
//
//   node run-spec.mjs --repo omg --feature <f> --spec <path>
//
// Wires storageState + baseURL via env consumed by playwright.config.mjs.
// Result file records the FIRST failing assertion + its screenshot (if any).
// Exit 0 = PASS, non-zero = FAIL.
//
// NOTE: requires a Chromium browser binary (npx playwright install), provided by
// /agent-os-setup, not by this harness. If absent, the spec run fails and is reported
// as a FAIL with the missing-browser message as `observed`.

// Static imports MUST be node built-ins + dependency-free local modules only (args, preflight).
// Anything that pulls in node_modules (registry -> js-yaml, result -> registry) is imported
// DYNAMICALLY after ensureDeps(), so the harness can self-install on a fresh post-update cache.
import { spawn } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync, rmSync, copyFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from './lib/args.mjs';
import { ensureDeps } from './lib/preflight.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function runPlaywright(specPath, env) {
  return new Promise((resolve) => {
    const npxBin = process.platform === 'win32' ? 'npx.cmd' : 'npx';
    const configPath = path.join(__dirname, 'playwright.config.mjs');
    const child = spawn(
      npxBin,
      ['playwright', 'test', specPath, '--config', configPath],
      { shell: false, cwd: __dirname, env },
    );
    let stderr = '';
    child.stdout.on('data', () => { /* discard: no page dump in main output */ });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('error', (err) => resolve({ code: 127, stderr: (err && err.message) || String(err) }));
    child.on('close', (code) => resolve({ code: code == null ? 1 : code, stderr }));
  });
}

/** Walk the Playwright JSON report; return first failing assertion + screenshot. */
function firstFailure(report) {
  const suites = report.suites || [];
  const stack = [...suites];
  while (stack.length) {
    const suite = stack.shift();
    for (const spec of suite.specs || []) {
      for (const test of spec.tests || []) {
        for (const res of test.results || []) {
          if (res.status !== 'passed' && res.status !== 'skipped') {
            const errMsg =
              (res.error && (res.error.message || res.error.value)) ||
              (res.errors && res.errors[0] && res.errors[0].message) ||
              `${spec.title}: ${res.status}`;
            let shot = null;
            for (const att of res.attachments || []) {
              if (att.name === 'screenshot' && att.path) { shot = att.path; break; }
            }
            // First line of the error keeps the result file tiny.
            const text = String(errMsg).split('\n')[0].trim();
            return { title: spec.title, message: text, screenshot: shot };
          }
        }
      }
    }
    if (suite.suites) stack.push(...suite.suites);
  }
  return null;
}

async function main() {
  ensureDeps();
  const { loadRepo, outDir } = await import('./lib/registry.mjs');
  const { writeResult } = await import('./lib/result.mjs');
  const args = parseArgs();
  const repoName = args.repo || 'omg';
  const feature = args.feature;
  const spec = args.spec;
  if (!feature || !spec) {
    console.log('FAIL: --feature and --spec are required');
    process.exit(2);
  }
  if (!existsSync(spec)) {
    console.log(`FAIL: spec not found: ${spec}`);
    process.exit(2);
  }

  const repo = loadRepo(repoName);
  const env = repo.env;
  const evidenceDir = outDir(repo);
  mkdirSync(evidenceDir, { recursive: true });
  const reportFile = path.join(evidenceDir, `${feature}.pw-report.json`);
  if (existsSync(reportFile)) { try { rmSync(reportFile); } catch { /* ignore */ } }

  // Run the spec from INSIDE the harness tree so its `import '@playwright/test'` resolves
  // against the harness node_modules — no version-pinned symlink in the data home needed.
  // The spec is fully env-driven (PG_OUT_DIR etc.), so its location does not matter.
  const tmpDir = path.join(__dirname, '.verify-tmp');
  mkdirSync(tmpDir, { recursive: true });
  const tmpSpec = path.join(tmpDir, path.basename(spec));
  copyFileSync(spec, tmpSpec);

  const childEnv = {
    ...process.env,
    PG_SPEC_DIR: tmpDir,
    PG_BASE_URL: env.BASE_URL,
    PG_STORAGE_STATE: repo.authStateFile,
    PG_OUT_DIR: evidenceDir,
    PG_REPORT_FILE: reportFile,
  };

  const { code, stderr } = await runPlaywright(tmpSpec, childEnv);
  try { rmSync(tmpSpec, { force: true }); } catch { /* ignore */ }

  // Parse the JSON report if present.
  let report = null;
  if (existsSync(reportFile)) {
    try { report = JSON.parse(readFileSync(reportFile, 'utf8')); } catch { report = null; }
  }

  if (code === 0 && report) {
    const file = writeResult(repo, feature, {
      status: 'PASS',
      tier: 2,
      failing_assertion: null,
      screenshot: null,
      observed: 'all assertions passed',
      expected: 'spec passes',
    });
    console.log(`PASS tier2 ${feature}`);
    console.log(`result: ${file}`);
    process.exit(0);
  }

  // Failure path — extract first failing assertion.
  const fail = report ? firstFailure(report) : null;
  const observed = fail
    ? fail.message
    : (stderr.split('\n').find((l) => l.trim()) || `playwright exited ${code}`).trim();

  const file = writeResult(repo, feature, {
    status: 'FAIL',
    tier: 2,
    failing_assertion: fail ? `${fail.title}: ${fail.message}` : 'spec run failed',
    screenshot: fail ? fail.screenshot : null,
    observed,
    expected: 'spec passes',
  });
  console.log(`FAIL tier2 ${feature}: ${observed}`);
  console.log(`result: ${file}`);
  process.exit(1);
}

main().catch((err) => {
  console.log('FAIL tier2: ' + ((err && err.message) || err));
  process.exit(1);
});
