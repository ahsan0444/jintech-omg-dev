---
name: implement
description: Executes an approved investigation plan — applies code changes via subagents, maintains a change log, handles failures, and verifies all edits. Run after /ticket produces an approved plan.
---

# /implement

You are the **Implementation Orchestrator**. You take an approved plan from `/ticket` and execute every step via subagents.

**Prerequisite:** An approved plan must exist — saved to `<REPO_ROOT>/.planning/approved-plan-<TICKET_ID>.md` by a previous `/ticket` run, or present in the current session. If neither exists, stop and tell the user to run `/ticket <ticket-id>` first.

**Architecture:**
- Main context = change log + orchestration decisions only
- Subagents = workers (all file reads and edits — noise stays inside them)
- Independent steps run in parallel; dependent steps run sequentially

**Target: main context under 20k tokens after full implementation.**

---

## Ground Rules

- **Never re-investigate.** The plan is the source of truth. If something looks wrong, diagnose then fix — do not restart investigation.
- **Step 0 bash commands and the Step 3 cleanup `rm -f` are the only permitted direct Bash calls in main context.** All Read, Grep, and other Bash calls happen inside subagents only — no exceptions.
- **Never re-read.** If a subagent already returned a snippet, trust it. Do not read that file again.
- **Grep-first on every edit.** Previous steps may have shifted line numbers. Always grep for the unique string from the plan before editing.
- **Change log is the backbone.** Update it after every subagent returns, before spawning the next.
- **Parallel where safe.** Steps with `Dependencies: none` spawn in one message. Steps with dependencies wait.
- **Max 2 attempts per step.** If a step fails twice, escalate immediately — do not retry a third time.

---

## Model Usage

> **Plugin agents:** codebase/lint/psql subagents use `jintech-omg-dev:omg-investigator` (read-only, no-file-reads enforced by tool permissions); edit subagents use `jintech-omg-dev:omg-implementer` (layer rules + TDD baked in). If these agent types are unavailable (plugin agents disabled), fall back to `Explore` / `general-purpose` with the same prompts. Jira/JAM/Confluence fetches stay on `Explore` (they need Atlassian/Jam MCP tools).

| Task | Model | Subagent type |
|---|---|---|
| Implementation edits (simple/medium) | `sonnet` | `general-purpose` |
| Implementation edits (complex/architectural) | `opus` | `general-purpose` |
| Diagnosis reads, grep, file reads | `haiku` | `Explore` |
| Post-implementation review | `haiku` | `Explore` |

Default to haiku for any subagent that only reads — never pays sonnet cost for pure reads.

---

## Step 0 — Load Plan, Detect Repo, Freshness Check

Run directly in main context (the **only** permitted direct Bash call):

```bash
REPO_ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)
PLAN_FILES=$(ls "$REPO_ROOT/.planning/approved-plan-"*.md 2>/dev/null)
PLAN_COUNT=$(echo "$PLAN_FILES" | grep -c '\.md' 2>/dev/null || echo 0)
SKILL_DIR=$(ls -d ~/.claude/plugins/cache/jintech-claude-marketplace/jintech-omg-dev/*/skills/implement 2>/dev/null | sort -V | tail -1)
[ -z "$SKILL_DIR" ] && SKILL_DIR="/Users/Shared/Code/jintech-omg-dev/skills/implement"
echo "REPO=$(basename $REPO_ROOT) | PLANS=$PLAN_COUNT"
[ -n "$PLAN_FILES" ] && echo "$PLAN_FILES"
```

**Interpret output:**

- **PLANS=0:** Check if a plan exists in the current session conversation. If not, stop: *"No approved plan found. Run `/ticket <ticket-id>` first."*
- **PLANS=1:** Load the plan. Read frontmatter for context:
  ```bash
  BASE_BRANCH=$(grep "^base:" "$PLAN_FILE" | sed 's/base: //')
  TICKET_ID=$(grep "^ticket:" "$PLAN_FILE" | sed 's/ticket: //')
  REPO_ROOT_PLAN=$(grep "^repo_root:" "$PLAN_FILE" | sed 's/repo_root: //')
  ```
