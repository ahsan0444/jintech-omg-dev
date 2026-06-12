---
name: prepr
description: Pre-PR review — audits all branch changes against OMG coding standards. Runs Perl::Critic for Perl files, checks OMG layer conventions, validates templates, JS, and DB scripts. Reports blockers vs warnings before a PR is raised.
---

# /prepr

You are the Pre-PR Review Orchestrator. You audit every changed file on the current branch against OMG coding standards and report what must be fixed before a PR is raised.

**You do not read files directly in main context.** All checking runs inside Haiku subagents. You receive structured findings and synthesise a final report.

**Target: main context under 20k tokens at report-complete.**

---

## Ground Rules

- **Orchestrate, don't check.** Spawn Haiku subagents per file type — all linting, reading, and grep work happens inside them.
- **Parallel by default.** All file-type checks run concurrently after Step 0.
- **Blockers vs warnings.** Blockers must be fixed before a PR. Warnings are recommended fixes. Pass means clean.
- **Synthesis only.** When collecting subagent results, record only blockers and warnings — discard "clean" / "none" prose. The Step 2 report is built from findings, not from re-quoting subagent output.
- **Never read compiled files.** No `*.min.js`, bundled Bryntum sources.

---

## Model Usage

> **Plugin agents:** codebase/lint/psql subagents use `omg-investigator` (read-only, no-file-reads enforced by tool permissions); edit subagents use `omg-implementer` (layer rules + TDD baked in). If these agent types are unavailable (plugin agents disabled), fall back to `Explore` / `general-purpose` with the same prompts. Jira/JAM/Confluence fetches stay on `Explore` (they need Atlassian/Jam MCP tools).

| Task | Model | Subagent type |
|---|---|---|
| File reads, grep, lint output parsing | `haiku` | `Explore` |
| Synthesis and report writing | `sonnet` | Main context |

---

## Step 0 — Repo Detection and Changed Files

Run directly in main context (the **only** permitted direct Bash call):

```bash
REPO_ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)
REPO_NAME=$(basename "$REPO_ROOT" 2>/dev/null)
CURRENT_BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null)

# Check for approved plan file to inherit BASE_BRANCH
PLAN_FILE=$(ls "$REPO_ROOT/.planning/approved-plan-"*.md 2>/dev/null | head -1)
if [ -n "$PLAN_FILE" ]; then
  BASE_BRANCH=$(grep "^base:" "$PLAN_FILE" | sed 's/base: //')
  echo "BASE_BRANCH=$BASE_BRANCH (from plan file)"
else
  DETECTED_BASE=$(git -C "$REPO_ROOT" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@' || echo "unknown")
  echo "BASE_BRANCH=$DETECTED_BASE (auto-detected — confirm or type a different branch)"
fi

echo "REPO=$REPO_NAME | BRANCH=$CURRENT_BRANCH"

# Merge conflict guard
git -C "$REPO_ROOT" diff --check 2>&1 | head -5
```

**If REPO_ROOT is empty**, stop: *"Not inside a git repository. cd into the correct repo and re-run."*

**If BASE_BRANCH was auto-detected** (no plan file):

- If DETECTED_BASE is "unknown" (symbolic-ref failed), output:
  ```
  Could not auto-detect base branch for <REPO_NAME>.
  Type the branch to compare against (e.g. main, master, develop):
  ```
  Wait for response. Record as **BASE_BRANCH**.

- Otherwise output:
  ```
  Repo:           <REPO_NAME>
  Current branch: <CURRENT_BRANCH>
  Merge target:   <DETECTED_BASE>  ← auto-detected

  Correct merge target? Press Enter to confirm or type a different branch name:
  ```
  Wait for response. If user presses Enter (empty response), use DETECTED_BASE. Otherwise record the typed value as **BASE_BRANCH**.

**If `git diff --check` shows conflict markers**, stop immediately:
> *"Branch has unresolved merge conflicts — resolve them before running /prepr."*

**Get changed files:**

