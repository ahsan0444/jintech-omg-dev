# CHANGES — jintech-omg-dev 1.1.0 → 1.2.0 (improved-plugin)

Every change made during the plugin audit, grouped by file, with the reason. Anything not listed below is unchanged from the original.

---

## Critical fixes (correctness / contract violations)

### `hooks/hooks.json` — rewritten
1. **Registered the `skill-router` UserPromptSubmit hook.** The router script shipped in `hook-scripts/` and had tests, but was never registered in the plugin's hooks.json — it only worked on machines where someone had wired it up out-of-band in user settings. The plugin was not self-contained.
2. **Registered `enforce-skill-usage` (PreToolUse, Bash matcher).** Previously it lived only in the root `settings.json` with a **hardcoded absolute path** (`/Users/Shared/Code/jintech-omg-dev/...`) — broken on every machine except the author's, and never loaded anyway because Claude Code does not read a plugin-root `settings.json`.
3. **Replaced `sh -c '[ -f ... ] && python3 ... || exit 0'` wrappers with a Python dispatcher** (`hook-scripts/run-hook.py`). `sh` does not exist on Windows, directly contradicting the README's "Supports macOS and Windows" claim. The dispatcher preserves the fail-open guarantee (missing/broken script → exit 0, never blocks tools) using only Python, which is already a hard prerequisite.
4. **Widened PostToolUse matcher** from `Edit|Write` to `Edit|Write|MultiEdit|NotebookEdit` so graph updates fire for all file-mutating tools.
5. **SessionStart matcher** changed from `""` to `startup|resume` — no need to re-print graph status after `/clear`.
6. **Added explicit `timeout` values to every hook** (router 5s, PreToolUse 5–10s, PostToolUse 60s).

### `hook-scripts/run-hook.py` — new file
Cross-platform fail-open dispatcher (see above). Passes stdin/stdout/exit codes through unchanged so each target script's hook contract is preserved.

### `hook-scripts/enforce-mcp-search.py` — rewritten
1. **Fixed the PreToolUse output contract.** The original printed its block message to **stdout** and exited 2 — but for exit 2, Claude Code feeds **stderr** (not stdout) back to Claude, so the carefully written MCP-redirect instructions never reached the model. Replaced with the official JSON decision format: `{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": ...}}` on stdout + exit 0.
2. **Fixed a false-positive class.** The old Bash regex `grep.+[/\\](lib|public[/\\]javascripts|t)([/\\]|$)` blocked *any* grep touching *any* `lib/` path — e.g. `grep foo /usr/lib/python3` was blocked. The check is now anchored to the active repo root (verified by smoke test).
3. **Parse stdin before subprocess work.** The original ran `git rev-parse` (and potentially the CRG `repos` subprocess) on *every* Grep/Bash call before knowing whether the call was even grep-shaped. Now non-matching calls exit in microseconds — this hook fires on every Bash call in a session, so latency matters.
4. **Uses `cwd` from the hook input** (official field) instead of `os.getcwd()`, which can differ from the session's working directory.

### `hook-scripts/enforce-skill-usage.py` — rewritten
Same stdout/exit-2 contract fix as above → official JSON deny format. Logic unchanged.

### `.claude-plugin/plugin.json` — fixed
1. **Removed `"CRG_DB_PATH": "${PROJECT_ROOT}/..."`.** `${PROJECT_ROOT}` is not a variable Claude Code expands (only `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PROJECT_DIR}` exist), so the env var was set to a literal junk path. Harmless only because `start-crg.py`'s own docstring says the server is multi-repo and ignores a fixed DB path — so the correct fix is deletion, not substitution.
2. Added `homepage` and `license` fields; bumped version to 1.2.0.

### Stale Atlassian MCP tool names — fixed everywhere
`mcp__claude_ai_Atlassian__*` (13 occurrences across `skills/ticket`, `skills/pr`, `procedures/inline/ticket-status.md`, `ticket-comment.md`, `ticket-transition.md`, and `settings.json`) renamed to the current `mcp__plugin_atlassian_atlassian__*` prefix used by the installed Atlassian plugin. With the old names, every ticket fetch/comment/transition step would fail tool resolution and burn a retry round in a Haiku subagent.