- **PLANS>1:** List the plan files to the user and ask which to execute. Wait for their selection.

**If REPO_ROOT is empty**, stop: *"Not inside a git repository. cd into the correct repo and re-run."*

**Freshness check** — before building the change log, verify the plan still matches the code. For each implementation step in the plan, extract the `Grep for:` string and run a quick check:

```bash
grep -rl "<unique_string>" <REPO_ROOT> --include="*.pm" --include="*.tt" --include="*.js" --include="*.sql" --include="*.scss" --include="*.css" | head -1
```

If **any grep string returns 0 results** (and it's not a new file step), surface to the user:

> *"Step N grep string not found in current code — the plan may be stale (a merge may have changed the target). Affected steps: [list]. Proceed anyway, or re-run `/ticket <TICKET_ID>` to refresh the plan?"*

Wait for their decision before continuing.

---

## Step 1 — Build Change Log and Audit Dependencies

From the loaded plan, extract all implementation steps.

**Dependency audit** — before building groups, scan all steps in main context:
- Read every step description and `Grep for:` string
- Identify any step whose grep target or replacement code references something *created* by another step (e.g. a function name that Step 1 adds and Step 3 calls)
- If found and not already marked: add `Dependencies: requires step N` to the dependent step

Build the change log:

```
CHANGE LOG:
  step 1: [file_path — description — pending]
  step 2: [file_path — description — pending]
  ...
```

Group steps:
- **Group A:** All steps with `Dependencies: none` — run in parallel
- **Group B+:** Steps that depend on earlier steps — run after their dependency completes

Active change log format (trim as work progresses — keep last 3 completed + all pending):
```
  step 1: [file — summary — ✅]   ← recent completed
  step 2: [file — summary — ✅]   ← recent completed
  step 3: [file — summary — ✅]   ← recent completed
  step 4: [file — summary — pending]
  ...
```

---

## Step 2 — Execute Steps

### For each parallel group, spawn all steps in one message:

```
Agent(
  description="Implement step N: <brief description>",
  subagent_type="jintech-omg-dev:omg-implementer",
  model="sonnet",  // use opus for complex/architectural changes
  prompt="""
  CONTEXT — steps this task depends on:
  <paste only the specific prior steps this subagent depends on — "none yet" for Group A>

  TASK: Implement the following plan step.
  File: <absolute_path>
  Change: <description from plan>
  Grep for: <unique string from plan>

  Replace with:
  <replacement from plan>

  (OMG layer rules enforced by omg-implementer agent type — not repeated here.
   Fallback to general-purpose: Read("$SKILL_DIR/references/omg-layer-rules.md") and
   insert its full contents at this position in the prompt.)

  INSTRUCTIONS:
  1. Grep for the unique string to find the exact current line number
  2. Read ±10 lines around the match to confirm the right location and understand context
  3. Apply Chesterton's Fence: if the existing code has logic you don't understand,
     read enough context to understand WHY it's there before changing it.
     Do not remove or bypass code that looks unused — investigate first.
  4. TDD — write the test BEFORE making the edit:
     a. Find the test file:
        NOTE — CRG `tests_for` pattern does NOT recognise Perl *.t files (CRG limitation).
        For Perl: use find directly:
        Bash("find <REPO_ROOT>/t -name '*.t' -exec grep -l '<module_basename>' {} \\; 2>/dev/null | head -1")
        For JS/Python: try MCP first:
        mcp__code-review-graph__query_graph_tool(pattern="tests_for", target="<module_basename>", detail_level="minimal", repo_root="<REPO_ROOT>")
        If MCP returns a path: use it. Otherwise fall back to find.
        If no test file found: note "no existing test file — skip TDD for this step" and proceed to step 5.
     b. Add a failing test case to the test file (one assert that will FAIL until the change is made)
     c. Run: Bash("cd <REPO_ROOT> && prove -l <test_file> 2>&1 | tail -15")
     d. Verify test output shows FAIL (expected RED) — if it passes already, the test is wrong, rewrite it
  5. Make the edit
  6. If TDD was possible: Run prove again — verify test now PASSES (GREEN)
     Bash("cd <REPO_ROOT> && prove -l <test_file> 2>&1 | tail -15")
  7. Read back the edited section to confirm it looks correct
  8. Check the OMG layer rules above — verify the edited file does not violate them

  Return ONLY the schema below. No prose, no preamble. The schema is the ceiling.

  STATUS: success | failed | partial
  FILE: <path>
  LINES_CHANGED: <from>-<to>
  SUMMARY: <one sentence>
  ISSUE: <describe any problem, or "none">
  """
)
```

### After each subagent returns:
1. Update the change log: `step N: [file — summary — ✅/❌/partial]`
2. `STATUS: success` → proceed to next step or group
3. `STATUS: failed` or `partial` → trigger recovery

---

## Recovery: Failed Step

**Step A — Diagnose (Haiku, Explore):**

```
Agent(
  description="Diagnose failed step N",
  subagent_type="jintech-omg-dev:omg-investigator",
  model="haiku",
  prompt="""
  Implementation step failed with: <ISSUE from failed subagent>

  1. Grep for '<unique string from plan>' in <file_path>
  2. Read ±30 lines around the first match
  3. Return what the code actually looks like at that location

  Return ONLY the schema below. No prose, no preamble. The schema is the ceiling.

  FOUND_AT_LINE: <line number or "not found">
  CURRENT_CODE: <exact code at that location, max 20 lines>
  DIAGNOSIS: <one sentence — why the edit failed>
  """
)
```

**Step B — Stall detection:**
Compare the `ISSUE` text from attempt 1 vs attempt 2. If the core error phrase is the same → **stop retrying immediately** and escalate.

**Step C — Decide:**
- **Minor divergence** (shifted lines, slight variation) → spawn a corrected implementation subagent using `CURRENT_CODE` from diagnosis as the actual starting point. Pass only this step's context, not the full change log.
- **Fundamental mismatch or stall** → surface to user:
  > *"Step N is stuck. The plan assumed:*
  > `<plan snippet>`
  > *The code actually is:*
  > `<diagnosis CURRENT_CODE>`
  > *How would you like to proceed?"*

---

## Step 2b — Layer Compliance Check (Haiku, Explore — always runs after edits complete)

Spawn one subagent to catch OMG layer violations before /prepr runs:

```
Agent(
  description="Layer compliance check — changed Perl files",
  subagent_type="jintech-omg-dev:omg-investigator",
  model="haiku",
  prompt="""
  Changed Perl files this session: <list .pm files from change log>
  Repo root: <REPO_ROOT>

  PHASE 0 — Semantic risk check (run first, 1 call):
    mcp__code-review-graph__detect_changes_tool(changed_files=["<file1>", "<file2>", ...], repo_root="<REPO_ROOT>")
    Report RISK_TIER from result. Flag any hub/bridge nodes as WARNING.
    If graph absent or tool errors: skip silently and continue to Phase 1.

  For each .pm file, run these targeted checks:

  Files in lib/*/dao/ (*_db.pm):
    Bash("grep -n 'bless\\|return.*->new' <file>")
    BLOCKER if found: dao must not return blessed objects.

  Files in lib/*/dom/ (*_dom.pm):
    Bash("grep -n 'sub TO_JSON' <file>")
    BLOCKER if missing: dom must have TO_JSON method.
    Bash("grep -n 'use Moo' <file>")
    WARNING if missing: dom objects are Moo-based (not Moose, not manual bless).

  Files in lib/*/*_helper.pm:
    Bash("grep -n '_controller->' <file>")
    BLOCKER if found: helper must not call foreign controllers.

  Files in lib/*/*_controller.pm:
    Bash("grep -n 'use.*_db;' <file>")
    WARNING if found: controller importing DAO directly.

  All .pm files NOT in lib/*/dao/:
    Bash("grep -n 'database->' <file>")
    BLOCKER if found: DB access belongs only in the dao layer.

  All .pm files:
    Bash("perl -c <file> 2>&1")
    BLOCKER if compile error.

  Return ONLY the schema below. No prose, no preamble.

  RISK_TIER: high | medium | low | unknown
  BLOCKERS: <file:line — issue, or "none">
  WARNINGS: <file:line — issue, or "none">
  """
)
```

If BLOCKERS found: surface them in Step 3 report under "Layer Violations — fix before /prepr".
If RISK_TIER is high: surface in Step 3 report under "Semantic Risk — review before /prepr".
If clean: log "Layer check: clean" — do not echo in report.

Skip this step if no .pm files were changed.

---

## Step 2c — Spec Generation (Sonnet, general-purpose — runs after Step 2b when UI changed)

**Trigger:** Run this step only when the change includes `.tt`, `.css`, or `.js` files, OR a route file (`OMG*.pm`) that feeds a UI route. Skip entirely for backend-only changes.

**Purpose:** Ensure `/verify` has a runnable Playwright spec before the session ends. A spec written now (with full plan context) is far cheaper than one authored cold in a verify session.

**Feature slug:** derive from the ticket ID + plan description. Use kebab-case. Examples:
- OMGXI-10073 "deliverable chooser" → `jobs-deliverable-chooser`
- OMGXI-10112 "apply template modal" → `apply-deliverable-template-modal`

**Skip condition:** If `~/.agent-os/omg/specs/<feature-slug>.spec.mjs` already exists AND the changed files are all in the same area as the existing spec (no new UI surface), log "Spec exists — skipped" and proceed to Step 3.

Before building the subagent prompt: `Read("$SKILL_DIR/references/playwright-spec-template.md")` and replace `<SPEC_TEMPLATE>` in the prompt below with the full file contents.

Spawn:

```
Agent(
  description="Generate Playwright spec for <feature-slug>",
  subagent_type="general-purpose",
  model="sonnet",
  prompt="""
  Write a Playwright Tier-2 spec for the feature just implemented.

  TICKET: <TICKET_ID>
  FEATURE SLUG: <feature-slug>   (kebab-case, e.g. "jobs-deliverable-chooser")
  REPO ROOT: <REPO_ROOT>
  DATA DIR: ~/.agent-os/omg

  ACCEPTANCE CRITERIA (from the approved plan):
  <paste the Definition of Done checklist from the plan>

  CHANGED UI FILES:
  <list .tt / .js / .scss files from the change log>

  CHANGED ROUTES (from the plan, or grep `OMG*.pm` changes):
  <list affected URL patterns e.g. /campaigns/:id/jobs>

  ── SPEC REQUIREMENTS ──

  <SPEC_TEMPLATE>

  Return ONLY the schema below. No prose, no preamble.

  STATUS: written | skipped | failed
  SPEC_PATH: <absolute path written, or "none">
  REGISTRY_PATH: <absolute path written, or "none">
  ASSERTIONS_COUNT: <number of expect() calls in the spec>
  ISSUE: <problem if failed, else "none">
  """
)
```

After subagent returns:
- `STATUS: written` → log "Spec generated: `<SPEC_PATH>`" in the Step 3 report. Spec is ready for `/verify`.
- `STATUS: skipped` → log "Spec exists — skipped".
- `STATUS: failed` → log "Spec generation failed: `<ISSUE>`" as a WARNING in Step 3 report. Does NOT block /prepr.

---

## Step 3 — Report

Once all steps complete:

```
## Implementation Complete

Changes applied: <N>/<N> steps

CHANGE LOG:
  step 1: <file> — <summary> — ✅
  step 2: <file> — <summary> — ✅
  ...

Layer Compliance: <clean | N blockers — list them>
TDD: <N steps had tests written | skipped — no test files found>

Definition of Done:
  <paste checklist from the approved plan>
```

Clean up the handoff file:
```bash
rm -f <REPO_ROOT>/.planning/approved-plan-<TICKET_ID>.md
```

---

```
---
# Next Up

Run /prepr to check for blockers, then /pr to raise the PR.

Also available:
  - /ticket <ticket-id> — start a new ticket

Done — start a fresh session for the next phase.
---
```
