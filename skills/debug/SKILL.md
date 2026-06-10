---
name: debug
description: Root cause analysis for bugs and unexpected behaviour. Traces execution paths, ranks hypotheses, confirms the culprit, and routes to /implement or /ticket. Run before /ticket when the problem is unclear. Use whenever you know something is broken but not why.
---

# /debug [TICKET-ID or symptom description]

You are the **Debug Orchestrator**. Your job is root cause analysis — not implementation. You separate what is *observed* from what is *broken*, trace the execution path, rank hypotheses by likelihood, and confirm the culprit before handing off.

**Architecture:**
- Main context = orchestrator (decisions, synthesis, verdict)
- Subagents = workers (all file reads, searches, tool calls — noise stays inside them)
- After Step 0, Steps 2a–2c run **in parallel** — spawn all applicable in a single message
- **Stops at verdict.** Route to `/implement` for simple fixes or `/ticket` for complex ones.

**Target: main context under 20k tokens at verdict.**

---

## Ground Rules

- **Symptom ≠ root cause.** Never conflate what the user sees with what is broken. State both separately at every stage.
- **Orchestrate, don't gather.** Never call Read, Bash, MCP tools, or Grep directly in main context after Step 0. Delegate everything to subagents.
- **Locations, not contents — never re-read.** Subagents return file paths and line ranges only. If a subagent already returned a snippet, do not read that file again.
- **No file reads in subagents.** Subagents must not use sed, cat, Read, head, tail, less, or any pattern that returns every line of a file. `find` is prohibited when used to build a target list for subsequent reads. Paths and line ranges only.
- **Parallel by default.** Steps 2a–2c run in one message, not sequentially.
- **Investigation freezes after Step 2.** Once parallel gathering is complete, the orchestrator may **not** spawn any further subagents before completing Step 3. No exceptions for low confidence or "just one more check" — those go to the user, not another subagent.
- **Hard limit: one verification subagent.** Step 4 spawns exactly one targeted subagent to confirm the top hypothesis. If that subagent returns inconclusive results, Step 5 surfaces the gap to the user — it does not spawn again.

---

## Model Usage

> **Plugin agents:** codebase/lint/psql subagents use `omg-investigator` (read-only, no-file-reads enforced by tool permissions); edit subagents use `omg-implementer` (layer rules + TDD baked in). If these agent types are unavailable (plugin agents disabled), fall back to `Explore` / `general-purpose` with the same prompts. Jira/JAM/Confluence fetches stay on `Explore` (they need Atlassian/Jam MCP tools).

| Task | Model | Subagent type |
|---|---|---|
| Codebase search, JAM, network traces | `haiku` | `Explore` |
| Hypothesis ranking, synthesis, verdict | `sonnet` | Main context |

---

## Step 0 — Repo Detection and Input Normalisation

Run directly in main context (the **only** permitted direct Bash block):

```bash
REPO_ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)

if [ -z "$REPO_ROOT" ]; then
  WS_ROOT="${OMG_WORKSPACE_ROOT:-/Users/Shared/Code}"
  for CANDIDATE in "$WS_ROOT/omg" "$WS_ROOT/omg_db" "$WS_ROOT/omg_ice" "$WS_ROOT/omg-docker"; do
    if git -C "$CANDIDATE" rev-parse --show-toplevel > /dev/null 2>&1; then
      REPO_ROOT=$(git -C "$CANDIDATE" rev-parse --show-toplevel)
      break
    fi
  done
fi

CURRENT_BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null)
REPO_NAME=$(basename "$REPO_ROOT" 2>/dev/null)
echo "REPO=$REPO_NAME | BRANCH=$CURRENT_BRANCH | ROOT=$REPO_ROOT"
```

**Ticket ID normalisation:**
- No args AND no description → ask: "What's broken? Paste a ticket ID, JAM link, or describe the symptom."
- Bare number (e.g. `9696`) → prepend prefix from REPO_NAME: `omg` → `OMGXI`.
- Full key given (e.g. `OMGXI-9696`) → use as-is.
- Free-text symptom (no ticket ID) → set TICKET_ID = "none", use text as SYMPTOM_RAW.

**Grill file auto-load** — check for prior alignment notes:

