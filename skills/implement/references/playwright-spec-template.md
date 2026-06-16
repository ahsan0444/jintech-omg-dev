# Playwright Tier-2 Spec — Requirements and Template

Loaded by `implement/SKILL.md` Step 2c before spawning the spec-generation subagent.
Insert full contents of this file where `<SPEC_TEMPLATE>` appears in the Step 2c prompt.

---

## Requirement 1 — File location

Write to `~/.agent-os/omg/specs/<feature-slug>.spec.mjs`

---

## Requirement 2 — Spec pattern (do NOT deviate)

```js
// Tier-2 Playwright spec — <feature-slug> (<TICKET_ID>)
// <one-line summary of what is asserted>
// Navigation: <navigation path, e.g. landing → campaigns → /campaigns/<id>/jobs>

import { test, expect } from '@playwright/test';
import path from 'node:path';

const outDir = process.env.PG_OUT_DIR || '/tmp/verify-out';

// Extended timeout — Bryntum SPA; networkidle never resolves within 30s.
test.setTimeout(90000);

test('<assertion-name>: <human description>', async ({ page }) => {

  // ── Step 1: Navigate to entry point ──
  await page.goto('<entry-url>', { waitUntil: 'domcontentloaded', timeout: 60000 });
  const url = page.url();
  if (url.includes('/loginsso') || url.includes('login')) {
    await page.screenshot({ path: path.join(outDir, '<feature-slug>-auth-fail.png') });
    throw new Error(`AUTH_EXPIRED on <entry-url>: ${url}`);
  }

  // ── Step 2: Discover entity (if route is entity-scoped, e.g. /campaigns/:id) ──
  // Navigate the UI dynamically — no hardcoded IDs.
  // <discovery logic here — find first matching entity link>

  // ── Step 3: Assert the change ──
  // Use role-based / data-attribute locators. Avoid XPath and nth-child.
  // Always use web-first assertions (toBeVisible, toContainText etc.) — they auto-wait.
  const element = page.locator('<selector>');
  const screenshotPath = path.join(outDir, '<feature-slug>-evidence.png');
  try {
    await expect(element).toBeVisible({ timeout: 15000 });
  } catch (err) {
    await page.screenshot({ path: screenshotPath });
    throw err;
  }
  await page.screenshot({ path: screenshotPath });
});
```

---

## Requirement 3 — Selector strategy (priority order)

a. `#id` for elements with stable ids set in `.tt`
b. `page.getByRole('button', { name: '...' })` / `getByLabel` / `getByText` for user-facing text
c. `[data-*]` attributes Bryntum emits (`[data-event-id]`, `[data-index]`)
d. Bryntum CSS classes (`.b-grid-row`, `.b-sch-event`) — last resort
e. NEVER XPath, never `:nth-child`

## Requirement 4 — Bryntum widget state

For counts, record values: prefer `page.evaluate()`:
```js
const count = await page.evaluate(() => window.scheduler?.eventStore.count);
```
Only use DOM assertions when JS API is unavailable.

## Requirement 5 — Navigation

Use `waitUntil: 'domcontentloaded'` (not `networkidle`) — Bryntum SPAs never reach networkidle.

## Requirement 6 — Auth check

Every navigation must include an auth check (`url.includes('/loginsso')`).

## Requirement 7 — Screenshots

Screenshot on failure only (except final passing evidence screenshot).

## Requirement 8 — Entity-scoped routes

For `/campaigns/:id`, `/jobs/:id`, etc.: discover the entity by navigating the listing page (find the first numeric-id link), never hardcode an id.

---

## YAML Registry

After writing the spec, ALSO write/update:
File: `~/.agent-os/omg/registry/features/<feature-slug>.yml`

```yaml
# Feature: <human description>
# Ticket: <TICKET_ID>
ticket: <TICKET_ID>
description: >
  <one paragraph from the plan>

routes:
  <route_name>:
    path: <url-pattern>      # e.g. /campaigns/:id/jobs
    confirmed: false

entry: "${BASE_URL}/"
discovery:
  goal: <what the spec navigates to>
  steps:
    - <step 1>
    - <step 2>

acceptance:
  - <acceptance criterion 1 from plan>
  - <acceptance criterion 2 from plan>

selectors:
  <selector_name>: <CSS selector or id>
```
