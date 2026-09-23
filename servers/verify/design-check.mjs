#!/usr/bin/env node
// design-check.mjs — Tier-2 design conformance. Reads computed styles for the elements in a
// design spec and compares them to the expected values. No pixel diffing.
//
//   node design-check.mjs --repo omg --feature <f> [--spec <path>]
//
// Spec default: <DATA>/.verify/design/<feature>.design.json
//   { url, viewport:{width,height}, elements:[{selector, expect:{prop:val}, states:{hover:{prop:val}}}],
//     figma_screenshot?: <png path> }
// Tolerance: px ±1 per token; colors canonicalised by the browser; font-family = first family,
// quotes stripped, case-insensitive; everything else trimmed case-insensitive equality.
// Evidence: <DATA>/.verify/out/<feature>.design/{full.png, el-<n>.png, figma.png}
// Result:   <DATA>/.verify/out/<feature>.design.result.json
// Exit 0 all pass, 1 any fail, 2 auth expired/missing, 4 bad spec/usage.

import { existsSync, readFileSync, mkdirSync, copyFileSync } from 'node:fs';
import path from 'node:path';
import { parseArgs } from './lib/args.mjs';
import { ensureDeps } from './lib/preflight.mjs';

const PX_TOL = 1;
const HOVER_SETTLE_MS = 400;