Prefer uncommitted changes (the current ticket's work-in-progress) over the full branch diff. Use this logic:

```bash
# Priority 1: uncommitted changes (working tree + staged)
UNCOMMITTED=$(
  { git -C "$REPO_ROOT" diff --name-only; git -C "$REPO_ROOT" diff --cached --name-only; } \
  | sort -u
)

if [ -n "$UNCOMMITTED" ]; then
  CHANGED_FILES="$UNCOMMITTED"
  echo "SCOPE=uncommitted ($(echo "$UNCOMMITTED" | wc -l | tr -d ' ') files)"
else
  # Priority 2: commits on this branch matching the ticket ID
  TICKET_ID=$(echo "$CURRENT_BRANCH" | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
  if [ -n "$TICKET_ID" ]; then
    TICKET_FILES=$(git -C "$REPO_ROOT" log --name-only origin/"$BASE_BRANCH"..HEAD \
      --grep="$TICKET_ID" --pretty="" 2>/dev/null | sort -u)
  fi
  if [ -n "$TICKET_FILES" ]; then
    CHANGED_FILES="$TICKET_FILES"
    echo "SCOPE=committed (ticket $TICKET_ID — $(echo "$TICKET_FILES" | wc -l | tr -d ' ') files)"
  else
    # Fallback: full branch diff — may include other tickets' changes
    CHANGED_FILES=$(git -C "$REPO_ROOT" diff --name-only origin/"$BASE_BRANCH"...HEAD)
    echo "SCOPE=full branch diff vs $BASE_BRANCH — $(echo "$CHANGED_FILES" | wc -l | tr -d ' ') files (may include unrelated commits)"
  fi
fi
```

Categorise into buckets:
- **perl** — `*.pm` files
- **sql** — `*.sql` files
- **tt** — `*.tt` template files
- **js** — `*.js` files (excluding `*.min.js`)
- **scss** — `*.scss` files
- **css** — `*.css` files in `public/css/`

**Exclude before categorising:**
- Any file under `locale/` — machine-managed i18n, no standards apply
- Any file under `graphify-out/` or `.planning/`
- JSON files are never in scope for pre-PR review

If no files remain after exclusions: *"No reviewable changes found vs <BASE_BRANCH>."*

---

## Step 0.5 — Semantic Risk Assessment (Haiku, Explore)

Spawn immediately after Step 0, **before** the parallel lint checks. Results feed into synthesis as a risk tier.

```
Agent(
  description="Semantic risk assessment — changed files",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed files: <full list from Step 0>
  Repo root: <REPO_ROOT>
  Tool call budget: 3.

  PHASE 1 — Risk-score every changed file:
    mcp__code-review-graph__detect_changes_tool(changed_files=["<file1>", "<file2>", ...], repo_root="<REPO_ROOT>")
    Identifies hub nodes, bridge nodes, cross-community coupling, and risk scores.
    If graph.db is absent or tool errors: return RISK_TIER: unknown and stop.

  PHASE 2 — Blast radius (only for files that score high-risk in Phase 1):
    For each high-risk file:
    mcp__code-review-graph__get_impact_radius_tool(node="<high-risk node name>", repo_root="<REPO_ROOT>")
    Returns all nodes that transitively depend on this node.

  Return schema only (no prose):

  RISK_TIER: high | medium | low | unknown
  HIGH_RISK_FILES:
    - <file path> — <reason: hub node | bridge node | cross-community | high dependent count>
  IMPACT_RADIUS:
    - <file path> — <N> dependents: <top 3 dependent names>
  (omit HIGH_RISK_FILES and IMPACT_RADIUS sections entirely if RISK_TIER is low or unknown)
  """
)
```

Collect result. Proceed to Step 1 in parallel with this result available for synthesis.

---

## Step 1 — Parallel Checks

Spawn all applicable subagents **in one message** based on non-empty buckets:

---

### Check templates (1a–1e)

Read `references/check-prompts.md` once (one Read covers all five templates), then spawn **only the agents whose bucket is non-empty**, all in one message (haiku, omg-investigator):

| § | Bucket | Check |
|---|---|---|
| 1a | perl | perlcritic + OMG layer conventions + graph context |
| 1b | tt | HTML encoding, i18n, inline JS |
| 1c | js | omg namespace, $.ajax, globals |
| 1d | scss/css | direct CSS edits, import order, !important |
| 1e | sql | naming, rollback pair, live DB validation |

## Step 2 — Perl Test Suite (conditional — after Step 1 completes)

Run **only after all Step 1 subagents have returned** and **only if Perl files were changed**.

Output to main context before spawning:
> *"Running Perl test suite..."*

```
Agent(
  description="Run Perl test suite",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Run the Perl test suite:
    cd <REPO_ROOT> && prove -l t/ 2>&1 | tail -30

  If prove is not available: perl t/001_base.t 2>&1

  Return schema only (no prose):

  TEST_RESULT: pass | fail | error
  FAILURES: <test name + one-line error only, or "none">
  """
)
```

---

## Step 3 — Synthesise Report

Collect all subagent results. Build the report from findings only — do not re-quote "clean" or "none" results.

```
# Pre-PR Review: <CURRENT_BRANCH> → <BASE_BRANCH>

## Summary
Changed files: <N> | Perl: <n> | TT: <n> | JS: <n> | SCSS/CSS: <n> | SQL: <n>
Test suite: pass | fail | not run

---

## ⚡ RISK TIER: <high | medium | low | unknown>
<If high or medium: list HIGH_RISK_FILES with reason and IMPACT_RADIUS>
<If low: "No high-risk files detected — changes are architecturally contained.">
<If unknown: "Graph not available — semantic risk assessment skipped.">

---

## 🚫 BLOCKERS (<N> — must fix before PR)
<file>:<line> — <issue> — <how to fix>
...
(or "None — clear to proceed")

---

## ⚠️ WARNINGS (<N> — recommended fixes)
<file>:<line> — <issue>
...
(or "None")

---

## ✅ CLEAN
<list of file types with zero findings>
```

**If CSS BLOCKER found**, append:
> *"Edit the relevant SCSS file instead, then run `build_sass.sh` to recompile. Do not commit the compiled CSS."*

If blockers:
> *"Fix the blockers above before raising a PR. Re-run `/prepr` after fixing to confirm clean."*

If clean:
> *"No blockers. Ready to raise a PR."*

---

## Step 3b — Antipattern Memory (run after synthesis, only if blockers found)

Run directly in main context for each BLOCKER:

```bash
ANTIPATTERNS="$HOME/.claude/memory/antipatterns.md"
DATE=$(date -u +"%Y-%m-%d")
mkdir -p "$(dirname "$ANTIPATTERNS")"

if [ ! -f "$ANTIPATTERNS" ]; then
  printf "# Antipatterns\n\nAuto-captured BLOCK findings from /prepr runs.\n\n" > "$ANTIPATTERNS"
fi
```

For each BLOCKER, append one line — **deduplicated** (the same file+issue re-found on a re-run must not append again):
```bash
ENTRY="$REPO_NAME: <FILE> — <BLOCKER description>"
grep -qF "$ENTRY" "$ANTIPATTERNS" || printf -- "- [%s] %s\n" "$DATE" "$ENTRY" >> "$ANTIPATTERNS"
```

After all appends, cap the file at 400 entries (keep the newest):
```bash
LINES=$(wc -l < "$ANTIPATTERNS" | tr -d ' ')
if [ "$LINES" -gt 400 ]; then
  { head -3 "$ANTIPATTERNS"; tail -n 380 "$ANTIPATTERNS"; } > "$ANTIPATTERNS.tmp" && mv "$ANTIPATTERNS.tmp" "$ANTIPATTERNS"
fi
```

This builds a rolling, bounded log that future sessions load to proactively avoid the same patterns.

---

## Step 3c — Self-Healing Warnings (only if `/prepr fix` was invoked)

Check if the user typed `/prepr fix`. If yes and WARNINGS exist:

For each WARNING, spawn a fix agent:

```
Agent(
  description="Fix warning: <issue> in <file>",
  subagent_type="omg-implementer",
  model="sonnet",
  prompt="""
  File: <absolute path>
  Issue: <warning description> at line <N>
  Repo root: <REPO_ROOT>

  Fix only the specific warning described. Minimal change — do not refactor surrounding code.
  Follow OMG conventions (use strict/warnings for Perl, l() for TT strings, etc.).

  Return: file path, line number changed, one-line description of what changed.
  """
)
```

After all fix agents complete: re-run Step 1 checks for the fixed files only (spawn targeted subagents per file type). Merge updated results into synthesis — mark each resolved warning as `(auto-fixed)`. Report remaining warnings as-is.

If `/prepr fix` was NOT invoked: skip this step entirely.

---

```
---
# Next Up

  Clean:   run /pr to create the draft PR
  Blocked: fix the issues above, then re-run /prepr

Also available:
  - /implement — continue with another ticket's approved plan
  - /ticket <ticket-id> — start a new ticket

Done — start a fresh session for the next phase.
---
```
