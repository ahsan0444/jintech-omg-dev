---
name: prepr
description: Pre-PR review — audits all branch changes against OMG coding standards. Runs Perl::Critic for Perl files, checks OMG layer conventions, validates templates, JS, and DB scripts. Reports blockers vs warnings before a PR is raised.
trigger: /prepr
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

```bash
git -C "$REPO_ROOT" diff --name-only origin/<BASE_BRANCH>...HEAD
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
  subagent_type="Explore",
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

### 1a — Perl Review (Haiku, Explore)

```
Agent(
  description="Perl review — perlcritic + OMG conventions",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Changed Perl files: <list from Step 0>
  Repo root: <REPO_ROOT>

  PHASE 0 — Graph-based structural review (MCP, 1-3 calls, run before linting):
    For each changed Perl file (use module basename as node name):
    mcp__code-review-graph__get_review_context_tool(node="<module_basename>", repo_root="<REPO_ROOT>")
    → surfaces the node's role, its callers, callees, and any known complexity flags.
    Flag nodes with >10 callers as WARNING (high-impact change).

    mcp__code-review-graph__find_large_functions_tool(repo_root="<REPO_ROOT>")
    → check if any changed files contain functions flagged as overly large/complex.
    Flag matches as WARNING with function name and line count.

    mcp__code-review-graph__get_knowledge_gaps_tool(repo_root="<REPO_ROOT>")
    → check if any changed nodes appear in the gaps list (no test coverage).
    Flag matches as WARNING: "No test coverage for <node> — add tests before PR."

    If graph absent or any tool errors: skip Phase 0 silently and continue.

  PHASE 1 — Perl::Critic (run for each file):
    Try in order until one works:
      /opt/homebrew/bin/perlcritic --severity 3 <file_path>
      perlcritic --severity 3 <file_path>
    If neither works: report perlcritic: unavailable and skip.

  PHASE 2 — OMG Layer Conventions (grep-based, run for each file):

  For files in lib/*/dao/ (*_db.pm):
    - CHECK: must NOT contain 'bless'
      Grep: grep -n 'bless' <file>
    - CHECK: must not return blessed objects
      Grep: grep -n 'return.*->new' <file>

  For files in lib/*/dom/ (*_dom.pm):
    - CHECK: must contain 'sub TO_JSON'
      Grep: grep -n 'sub TO_JSON' <file>
    - CHECK: TO_JSON must return '{ %{ shift() } }'
      Grep: grep -n 'TO_JSON' -A2 <file>

  For files in lib/*/*_helper.pm:
    - CHECK: must not call foreign _controller methods
      Grep: grep -n '_controller->' <file>
    - CHECK: must not directly call foreign _db methods
      Grep: grep -n '_db->' <file>

  For files in lib/*/*_controller.pm:
    - CHECK: must not call foreign _controller methods
      Grep: grep -n '_controller->' <file>
    - CHECK: should not import foreign DAOs directly
      Grep: grep -n 'use.*_db;' <file>

  For route files (OMG*.pm):
    - CHECK: OMG_ajax.pm should only have AJAX routes
      Grep: grep -n 'template\|redirect' lib/OMG_ajax.pm (if changed)

  PHASE 3 — General Perl hygiene (all files):
    - CHECK: no hardcoded environment values
      Grep: grep -n 'localhost\|127\.0\.0\.1\|password.*=.*["\x27][^"\x27]*["\x27]' <file>
    - CHECK: use strict and use warnings present
      Grep: grep -n 'use strict\|use warnings' <file>

  Return schema only, per file (no prose):

  FILE: <path>
  GRAPH_ROLE: <node role summary from get_review_context_tool, or "unknown">
  LARGE_FUNCTIONS: <function names flagged by find_large_functions_tool, or "none">
  COVERAGE_GAPS: <nodes with no test coverage from get_knowledge_gaps_tool, or "none">
  PERLCRITIC: <violations list, or "clean">
  BLOCKER: <description — line N, or "none">
  WARNING: <description — line N, or "none">
  """
)
```

---

### 1b — Template Review (Haiku, Explore)

```
Agent(
  description="TT template review — OMG conventions",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Changed .tt files: <list from Step 0>
  Note: this codebase uses <% %> Template Toolkit tags (not [% %]).

  For each file:

  1. HTML encoding — user content must use | html_entity or | html:
     Grep: grep -n '<% [a-zA-Z]' <file> | grep -v '| html_entity\|| html\|l(\|IF\|FOREACH\|INCLUDE\|PROCESS\|END\|USE\|SET\|BLOCK\|#\|SWITCH\|CASE\|WRAPPER'
     Flag unfiltered variable output as BLOCKER.

  2. Hardcoded English strings — must use l() for display text:
     Grep: grep -n '>[A-Z][a-z]' <file> | grep -v 'l(\|<%#\|class=\|id=\|href=\|src=\|type=\|name=\|value=\|placeholder.*l('
     Flag suspicious hardcoded strings as WARNING.

  3. Module JS/CSS loaded in template instead of layout:
     Grep: grep -n '<script\|<link' <file>
     Flag shared layout resources loaded here as WARNING.

  4. Hidden inputs missing meaningful id attributes:
     Grep: grep -n 'type="hidden"' <file>
     Flag missing id as WARNING.

  5. Inline JavaScript:
     Grep: grep -n 'onclick=\|onchange=\|onsubmit=' <file>
     Flag as WARNING — should use event listeners.

  Return schema only, per file (no prose):

  FILE: <path>
  BLOCKER: <issue — line N, or "none">
  WARNING: <issue — line N, or "none">
  """
)
```

---

### 1c — JavaScript Review (Haiku, Explore)

```
Agent(
  description="JS review — OMG namespace conventions",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Changed .js files (excluding *.min.js): <list from Step 0>

  For each file:

  1. No raw $.ajax calls — must use omg.dataDelivery:
     Grep: grep -n '\.ajax(' <file>
     Flag $.ajax as BLOCKER.

  2. No new top-level globals — all code under omg namespace:
     Grep: grep -n '^var \|^let \|^const \|^function ' <file>
     Flag top-level declarations outside omg namespace as WARNING.

  3. No hardcoded display strings in alerts:
     Grep: grep -n "showFlashAlert\|alert(" <file> | grep -v 'localText\.'
     Flag hardcoded strings as WARNING.

  4. New files should use const/let not var:
     Check if file is newly added (git status in <REPO_ROOT>).
     If new: grep -n '^var ' and flag as WARNING.

  5. Class-based JS selectors (prefer data-ref):
     Grep: grep -n "\$('\.[a-z]\|querySelector('\.[a-z]" <file>
     Flag as WARNING (not blocker — legacy code uses them).

  Return schema only, per file (no prose):

  FILE: <path>
  BLOCKER: <issue — line N, or "none">
  WARNING: <issue — line N, or "none">
  """
)
```

---

### 1d — CSS/SCSS Review (Haiku, Explore)

```
Agent(
  description="CSS/SCSS review",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Changed CSS files: <css list from Step 0>
  Changed SCSS files: <scss list from Step 0>
  Repo root: <REPO_ROOT>

  CHECK 1 — Direct CSS edits are not allowed:
    Files in public/css/ must not be edited directly (compiled from SCSS via build_sass.sh).
    If any public/css/*.css files are in the changed list: flag each as BLOCKER.
    Exception: public/css/bryntum/*_omg.css overrides — flag as WARNING not blocker.

  CHECK 2 — SCSS import order (for changed app.scss only):
    Grep: grep -n '@import' <file>
    Expected order: style → login → global → bootstrap
    Flag wrong order as WARNING.

  CHECK 3 — !important overuse:
    Grep: grep -c '!important' <file>
    If count > 5 in a single file: flag as WARNING with count.

  Return schema only (no prose):

  CSS_DIRECT_EDITS: <list of blocked files, or "none">
  SCSS_WARNINGS: <list with line numbers, or "none">
  """
)
```

---

### 1e — SQL / DB Script Review (Haiku, Explore)

```
Agent(
  description="SQL/DB script review — OMG naming conventions",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Changed SQL files: <list from Step 0>
  Repo root: <REPO_ROOT>

  For each file:

  1. File naming convention: dbscripts/s<sprint>/<n>_<TICKET>_<description>.sql
     Flag non-conforming names as BLOCKER.

  2. Deploy/rollback pair:
     Check that for every deploy file a matching rollback exists.
     ls <parent_dir>/rollback/ for matching name.
     Missing rollback = BLOCKER.

  3. Function naming: <entity>_<scope>_<verb> pattern:
     Grep: grep -n 'CREATE.*FUNCTION\|REPLACE.*FUNCTION' <file>
     Flag functions not following pattern as WARNING.

  4. Table conventions (ALTER/CREATE TABLE):
     Grep: grep -n 'ALTER TABLE\|CREATE TABLE' <file>
     - FK columns must have fk_ prefix
     - New tables should have is_deleted column
     Flag violations as WARNING.

  5. Sensitive data encryption variants:
     Grep: grep -n 'email\|password\|phone\|bank\|card' <file>
     If sensitive fields found with no _enc function variant: flag as WARNING.

  6. Live DB validation (psql CLI only — if psql unavailable, skip and note in WARNING):
     a. For each CREATE OR REPLACE FUNCTION: check if function exists with DIFFERENT signature:
        Bash("psql -t -A -c \"SELECT proname, pg_get_function_arguments(oid) FROM pg_proc WHERE proname = '<name>'\" 2>/dev/null")
        Different signature = BLOCKER.
     b. For each table referenced: confirm it exists:
        Bash("psql -t -A -c \"SELECT tablename FROM pg_tables WHERE tablename = '<table>'\" 2>/dev/null")
        Missing = BLOCKER.
     c. For each ADD COLUMN: confirm it doesn't already exist:
        Bash("psql -t -A -c \"SELECT column_name FROM information_schema.columns WHERE table_name = '<table>' AND column_name = '<column>'\" 2>/dev/null")
        Already exists = BLOCKER.

  Return schema only, per file (no prose):

  FILE: <path>
  BLOCKER: <issue, or "none">
  WARNING: <issue, or "none">
  """
)
```

---

## Step 2 — Perl Test Suite (conditional — after Step 1 completes)

Run **only after all Step 1 subagents have returned** and **only if Perl files were changed**.

Output to main context before spawning:
> *"Running Perl test suite..."*

```
Agent(
  description="Run Perl test suite",
  subagent_type="Explore",
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
ANTIPATTERNS="$HOME/.claude/projects/-Users-Shared-Code/memory/antipatterns.md"
DATE=$(date -u +"%Y-%m-%d")

if [ ! -f "$ANTIPATTERNS" ]; then
  printf "# Antipatterns\n\nAuto-captured BLOCK findings from /prepr runs.\n\n" > "$ANTIPATTERNS"
fi
```

For each BLOCKER, append one line:
```bash
printf -- "- [%s] %s/%s: %s — %s\n" "$DATE" "$REPO_NAME" "$CURRENT_BRANCH" "<FILE>" "<BLOCKER description>" >> "$ANTIPATTERNS"
```

This builds a rolling log that future sessions load to proactively avoid the same patterns.

---

## Step 3c — Self-Healing Warnings (only if `/prepr fix` was invoked)

Check if the user typed `/prepr fix`. If yes and WARNINGS exist:

For each WARNING, spawn a fix agent:

```
Agent(
  description="Fix warning: <issue> in <file>",
  subagent_type="general-purpose",
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
