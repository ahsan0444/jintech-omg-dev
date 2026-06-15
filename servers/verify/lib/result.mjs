// Result-file writer. The harness reports to the caller ONLY via exit code + this file.
// NO rich stdout payload, NO DOM dumps.
//
// Schema:
//   { status, tier, feature, failing_assertion, screenshot, observed, expected }
// Path: <DATA>/.verify/out/<feature>.result.json

import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { outDir } from './registry.mjs';

export function writeResult(repo, feature, result) {
  const dir = outDir(repo);
  mkdirSync(dir, { recursive: true });
  const payload = {
    status: result.status,                       // "PASS" | "FAIL"
    tier: result.tier,                           // 1 | 2
    feature,
    failing_assertion: result.failing_assertion ?? null,
    screenshot: result.screenshot ?? null,
    observed: result.observed ?? '',
    expected: result.expected ?? '',
  };
  const file = path.join(dir, `${feature}.result.json`);
  writeFileSync(file, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  return file;
}