### `skill-routing-manifest.json` — fixed paths + over-trigger
1. **Inline procedure paths** changed from `~/.claude/procedures/inline/*.md` (a location the plugin never installs to — every inline route silently no-opped on a fresh install) to `${CLAUDE_PLUGIN_ROOT}/procedures/inline/*.md`, resolved by the router (user-absolute paths still honoured as overrides).
2. **`ticket-id-direct` demoted from high → low confidence.** Any prompt *mentioning* an OMGXI id ("review my notes on OMGXI-12") force-routed to a full ticket investigation. As low confidence it now hedges ("possible match — verify") instead of mandating.
3. **`prepr` patterns tightened.** `\bpre.?pr\b` matched any *mention* of the word — including "evaluate the prepr skill", which misrouted the very audit request that produced this report. Now requires the prompt to start with `prepr`, use an imperative ("run/do/start pre-pr"), or name "pre-pr checks/audit/review".

### `hook-scripts/skill-router.py` — inline path resolution
Added `resolve_inline_file()`: expands `${CLAUDE_PLUGIN_ROOT}`, then `~`, then falls back to plugin-root-relative — matching the manifest fix above. Everything else (timeout watchdog, fail-open, logging, slash interception) unchanged.

---

## Robustness / error-handling fixes

### `servers/start-crg.py` — rewritten
1. **Install failures no longer crash with a raw traceback.** `subprocess.run(..., check=True)` exceptions are caught; the user gets an actionable stderr message with the exact manual commands, and a half-built venv is removed so the next start retries cleanly. Added an explicit Python ≥3.12 pre-check with a clear message (previously surfaced as an opaque pip resolution error).
2. **Windows serve fix:** `os.execv` on Windows spawns a child and returns in the parent, severing the MCP stdio pipes — the server would die immediately. Now: `subprocess.run` (blocking) on win32, `execv` on POSIX.
3. **`python -m pip`** instead of a hardcoded `pip`/`pip.exe` binary path (pip shim not guaranteed to exist in all venv configurations).
4. **`embed.log` capped at 5 MB** with one-generation rotation (previously unbounded append forever).
5. Windows-correct detached spawn flags for the background embed process (`DETACHED_PROCESS` instead of POSIX-only `start_new_session`).

### `hook-scripts/post-edit-update.py` — rewritten
1. **Reads the hook input** (previously ignored stdin entirely) and **skips non-source files** — the original ran a full `code-review-graph update` subprocess after every `.md`/`.json`/plan-file edit.
2. Repo root derived from the **edited file's directory**, falling back to the input's `cwd` — edits made from a parent directory now update the right repo.
3. Subprocess timeout raised 30s → 50s, within the new 60s hook timeout.

### `hook-scripts/session-start-status.py` — updated
1. Consumes the hook's stdin JSON and uses its `cwd` field.
2. Fixed the not-found message: it recommended `/plugin reinit jintech-omg-dev`, **a command that does not exist**. Now explains the server self-installs on first MCP start and points at `/plugin` → reinstall.

### `tests/test_skill_router.py` — fixed
1. **`PLUGIN_ROOT` no longer hardcoded** to the author's checkout path — derived from the test file's location (overridable via `PLUGIN_ROOT_OVERRIDE`).
2. **Fixed a pre-existing red test:** `test_slash_prefix` asserted empty output for `/ticket OMGXI-1234`, but the script's Stage 0.5 (added later) intentionally emits a routing instruction for known slash commands — the shipped suite failed against the shipped script. Split into `test_slash_prefix_known_command_routes` (asserts routing + ARGUMENTS passthrough) and `test_slash_prefix_unknown_command_silent`.
3. Full suite verified green against the improved plugin: **14/14 pass** (original: 11/13).

---

## Security fixes

### Bitbucket credentials out of process argv
`curl -u "$BITBUCKET_USER:$BITBUCKET_TOKEN"` exposes the token to any local process via `ps` for the duration of the call. All 7 call sites (`skills/pr/SKILL.md` ×4, `procedures/inline/pr-address-comments.md` ×2, `pr-fetch-comments.md` ×2) now pipe a curl config stanza via stdin:
```bash
printf 'user = "%s:%s"\n' "$BITBUCKET_USER" "$BITBUCKET_TOKEN" | curl -s -K - ...
```
`printf` is a shell builtin, so the credentials never appear in a process list. The `/pr` skill's Auth ground rule was updated to state this as the requirement. README gained a note on minimal app-password scoping.

---

## Schema-compliance / standards fixes

### `settings.json` — converted to documented template
Claude Code does not load a `settings.json` shipped at a plugin root, so the original's hook registration (hardcoded path) and permissions silently did nothing. The hook moved to `hooks/hooks.json` (see above); the file is now an explicitly labelled **permissions template** with a `_comment` telling users to copy the allow-list into their project's `.claude/settings.json`. Allow-list updated: stale `mcp__claude_ai_Atlassian__*` entries replaced, and `mcp__plugin_jintech-omg-dev_code-review-graph__*` variants added (the prefix the tools get when served via the plugin).

