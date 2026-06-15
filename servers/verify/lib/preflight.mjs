// preflight.mjs — self-heal harness dependencies.
//
// The plugin cache is re-cloned from git on every `/plugin update`, and node_modules is
// gitignored — so after an update the harness has no deps until `npm ci` runs. This makes
// that automatic: any entry script calls ensureDeps() first; if @playwright/test is absent
// it runs `npm ci` (falling back to `npm install`) in the harness dir, once.
//
// Browser binaries (chromium) are global (~/ms-playwright) and survive updates, so they are
// NOT reinstalled here — only the node_modules tree.

import { existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// lib/preflight.mjs -> lib -> verify (harness root)
const HARNESS_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

/**
 * Ensure the harness node_modules (specifically @playwright/test) is installed.
 * Idempotent and cheap when already present (a single existsSync). Throws if install fails.
 */
export function ensureDeps() {
  const marker = path.join(HARNESS_DIR, 'node_modules', '@playwright', 'test', 'package.json');
  if (existsSync(marker)) return;

  console.error('[verify] harness deps missing (post-update) — running `npm ci` once...');
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const opts = { cwd: HARNESS_DIR, stdio: 'inherit' };
  try {
    execFileSync(npm, ['ci'], opts);
  } catch {
    // lockfile drift or no lockfile — fall back to a plain install
    execFileSync(npm, ['install'], opts);
  }
  if (!existsSync(marker)) {
    throw new Error(`npm install did not provide @playwright/test in ${HARNESS_DIR}`);
  }
}

export { HARNESS_DIR };
