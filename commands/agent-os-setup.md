---
description: Bootstrap the Agent OS data home + verify harness on this machine (product graph, registry, Playwright, auth capture). Run once per machine, or after cloning, to set up the /verify workflow.
---

# /agent-os-setup

Set up the Agent OS for a repo on THIS machine. Cross-platform (macOS + Windows). Idempotent —
safe to re-run. Nothing here writes to the production app repo.

Resolve `AGENT_OS_HOME` (default `~/.agent-os`) and `PLUGIN` (`${CLAUDE_PLUGIN_ROOT}`). Ask the
user which repo to set up (default `omg`, repo_root e.g. `/Users/Shared/Code/omg`).

## Steps (run in order; stop and report on any failure)

1. **Data home + config**
   - `mkdir -p $AGENT_OS_HOME/<repo>/{registry/features,registry/.pending,specs,.product-graph,.auth,.verify/out}`
   - Create `$AGENT_OS_HOME/config.yml` mapping `name`/`repo_root`/`data` if absent.
   - Create `$AGENT_OS_HOME/.gitignore` ignoring `.cache/`, `*/registry/.env.local`, `*/registry/.pending/`, `*/.auth/`, `*/.verify/out/`, `*/.product-graph/*.db`.
   - Seed `registry/env` (BASE_URL, RESTART_CMD, APP_CONTAINER, HEALTH_URL, HEALTH_EXPECT, WAIT_TIMEOUT) and `registry/auth.yml`. **Ask the user** for environment specifics (host, restart command, readiness path) — never guess; confirm the host returns the expected pre-auth response.

2. **Secrets** — copy `registry/.env.local.example` → `registry/.env.local`. By default nothing is required (auth = captured storageState; entity pages reached by UI discovery from the authenticated BASE_URL landing page). Only fill it if switching to form auth (`TEST_USER`/`TEST_PASS`). Never commit it.

3. **Verify harness deps** — in `$PLUGIN/servers/verify`: `npm ci` (uses the committed lockfile → deterministic Playwright). Then install BOTH browser builds (Playwright 1.49 splits them; headed capture needs `chromium`, headless validate/specs need `chromium-headless-shell`): `npx playwright install chromium chromium-headless-shell`.

4. **Product graph** — build it: `"$PLUGIN/servers/venv/bin/python" "$PLUGIN/servers/product-graph/build.py" --repo <repo>` (the MCP bootstrap also installs deps). Verify counts print.

5. **Capture auth** (manual, interactive) — `node "$PLUGIN/servers/verify/capture-auth.mjs" --repo <repo>`: a headed browser opens at BASE_URL; user completes SSO; state saved to `$AGENT_OS_HOME/<repo>/.auth/state.json` (private, gitignored).

6. **Smoke test** — `node "$PLUGIN/servers/verify/restart.mjs" --repo <repo> --check-only` (expect READY) and `node "$PLUGIN/servers/verify/tier1.mjs" --repo <repo> --feature <a feature>` (expect PASS). Report the result file.

7. Confirm the plugin's product-graph MCP server is enabled in the client and that session-start prints `[agent-os] product-graph: …`.

Report what succeeded and what the user must still do (fill `.env.local`, capture auth). Then: "Setup done — run `/verify <feature>` to verify a change."