### Skills — frontmatter cleanup (all 6)
Removed the nonstandard `trigger: /x` frontmatter key (not part of the SKILL.md schema; the slash command comes from the skill/command name itself). `name` and `description` retained — both already compliant (dir-matching names, third-person descriptions with trigger conditions).

### Commands — argument handling added (all 4)
- `resume-session.md`: `argument-hint` + explicit `$ARGUMENTS` reference (it documented argument forms but never consumed `$ARGUMENTS`).
- `save-session.md`: `argument-hint` + dynamic `!`date +%Y-%m-%d`` injection so the dated filename uses the real date instead of a guessed one.
- `embed-graph.md`: `argument-hint` + `allowed-tools` allow-list (both MCP name variants + the git detection commands).
- `learn.md`: `argument-hint` + `disable-model-invocation: true` (pattern extraction should be a deliberate user action, not something the model self-triggers).

---

## Portability fixes (macOS + Windows)

1. **Repo-detection fallback loops** in `skills/ticket`, `skills/debug`, `skills/grill-me`, and `commands/embed-graph.md` now include `/c/Code/*` (Git Bash) candidates alongside `/Users/Shared/Code/*`.
2. `skills/pr` `/tmp` payload guidance gained a Windows note (Git Bash maps `/tmp`; fallback to `<REPO_ROOT>/.planning/` if not).
3. `sh -c` removal and `os.execv` fix above are also portability fixes.

---

## Documentation fixes