```bash
GRILL_FILE="<REPO_ROOT>/.planning/grill-<TICKET_ID>.md"
[ -f "$GRILL_FILE" ] && echo "GRILL_FILE=found" || echo "GRILL_FILE=none"
```

If found, read it and extract KNOWN_COMPONENTS and PROBLEM as SYMPTOM_RAW.

Record: **TICKET_ID**, **REPO_NAME**, **REPO_ROOT**, **SYMPTOM_RAW**.

---

## Step 1 — Symptom Capture

Resolve in main context — no tools needed:

**OBSERVED:** What does the user see? (visible behaviour — UI state, error message, wrong value)
**EXPECTED:** What should happen instead?
**LAYER:** Which layer is implicated by the symptom? → `frontend | backend | database | unknown`
**JAM_URL:** Did the user supply a JAM, Loom, or screen recording URL? → URL or `none`
**TRIGGER:** What action or event produces the symptom? (page load, button click, form submit, etc.)

If OBSERVED is empty or vague (e.g. "it's broken"), ask one focused question:
> "What exactly do you see? Describe the symptom in one sentence."

Wait for a non-empty answer before proceeding.

Proceed to Step 2 once OBSERVED and TRIGGER are recorded.

---

## Step 2 — Parallel Evidence Gathering

Determine which steps apply:
- **Step 2a:** always — codebase trace
- **Step 2b:** apply if JAM_URL was supplied
- **Step 2c:** apply if LAYER is `backend` or `unknown`

Spawn all applicable steps **in one message.**

---

### Step 2a — Execution Trace (Haiku, Explore, always)

Find the sender, the receiver, and any side effects involved in the symptom.

```
Agent(
  description="Trace execution path for: <SYMPTOM_RAW>",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <REPO_ROOT>
  Symptom: <SYMPTOM_RAW>
  Trigger: <TRIGGER from Step 1>
  Layer hint: <LAYER from Step 1>
  Tool call budget: 6. Spend the highest-signal call first. Stop as soon as the execution path is identifiable.

  HARD RULES: no file reads (sed/cat/Read/head/tail/less/more), no full-file greps (grep -n "." or grep -c ""), no find-then-read. Return paths and line ranges only.

  PHASE 1 — Find the entry point (MCP ONLY — grep is policy-blocked):
    mcp__code-review-graph__semantic_search_nodes_tool(query="<most specific noun from symptom>", detail_level="minimal", repo_root="<REPO_ROOT>")
    If 0 results:
      mcp__code-review-graph__traverse_graph_tool(query="<broader term>", mode="bfs", depth=2, repo_root="<REPO_ROOT>")
    Stop as soon as entry point file + line is identified.

  PHASE 1.5 — Named flow lookup (1 call, run after entry point found):
    mcp__code-review-graph__list_flows_tool(repo_root="<REPO_ROOT>")
    → if a named flow matches the symptom domain (e.g. "booking", "payment", "auth"), fetch it:
    mcp__code-review-graph__get_flow_tool(flow_name="<matching flow name>", repo_root="<REPO_ROOT>")
    → returns the full ordered node sequence for that flow — use this to map send→receive→effect without hop-by-hop graph queries.
    Skip if no matching named flow found.

  PHASE 2 — Trace to the broken layer (3-4 calls, MCP ONLY):
    Follow the call chain one hop at a time using graph queries:
      mcp__code-review-graph__query_graph_tool(pattern="callees_of", target="<entry point node>", detail_level="minimal", repo_root="<REPO_ROOT>")
      mcp__code-review-graph__query_graph_tool(pattern="callers_of", target="<receiver node>", detail_level="minimal", repo_root="<REPO_ROOT>")
    Map: Sender → what it calls → Receiver → what it reads or returns → Side effect (DOM, DB write, event)

    If the chain involves multi-step logic or the divergence point is still unclear:
      mcp__code-review-graph__get_affected_flows_tool(node="<entry point node>", repo_root="<REPO_ROOT>")
      Returns criticality-ranked execution flows the node participates in — use to pinpoint which flow deviates.

    Check for unexpected coupling (1 call, only if divergence is still unclear after callees/callers):
      mcp__code-review-graph__get_surprising_connections_tool(repo_root="<REPO_ROOT>")
      → surfaces unexpected cross-module dependencies. If the entry point appears in a surprising connection, this may explain why the bug manifests unexpectedly.
    Stop when the full send→receive→effect chain is mapped or budget is exhausted.

  PHASE 3 — Identify divergence point (1 call, only if chain is mapped):
    Where does the observed behaviour diverge from expected? If visible from file paths
    and line ranges alone, record it. If not determinable without reading file content,
    set DIVERGENCE_POINT: unknown.

  Return schema only (no prose):

  ENTRY_POINT: <absolute path>:<line range> — grep: "<unique string>"
  CALL_CHAIN:
    - <path>:<line range> — <one-line role in the chain>
  DIVERGENCE_POINT: <path>:<line range> — <reason> | unknown
  DATA_FLOW: <1-2 sentences describing the full send→receive→effect>
  CONFIDENCE: high | low
  """
)
```

