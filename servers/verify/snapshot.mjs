#!/usr/bin/env node
// snapshot.mjs — Tier-1 characterization snapshots. NO browser (Playwright request context only).
//
//   node snapshot.mjs record  --repo omg --routes <file|/a,/b> --label base [--feature <f>]
//   node snapshot.mjs compare --repo omg --label base [--feature <f>]
//
// GET only: a route written as "POST /x" (any non-GET method) is refused. Routes file = one per
// line, optional "GET " prefix, # comments. Bodies are normalised (NORMALIZERS) then stored at
// <DATA>/.verify/snapshots/<label>/. compare re-fetches into <label>.current/ and diffs.
// The script only fetches — stashing / branch switching is the orchestrator's job.
// Result: <DATA>/.verify/out/<feature>.snapshot.result.json
// Exit 0 recorded / no diff, 1 diff or fetch error, 2 auth expired/missing, 4 usage/refused.

import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { parseArgs } from './lib/args.mjs';
import { ensureDeps } from './lib/preflight.mjs';

// [name, pattern, replacement] — applied in order.
const NORMALIZERS = [
  ['csrf', /((?:csrf|xsrf|authenticity)[\w-]*["']?\s*(?:[:=]|\s+(?:value|content)=)\s*["']?)[^"'\s&<>]+/gi, '$1<CSRF>'],
  ['session', /((?:session|sess|sid)[\w.-]*["']?\s*[:=]\s*["']?)[A-Za-z0-9%._-]{16,}/gi, '$1<SID>'],
  ['iso-ts', /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?/g, '<TS>'],
  ['epoch-ms', /\b1[5-9]\d{11}\b/g, '<EPOCH_MS>'],
  ['cache-bust', /([?&](?:v|ver|_|t|ts)=)[\w.-]+/g, '$1<V>'],
];

function normalize(body) {
  return NORMALIZERS.reduce((s, [, re, rep]) => s.replace(re, rep), body);
}

const slug = (route) => route.replace(/^\//, '').replace(/[^\w.-]+/g, '_').slice(0, 120) || 'root';

function parseRoutes(arg) {
  const raw = existsSync(arg) ? readFileSync(arg, 'utf8').split(/\r?\n/) : String(arg).split(',');
  const routes = [];
  for (const line of raw.map((l) => l.trim()).filter((l) => l && !l.startsWith('#'))) {
    const m = line.match(/^([A-Za-z]+)\s+(\S+)$/);
    if (m && m[1].toUpperCase() !== 'GET') throw new Error(`refused non-GET route: ${line}`);
    routes.push(m ? m[2] : line);
  }
  return routes;
}

async function fetchRoute(req, repo, route, expirySignal, isExpiredResponse) {
  const url = new URL(route, repo.env.BASE_URL);
  if (url.origin !== new URL(repo.env.BASE_URL).origin) throw new Error(`refused off-host route: ${route}`);
  const res = await req.get(url.toString(), { maxRedirects: 0 });
  if (isExpiredResponse(res, expirySignal)) return { expired: true };
  const loc = res.headers()['location'];
  const head = `# ${res.status()}${loc ? ' -> ' + normalize(loc) : ''}\n`;
  const body = normalize(await res.text());
  return { status: res.status(), text: head + body + (body.endsWith('\n') ? '' : '\n') };
}

/** Unified diff via git --no-index (cross-platform, no deps). */
function diff(a, b) {
  const r = spawnSync('git', ['diff', '--no-index', '--no-color', '-U3', a, b], { encoding: 'utf8', shell: false });
  if (r.error) throw new Error('git not available for diff: ' + r.error.message);
  const lines = (r.stdout || '').split('\n').filter((l) => l && !/^(diff --git|index |--- |\+\+\+ )/.test(l));
  return {
    changed: r.status === 1,
    added: lines.filter((l) => l.startsWith('+')).length,
    removed: lines.filter((l) => l.startsWith('-')).length,
    head: lines.slice(0, 40),
  };
}

async function main() {
  ensureDeps();
  const { request } = await import('@playwright/test');
  const { loadRepo } = await import('./lib/registry.mjs');
  const { writeResult } = await import('./lib/result.mjs');
  const { checkSession, authProbe, isExpiredResponse } = await import('./lib/session.mjs');

  const args = parseArgs();
  const mode = args._[0];
  const repo = loadRepo(args.repo || 'omg');
  const label = args.label;
  const feature = args.feature || 'snapshot';
  if (!['record', 'compare'].includes(mode) || !label || !/^[\w.-]+$/.test(label)) {
    console.log('FAIL: usage: snapshot.mjs record|compare --label <name> [--routes <file|list>]');
    return 4;
  }
  if (!existsSync(repo.authStateFile)) { console.log('AUTH_MISSING: run capture-auth.mjs'); return 2; }

  const root = path.join(repo.dataDir, '.verify', 'snapshots');
  const baseDir = path.join(root, label);
  const manifestFile = path.join(baseDir, 'manifest.json');
  let routes;
  try {
    if (mode === 'record') {
      if (!args.routes) throw new Error('--routes is required for record');
      routes = parseRoutes(args.routes);
    } else {
      if (!existsSync(manifestFile)) throw new Error(`no snapshot "${label}" at ${baseDir}`);
      routes = JSON.parse(readFileSync(manifestFile, 'utf8')).routes.map((r) => r.route);
    }
  } catch (e) { console.log('FAIL: ' + e.message); return 4; }

  const outDir = mode === 'record' ? baseDir : path.join(root, `${label}.current`);
  const { expirySignal } = authProbe(repo);
  const req = await request.newContext({ storageState: repo.authStateFile });
  try {
    if ((await checkSession(req, repo)).expired) { console.log('AUTH_EXPIRED: re-capture'); return 2; }
    rmSync(outDir, { recursive: true, force: true });
    mkdirSync(outDir, { recursive: true });
    const entries = [];
    for (const route of routes) {
      const file = `${slug(route)}.txt`;
      const r = await fetchRoute(req, repo, route, expirySignal, isExpiredResponse);
      if (r.expired) { console.log(`AUTH_EXPIRED: ${route} redirected to ${expirySignal}`); return 2; }
      writeFileSync(path.join(outDir, file), r.text, 'utf8');
      entries.push({ route, file, status: r.status });
    }

    if (mode === 'record') {
      writeFileSync(manifestFile, JSON.stringify({ label, recorded_at: new Date().toISOString(), routes: entries }, null, 2) + '\n');
      const file = writeResult(repo, feature, {
        status: 'PASS', tier: 1, observed: `recorded ${entries.length} route(s)`, expected: `snapshot ${label}`,
      }, { kind: 'snapshot', extra: { check: 'snapshot', mode, label, dir: baseDir, routes: entries } });
      console.log(`PASS snapshot record ${label}: ${entries.length} route(s)`);
      console.log(`result: ${file}`);
      return 0;
    }

    const results = entries.map((e) => ({ route: e.route, status: e.status, ...diff(path.join(baseDir, e.file), path.join(outDir, e.file)) }));
    const changed = results.filter((r) => r.changed);
    const file = writeResult(repo, feature, {
      status: changed.length ? 'FAIL' : 'PASS',
      tier: 1,
      failing_assertion: changed.length ? `behaviour changed: ${changed.map((r) => r.route).join(', ')}` : null,
      observed: `${changed.length}/${results.length} route(s) differ`,
      expected: `matches snapshot ${label}`,
    }, { kind: 'snapshot', extra: { check: 'snapshot', mode, label, dir: outDir, routes: results } });
    console.log(`${changed.length ? 'FAIL' : 'PASS'} snapshot compare ${label}: ${changed.length}/${results.length} differ`);
    console.log(`result: ${file}`);
    return changed.length ? 1 : 0;
  } finally {
    await req.dispose().catch(() => {});
  }
}

main().then((code) => process.exit(code)).catch((err) => {
  console.log('FAIL snapshot: ' + ((err && err.message) || err));
  process.exit(1);
});