### `README.md`
1. New **Hooks** section: all five hooks, their events, fail-open guarantee, router kill switch (`CLAUDE_SKILL_ROUTER_DISABLED=1`), manifest override paths, and `\`-prefix bypass. The router — the plugin's most user-visible behaviour — was previously undocumented.
2. "What's included" hooks row corrected (was missing `skill-router` and `enforce-skill-usage`).
3. Security note for token scoping (above).
4. Permissions-template note explaining what `settings.json` is and is not.
5. Removed both references to the nonexistent `/plugin reinit` command (also in `commands/embed-graph.md`).

### `WORKFLOW.md`
Persistence map claimed `session-log.md` is "auto-written by Stop hook" — **no Stop hook exists anywhere in the plugin**. Replaced with the real artifact: `~/.claude/session-data/` files written by `/save-session` / read by `/resume-session`.

### `CLAUDE.md`
Added an **Active Hooks** table so the model knows how to respond to each hook's output — including explicit guidance that a router instruction is a strong hint, not a mandate, when the matched skill clearly doesn't fit (the failure mode observed during this audit).

### `.gitignore`
Added `servers/embed.log.1` (new rotation artifact).

---

## Verified
- `python3 -m py_compile` clean on all hook scripts, server scripts, and tests.
- All JSON files validate.
- Router test suite: 14/14 green.
- Smoke tests: `enforce-skill-usage` denies `gh pr create` with valid JSON decision; `enforce-mcp-search` denies grep in `omg/lib` and **allows** `grep foo /usr/lib/python3` (original blocked it); dispatcher exits 0 on malformed stdin and missing target script.

---

# Round 2 — architectural improvements

## Custom agents (`agents/` — new)
- **`agents/omg-investigator.md`** — read-only locator agent (haiku). Tool list contains **no Read/Edit/Write** — the "no file reads in subagents / locations not contents" discipline, previously repeated as HARD RULES prose in every subagent prompt, is now enforced by tool permissions. Includes both `mcp__code-review-graph__*` and `mcp__plugin_jintech-omg-dev_code-review-graph__*` tool-name variants plus Grep/Glob/Bash/ToolSearch/WebFetch/WebSearch. MCP-first policy, budgets, "absent by design" rule, and a default output schema baked into its system prompt.
- **`agents/omg-implementer.md`** — single-step executor (sonnet). OMG layer rules table, grep-first edit procedure, Chesterton's Fence, and the red-green TDD loop live in the agent's system prompt instead of being re-pasted into every `/implement` step prompt.
- **Skills rewired:** all codebase/lint/psql subagents (`subagent_type="Explore"`) → `omg-investigator` (ticket ×4, debug ×3, grill-me ×2, prepr ×7, pr ×2, implement ×2); all edit subagents (`general-purpose`) → `omg-implementer` (implement Step 2, prepr Step 3c). Jira/JAM/Confluence fetch agents **stay on `Explore`** — they need Atlassian/Jam MCP tools the investigator deliberately lacks. A fallback note under each skill's Model Usage section covers installs with plugin agents disabled.

## Bitbucket pagination (real truncation bug)
`procedures/inline/pr-fetch-comments.md` and `pr-address-comments.md` rewritten: the comments endpoint defaults to `pagelen=10`, so PRs with 11+ comments silently dropped the rest. Now a single Python (urllib) block requests `pagelen=100` **and follows `next` links** until exhausted. Side benefit: credentials move from curl argv to an Authorization header built inside Python from env vars — never visible in the process list at all.

## CI + hook test coverage
- **`.github/workflows/ci.yml`** — matrix (ubuntu/windows × Python 3.12/3.14): compileall, JSON validation, plugin-manifest field check, full unittest run. Windows leg creates a `python3` shim, matching the plugin's documented prerequisite.
- **`tests/test_hooks.py`** — 11 new tests covering the dispatcher (missing script fails open), `enforce-skill-usage` (deny JSON contract for `gh pr create`, allow, malformed stdin), and `enforce-mcp-search` (deny in covered dirs of a fixture git repo with graph.db, `views/` exemption, no-graph repos allowed, and a regression test for the `/usr/lib` false positive).
- **Bug found by the new tests:** repo-anchored matching in `enforce-mcp-search.py` broke under macOS path aliasing (`/var` vs `/private/var` — git returns the resolved root, tool input uses the alias). Fixed with realpath normalisation for Grep paths and root-spelling variants for Bash command matching. Suite: **25/25 green**.

## Antipatterns log hygiene (`skills/prepr/SKILL.md` Step 3b)
Appends are now deduplicated (`grep -qF` guard — re-running /prepr on the same blocker no longer duplicates the entry; branch dropped from the entry key so the same issue found on two branches dedupes too) and the file is capped at ~400 entries, keeping the newest.

---

# Round 3 — remaining audit items

## Progressive disclosure (official skill-authoring guidance: lean SKILL.md, on-demand references)
Conditional sections moved verbatim into per-skill `references/` files, loaded with one Read only when their condition fires:
- `skills/ticket/` 634 → **518 lines**; `references/conditional-steps.md` holds Step 2a (Confluence), 2b (JAM), 2c retry, 2c-db — none load for the common no-URL, no-DB, high-confidence ticket.
- `skills/prepr/` 560+ → **318 lines**; `references/check-prompts.md` holds all five 1a–1e check templates; SKILL.md keeps a bucket→§ table and spawns only non-empty buckets.
- `skills/pr/` 518+ → **448 lines**; `references/update-existing-pr.md` holds the PR_EXISTS=yes branch (rebase check, force-with-lease, description PUT).
All SKILL.md files now under 520 lines; pointer text states exactly when to Read each reference.

## Workspace/environment extraction — one place to relocate
- `OMG_WORKSPACE_ROOT` (default `/Users/Shared/Code`) now drives every repo-detection fallback loop (ticket, debug, grill-me, embed-graph) — replaced the duplicated macOS + `/c/Code` hardcoded lists.
- `OMG_BITBUCKET_WORKSPACE` (default `zlalani`) now drives every Bitbucket URL: `/pr` sets `BB_WORKSPACE` once in Step 1; both comment procedures read it via `os.environ`. The literal `zlalani` survives only as the documented default.
- README gained an "Optional environment overrides" section; CLAUDE.md instructs never to hardcode either value again.

## Atlassian tool-name resilience
TOOL DISCOVERY notes added to every Jira/Confluence call site (ticket Step 1 + 2a, pr ticket fetch, ticket-status/comment/transition procedures): if the named tool is unknown, discover the install's actual prefix via `ToolSearch(query="+jira <tool>")` instead of failing — the `mcp__plugin_atlassian_atlassian__` names are now documented defaults, not hard dependencies.

## Router feedback loop — `commands/router-stats.md` (new)
Parses `~/.claude/logs/intent-router-*.jsonl`: total matches, per-intent counts, action-type breakdown over N days (arg, default 30); flags interpretation guidance (loose patterns, dead patterns, menu collisions). Prunes log files older than 30 days — the log dir previously grew forever with no consumer.

## Docs
- README: Windows `python3` troubleshooting now gives the actual shim command (python.org builds ship no `python3.exe`); commands row includes `/router-stats`; design note added on regex-router limits and the long-term direction (prefer skill-description triggers; router for inline procedures only).

---

## Not changed (deliberately)
- Skill body logic/prose for all 6 skills (orchestration design is strong; only tool names, frontmatter, auth, and paths were touched).
- `docs/superpowers/` design artifacts (historical records).
- `servers/_run_embed.py`, `requirements.txt` (correct as-is).
- `tests/router-fixtures.jsonl` (all fixtures still pass against the tightened manifest).
