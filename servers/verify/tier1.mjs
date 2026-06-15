#!/usr/bin/env node
// tier1.mjs — Tier-1 verification. NO browser.
//
//   node tier1.mjs --repo omg --feature <f> [--endpoint /path --expect status:200|redirect:/x]
//
// (a) Health probe (HEALTH_URL vs HEALTH_EXPECT) — SSO 302 -> /loginsso counts as up.
// (b) Optional endpoint check: fetch (redirect manual) the endpoint and assert --expect.
//
// Writes the result file, sets exit code (0 = PASS, non-zero = FAIL). No DOM, no payload.

import { loadRepo } from './lib/registry.mjs';
import { probe } from './lib/health.mjs';
import { writeResult } from './lib/result.mjs';
import { parseArgs } from './lib/args.mjs';

async function main() {
  const args = parseArgs();
  const repoName = args.repo || 'omg';
  const feature = args.feature;
  if (!feature) {
    console.log('FAIL: --feature is required');
    process.exit(2);
  }

  const repo = loadRepo(repoName);
  const env = repo.env;

  const healthUrl = env.HEALTH_URL || env.BASE_URL;
  const healthExpect = env.HEALTH_EXPECT || 'status:200';

  // (a) Health probe.
  const h = await probe(healthUrl, healthExpect);
  if (!h.ok) {
    const file = writeResult(repo, feature, {
      status: 'FAIL',
      tier: 1,
      failing_assertion: `health probe ${healthUrl}`,
      screenshot: null,
      observed: h.error ? `${h.observed} (${h.error})` : h.observed,
      expected: healthExpect,
    });
    console.log(`FAIL tier1 ${feature}: health ${h.observed} (expected ${healthExpect})`);
    console.log(`result: ${file}`);
    process.exit(1);
  }

  // (b) Optional endpoint check.
  if (args.endpoint) {
    const expect = args.expect || 'status:200';
    const url = new URL(args.endpoint, env.BASE_URL).toString();
    const e = await probe(url, expect);
    if (!e.ok) {
      const file = writeResult(repo, feature, {
        status: 'FAIL',
        tier: 1,
        failing_assertion: `endpoint ${args.endpoint}`,
        screenshot: null,
        observed: e.error ? `${e.observed} (${e.error})` : e.observed,
        expected: expect,
      });
      console.log(`FAIL tier1 ${feature}: endpoint ${args.endpoint} -> ${e.observed} (expected ${expect})`);
      console.log(`result: ${file}`);
      process.exit(1);
    }
  }

  const file = writeResult(repo, feature, {
    status: 'PASS',
    tier: 1,
    failing_assertion: null,
    screenshot: null,
    observed: h.observed,
    expected: healthExpect,
  });
  console.log(`PASS tier1 ${feature}: health ${h.observed}`);
  console.log(`result: ${file}`);
  process.exit(0);
}

main().catch((err) => {
  console.log('FAIL tier1: ' + ((err && err.message) || err));
  process.exit(1);
});