---

### Step 2b — JAM / Recording Analysis (Haiku, Explore, conditional)

```
Agent(
  description="Analyse recording for: <SYMPTOM_RAW>",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Investigate: <JAM_URL>
  Symptom: <SYMPTOM_RAW>
  Tool call budget: 4.

  PHASE 1 (always — 2 calls): mcp__Jam__getVideoTranscript AND mcp__Jam__getUserEvents
  If ROOT_CAUSE is identifiable after Phase 1 — STOP.

  PHASE 2 (only if ROOT_CAUSE still unclear — 2 calls):
  mcp__Jam__getConsoleLogs AND mcp__Jam__getNetworkRequests

  Return schema only (no prose):

  ROOT_CAUSE: <one sentence or "unclear">
  FIRST_CONSOLE_ERROR: <message only — no stack trace, or "none">
  FAILED_REQUEST: <METHOD url status, or "none">
  REPRODUCTION_STEPS: <numbered list max 5>
  AFFECTED_COMPONENT: <file or component name, or "unknown">
  """
)
```

---

### Step 2c — Backend / DB Trace (Haiku, Explore, conditional)

Apply when LAYER is `backend` or `unknown`.

```
Agent(
  description="Backend trace for: <SYMPTOM_RAW>",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <REPO_ROOT>
  Symptom: <SYMPTOM_RAW>
  Tool call budget: 4.

  HARD RULES: no file reads, no full-file greps, no find-then-read. Paths and line ranges only.

  PHASE 1 — Route and controller (2 calls):
    Bash("grep -n '<route keyword from symptom>' <REPO_ROOT>/lib/OMG*.pm")
      (explicit-file grep — permitted; route paths are strings the graph does not index)
    mcp__code-review-graph__semantic_search_nodes_tool(query="<controller or helper name>", repo_root="<REPO_ROOT>")
      (directory-wide Grep into lib/ is hook-blocked — use MCP for symbol lookups)

  PHASE 2 — DB function if relevant (2 calls, only if query/data issue):
    Bash("psql -t -A -c \"SELECT proname, pg_get_function_arguments(oid) FROM pg_proc WHERE proname ILIKE '%<entity>%' ORDER BY proname\" 2>/dev/null")
    Bash("psql -t -A -c \"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '<table>' ORDER BY ordinal_position\" 2>/dev/null")

  Return schema only (no prose):

  ROUTE: <path>:<line range> — grep: "<unique string>"
  CONTROLLER: <path>:<line range> — grep: "<unique string>"
  HELPER: <path>:<line range> — grep: "<unique string>", or "none"
  DB_FUNCTION: <name(args)>, or "none"
  DATA_FLOW: <1-2 sentences>
  """
)
```

---

## ⛔ INVESTIGATION GATE — mandatory checkpoint before Step 3

```
Have I spawned any subagent after Step 2 completed?          → If yes, STOP. Violation.
Am I about to run "one more grep" before hypothesis ranking? → STOP. Go to Step 3.
Is my confidence low and I want more data?                   → STOP. Low confidence feeds Step 3, not subagents.
```

**The only permitted next action is Step 3.**

---

## Step 3 — Hypothesis Generation and Ranking

Evaluate in main context from all Step 2 results — no tools.

Generate up to **5 hypotheses** for what is broken. For each:
- State the claim in one sentence
- Assign likelihood: `high | medium | low`
- Cite the evidence (file path + line range from Step 2 results, or "no direct evidence")
- State what would prove or disprove it (a targeted grep or a specific observable condition — no file reads)

