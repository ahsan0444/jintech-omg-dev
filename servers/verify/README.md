# Verify Harness (Node)

Deterministic executable bits the Python `/verify` skill shells into. Cross-platform
(macOS + Windows), Node 18+ (built-in `fetch`, no axios). Playwright is pinned and the
lockfile is committed.

## Contract

The harness reports to its caller **only** via:

1. **process exit code** — `0` = PASS, non-zero = FAIL; and
2. **a tiny result file** at `<DATA>/.verify/out/<feature>.result.json`:

```json
{ "status":"PASS"|"FAIL", "tier":1|2, "feature":"<name>",
  "failing_assertion":"<text|null>", "screenshot":"<abs path|null>",
  "observed":"<short>", "expected":"<short>" }
```

No rich stdout payload. No page DOM is ever dumped. `<DATA>` for `omg` is `~/.agent-os/omg`.

## Privacy / security invariants

- The captured auth state token / cookies are **PRIVATE** — never printed, logged,
  screenshotted, or committed. `state.json` lives in the gitignored `<DATA>/.auth/` dir.
- The login / IdP page is never screenshotted.
- The health probe uses `redirect:'manual'` so it can read the 302 `Location` without
  following it (and without ever touching the IdP).

## SSO readiness rule

This host 302-redirects ALL unauthenticated requests to the IdP. **That redirect means the
app is UP.** `HEALTH_EXPECT=redirect:/loginsso` => a `3xx` whose `Location` contains
`/loginsso` is HEALTHY (`ok=true`). The format also supports `status:200`.
Connection-refused / 502 / 504 / timeout = NOT ready.

## CLIs

| Command | Purpose |
|---|---|
| `node restart.mjs --repo omg` | Restart the dev container, then poll until READY (container `Up` AND health matches). Falls back to `RESTART_CMD_FALLBACK`. Exit 0 READY / 1 NOT_READY. |
| `node restart.mjs --repo omg --check-only` | Skip restart; only probe readiness against the already-running app (non-disruptive). |
| `node auth.mjs validate --repo omg` | Validate the captured session. Exit 0 `AUTH_OK`, 3 `AUTH_MISSING`, 2 `AUTH_EXPIRED` (re-capture). Never logs cookies. |
| `node capture-auth.mjs --repo omg` | **Manual dev step.** Headed browser at `BASE_URL`; complete SSO; saves `storageState` to `AUTH_STATE_FILE`. Prints only the path. |
| `node tier1.mjs --repo omg --feature <f> [--endpoint /p --expect status:200\|redirect:/x]` | Tier 1, NO browser. Health probe + optional endpoint check. Writes result file, sets exit code. |
| `node run-spec.mjs --repo omg --feature <f> --spec <path>` | Tier 2. Runs one Playwright spec as a child process (storageState + baseURL wired in), reduces to the result-file shape (first failing assertion + screenshot). |

## Design check (Tier 2, opt-in)

Runs only when `<DATA>/.verify/design/<feature>.design.json` exists (written by the figma-omg skill).

```
node design-check.mjs --repo omg --feature <f> [--spec <path>]
```

Spec: `{ url, viewport, elements:[{ selector, expect:{prop:val}, states:{ hover:{prop:val} } }], figma_screenshot? }`.
Reads `getComputedStyle` per property (hover via `locator.hover()`); px ±1 per token, colours
canonicalised by the browser (hex/named -> `rgb[a]()`), `font-family` = first family, quotes
stripped, case-insensitive; anything else trimmed case-insensitive equality.
Evidence in `<DATA>/.verify/out/<feature>.design/`: `full.png`, `el-<n>.png`, `figma.png` (copy
for human side-by-side; no pixel diffing). Result `<feature>.design.result.json` adds
`elements[].properties|states.<state>.<prop> = {expected, actual, pass}`.
Exit 0 pass / 1 mismatch / 2 auth expired or missing / 4 bad spec.

## Characterization snapshots (Tier 1)

```
node snapshot.mjs record  --repo omg --routes routes.txt --label base [--feature <f>]
node snapshot.mjs record  --repo omg --routes /jobs,/campaigns --label base
node snapshot.mjs compare --repo omg --label base [--feature <f>]
```

GET only (a `POST /x` line is refused, exit 4; off-host URLs refused). Uses the saved auth
cookies via a Playwright request context (no browser), never follows redirects. Bodies are
normalised by the `NORMALIZERS` table (CSRF tokens, session ids, ISO timestamps, epoch ms,
`?v=` cache-busters) and stored in `<DATA>/.verify/snapshots/<label>/` (+ `manifest.json`);
compare writes `<label>.current/` and diffs with `git diff --no-index`. Result
`<feature>.snapshot.result.json` adds `routes[] = {route, status, changed, added, removed, head}`
(`head` = first 40 diff lines). Exit 0 same / 1 diff / 2 auth / 4 usage. The script never touches
git state — the caller stashes / checks out the base before `record`.

## Data resolution

- `AGENT_OS_HOME` env (default `~/.agent-os`); reads `config.yml` -> `repos[].{name,repo_root,data}`.
- For repo `omg`: `DATA=$AGENT_OS_HOME/omg`. Loads `registry/env` (KEY=VALUE, `#` lines
  ignored), `registry/auth.yml` (yaml), `registry/features/<f>.yml` (yaml), and optional
  secrets in `registry/.env.local`. Uses `js-yaml` + a manual env parser.

## Install (pinned)

```
npm install
```

This installs the **exact** pinned versions and commits `package-lock.json`:

- `@playwright/test` `1.49.1`
- `js-yaml` `4.1.0`

`npm install` does **not** download browser binaries. Tier-2 specs and `capture-auth.mjs`
need a Chromium binary via `npx playwright install` — that download is part of
`/agent-os-setup`, intentionally not run here. Tier-1 needs no browser.

## Cross-platform notes

- All paths are built with `node:path` / `node:os`; a leading `~` is expanded via `homedir()`.
- Child processes are spawned with **array args and `shell:false`** — no shell string
  interpolation anywhere.
- `npx` resolves to `npx.cmd` on Windows.