const firstFamily = (v) => String(v).split(',')[0].replace(/["']/g, '').trim().toLowerCase();
const pxTokens = (v) => {
  const t = String(v).trim().split(/\s+/);
  return t.every((x) => /^-?\d*\.?\d+px$/.test(x)) ? t.map((x) => parseFloat(x)) : null;
};

function compare(prop, expected, actual) {
  if (actual == null) return false;
  if (prop === 'font-family') return firstFamily(expected) === firstFamily(actual);
  const e = pxTokens(expected);
  const a = pxTokens(actual);
  if (e && a) return e.length === a.length && e.every((n, i) => Math.abs(n - a[i]) <= PX_TOL);
  return String(expected).trim().toLowerCase() === String(actual).trim().toLowerCase();
}

/** Read computed values for props; canonicalises expected colours in-page (hex/named/hsl -> rgb[a]). */
async function readStyles(locator, expect) {
  return locator.evaluate((el, exp) => {
    const cs = getComputedStyle(el);
    const canon = (v) => {
      const d = document.createElement('div');
      d.style.color = v;
      if (!d.style.color) return v;
      document.body.appendChild(d);
      const c = getComputedStyle(d).color;
      d.remove();
      return c;
    };
    const out = {};
    for (const [prop, want] of Object.entries(exp)) {
      out[prop] = {
        expected: /color$/i.test(prop) || prop === 'fill' || prop === 'stroke' ? canon(want) : want,
        actual: cs.getPropertyValue(prop).trim(),
      };
    }
    return out;
  }, expect);
}

function judge(styles) {
  const res = {};
  for (const [prop, { expected, actual }] of Object.entries(styles)) {
    res[prop] = { expected, actual, pass: compare(prop, expected, actual) };
  }
  return res;
}

function missing(expect) {
  const res = {};
  for (const [prop, expected] of Object.entries(expect || {})) res[prop] = { expected, actual: null, pass: false };
  return res;
}

async function main() {
  ensureDeps();
  const { chromium } = await import('@playwright/test');
  const { loadRepo, outDir } = await import('./lib/registry.mjs');
  const { writeResult } = await import('./lib/result.mjs');
  const { checkSession, authProbe } = await import('./lib/session.mjs');

  const args = parseArgs();
  const repoName = args.repo || 'omg';
  const feature = args.feature;
  if (!feature) { console.log('FAIL: --feature is required'); process.exit(4); }

  const repo = loadRepo(repoName);
  const specPath = args.spec || path.join(repo.dataDir, '.verify', 'design', `${feature}.design.json`);
  if (!existsSync(specPath)) { console.log(`FAIL: design spec not found: ${specPath}`); process.exit(4); }
  let spec;
  try { spec = JSON.parse(readFileSync(specPath, 'utf8')); } catch (e) {
    console.log(`FAIL: design spec invalid JSON: ${e.message}`); process.exit(4);
  }
  if (!spec.url || !Array.isArray(spec.elements)) { console.log('FAIL: design spec needs url + elements[]'); process.exit(4); }
  if (!existsSync(repo.authStateFile)) { console.log('AUTH_MISSING: run capture-auth.mjs --repo ' + repoName); process.exit(2); }

  const evDir = path.join(outDir(repo), `${feature}.design`);
  mkdirSync(evDir, { recursive: true });
  const { expirySignal } = authProbe(repo);

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      storageState: repo.authStateFile,
      baseURL: repo.env.BASE_URL,
      viewport: spec.viewport || { width: 1440, height: 900 },
    });
    if ((await checkSession(context.request, repo)).expired) {
      console.log('AUTH_EXPIRED: re-capture (session redirected to ' + expirySignal + ')');
      return 2;
    }
    const page = await context.newPage();
    await page.goto(spec.url, { waitUntil: 'networkidle' });
    // Never screenshot the IdP.
    if (page.url().includes(expirySignal)) {
      console.log('AUTH_EXPIRED: page redirected to ' + expirySignal);
      return 2;
    }

    const elements = [];
    for (const [i, el] of spec.elements.entries()) {
      const loc = page.locator(el.selector).first();
      const entry = { selector: el.selector, screenshot: null, properties: {}, states: {} };
      try {
        await loc.waitFor({ state: 'visible', timeout: 10000 });
      } catch {
        entry.properties = missing(el.expect);
        for (const [st, exp] of Object.entries(el.states || {})) entry.states[st] = missing(exp);
        entry.error = 'selector not visible';
        elements.push(entry);
        continue;
      }
      entry.properties = judge(await readStyles(loc, el.expect || {}));
      entry.screenshot = path.join(evDir, `el-${i}.png`);
      await loc.screenshot({ path: entry.screenshot });
      if (el.states && el.states.hover) {
        await loc.hover();
        await page.waitForTimeout(HOVER_SETTLE_MS);
        entry.states.hover = judge(await readStyles(loc, el.states.hover));
        await page.mouse.move(0, 0);
      }
      elements.push(entry);
    }

    const full = path.join(evDir, 'full.png');
    await page.screenshot({ path: full, fullPage: true });
    let figma = null;
    if (spec.figma_screenshot && existsSync(spec.figma_screenshot)) {
      figma = path.join(evDir, 'figma.png');
      copyFileSync(spec.figma_screenshot, figma);
    }

    const fails = [];
    for (const e of elements) {
      for (const [p, r] of Object.entries(e.properties)) if (!r.pass) fails.push({ sel: e.selector, p, r });
      for (const [st, props] of Object.entries(e.states)) {
        for (const [p, r] of Object.entries(props)) if (!r.pass) fails.push({ sel: `${e.selector}:${st}`, p, r });
      }
    }
    const f = fails[0];
    const file = writeResult(repo, feature, {
      status: fails.length ? 'FAIL' : 'PASS',
      tier: 2,
      failing_assertion: f ? `${f.sel} ${f.p}` : null,
      screenshot: full,
      observed: f ? String(f.r.actual) : 'all design properties matched',
      expected: f ? String(f.r.expected) : 'design spec',
    }, { kind: 'design', extra: { check: 'design', spec: specPath, figma, fail_count: fails.length, elements } });
    console.log(`${fails.length ? 'FAIL' : 'PASS'} design ${feature}: ${fails.length} mismatch(es)`);
    console.log(`result: ${file}`);
    return fails.length ? 1 : 0;
  } finally {
    await browser.close().catch(() => {});
  }
}

main().then((code) => process.exit(code)).catch((err) => {
  console.log('FAIL design: ' + ((err && err.message) || err));
  process.exit(1);
});