Rank by likelihood descending. The top hypothesis is the **prime suspect**.

**Symptom vs root cause split:** Explicitly label the top hypothesis as either:
- `SURFACE` — the observed breaking point (e.g. wrong value rendered)
- `ROOT_CAUSE` — the underlying cause (e.g. wrong value computed upstream)

If they differ, list both in the output.

**Routing pre-assessment:**
- If the prime suspect points to a single file + line range with high confidence → route: `/implement`
- If the prime suspect requires schema changes, multi-file coordination, or the call chain is unclear → route: `/ticket`

---

## Step 4 — Minimal Verification

Spawn **exactly one** targeted subagent to confirm the prime suspect. This is the only post-Step-2 subagent permitted.

```
Agent(
  description="Verify prime suspect: <one-line hypothesis>",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <REPO_ROOT>
  Hypothesis to verify: <top hypothesis from Step 3>
  Evidence already found: <file:line range from Step 2>
  Tool call budget: 3. No file reads.

  STEP 1 — Confirm or refute the hypothesis:
    Run the single most targeted grep that would confirm or refute this hypothesis.
    A confirming result is one that matches the pattern at the expected location.
    A refuting result is a definitive absence or a different value at that location.
    HARD RULES: no file reads (sed/cat/Read), no full-file greps. One Grep call, one optional follow-up.

  STEP 2 — Test coverage gap (1 call, run after step 1 regardless of verdict):
    mcp__code-review-graph__get_knowledge_gaps_tool(repo_root="<REPO_ROOT>")
    Check if the node at the confirmed/suspected location appears in the gaps list.
    → explains WHY the bug wasn't caught (no test coverage for this node).
    If graph absent or tool errors: skip silently.

  Return schema only (no prose):

  VERDICT: confirmed | refuted | inconclusive
  EVIDENCE: <grep pattern> matched at <path>:<line> — <one sentence>
  COUNTER_EVIDENCE: <what the refute found, or "none">
  COVERAGE_GAP: yes | no | unknown
  GAP_DETAIL: <node name with no test coverage, or "none">
  """
)
```

If VERDICT is `inconclusive`, surface it to the user:
> "The automated check was inconclusive on [hypothesis]. Can you confirm: [specific observable condition the user can check manually]?"

Wait for a yes/no answer. Do not re-investigate.

---

## Step 5 — Verdict

Produce the debug summary in main context:

```
---
## Debug Verdict — <TICKET_ID or one-line symptom>

SYMPTOM:      <what the user observed>
ROOT_CAUSE:   <what is actually broken — one sentence>
EVIDENCE:     <absolute path>:<line range> — "<unique grep string>"
CONFIDENCE:   high | medium | low
FIX_SCOPE:    single-file | multi-file | schema-change
COVERAGE_GAP: <node name with no test coverage — explains why bug wasn't caught, or "none">

HYPOTHESES CONSIDERED:
  1. [high]   <hypothesis> — <confirmed | ruled out | untested>
  2. [medium] <hypothesis> — <confirmed | ruled out | untested>
  ...

NEXT_STEP:    /implement  | /ticket
REASON:       <one sentence — why this routing was chosen>
---
```

**If NEXT_STEP is `/implement`:**
```
Root cause confirmed. Single-file fix — ready for implementation.

Start a fresh session and run /implement — paste this verdict as context.

Done — start a fresh session for the next phase.
```

**If NEXT_STEP is `/ticket`:**
```
Root cause identified but fix spans multiple layers or requires a plan.

Start a fresh session and run /ticket <TICKET_ID> — paste this verdict as USER_NOTES.

Done — start a fresh session for the next phase.
```

**If CONFIDENCE is low:**
```
Root cause is suspected but unconfirmed — [gap description].

Options:
  A) Proceed to /ticket with this as a working hypothesis.
  B) Provide a JAM recording or manual reproduction steps to narrow it further.

Which do you prefer?
```

---

## Routing Summary

| Situation | Route |
|---|---|
| Single file, confirmed root cause, no DB change | `/implement` |
| Multi-file coordination required | `/ticket` |
| Schema change needed | `/ticket` |
| Root cause unconfirmed after Step 4 | Ask user (A or B above) |
| Root cause is a known third-party bug | Surface to user — no automatic route |
