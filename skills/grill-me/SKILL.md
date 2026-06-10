---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me". Saves output to .planning/ for /ticket to auto-load.
---

# /grill-me [TICKET-ID]

Interview me relentlessly about every aspect of this plan until
we reach a shared understanding. Walk down each branch of the design
tree resolving dependencies between decisions one by one.

If a question can be answered by exploring the codebase, explore
the codebase instead. Use MCP tools in haiku subagents — lower token cost and faster orientation.

For each question, provide your recommended answer.

Use haiku subagents for all codebase exploration to keep main context clean.

---

## Setup

Before starting the interview, run in main context:

```bash
REPO_ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  WS_ROOT="${OMG_WORKSPACE_ROOT:-/Users/Shared/Code}"
  for CANDIDATE in "$WS_ROOT/omg" "$WS_ROOT/omg_db" "$WS_ROOT/omg_ice" "$WS_ROOT/omg-docker"; do
    if git -C "$CANDIDATE" rev-parse --show-toplevel > /dev/null 2>&1; then
      REPO_ROOT=$(git -C "$CANDIDATE" rev-parse --show-toplevel); break
    fi
  done
fi
CURRENT_BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null)
echo "ROOT=$REPO_ROOT | BRANCH=$CURRENT_BRANCH"
```

**Architectural orientation** — before the first question, spawn one haiku subagent:

```
Agent(
  description="Architectural overview for grill-me: <TICKET_ID>",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <REPO_ROOT>
  MCP ONLY — grep is policy-blocked.

  STEP 1 — Get high-level architecture:
    mcp__code-review-graph__get_architecture_overview_tool(repo_root="<REPO_ROOT>")
    → communities, hub nodes, dominant flows

  STEP 2 — If the ticket mentions a specific domain/feature, find its community:
    mcp__code-review-graph__semantic_search_nodes_tool(query="<key noun from ticket title>", detail_level="minimal", repo_root="<REPO_ROOT>")
    If a node is returned:
    mcp__code-review-graph__get_community_tool(node="<node name>", repo_root="<REPO_ROOT>")
    → reveals which subsystem owns this feature and its main dependencies

  STEP 3 — Surface suggested investigation angles:
    mcp__code-review-graph__get_suggested_questions_tool(repo_root="<REPO_ROOT>")
    → use returned questions as seeds for interview branches

  Return schema only (no prose):

  ARCHITECTURE_SUMMARY: <2-3 sentences: dominant layers, major communities>
  FEATURE_COMMUNITY: <community name and key members, or "not found">
  SUGGESTED_ANGLES: <bullet list of 3-5 questions from get_suggested_questions_tool>
  """
)
```

Use ARCHITECTURE_SUMMARY to frame early questions. Use SUGGESTED_ANGLES to seed interview branches not obvious from the ticket alone.

**Ticket ID** — resolve in this order:
1. Provided as arg to /grill-me
2. Parse from CURRENT_BRANCH (e.g. `OMGXI-8616_jin` → `OMGXI-8616`)
3. Ask user: "Which ticket are we aligning on?"

Record: TICKET_ID, REPO_ROOT.

---

## Codebase Exploration Rule

When a question can be answered by exploring the codebase, spawn a haiku subagent instead of reading directly:

```
Agent(
  description="Explore: <what you're looking for>",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <REPO_ROOT>
  MCP ONLY — grep is policy-blocked. Use in order:
    1. mcp__code-review-graph__semantic_search_nodes_tool(query="<term>", detail_level="minimal", repo_root="<REPO_ROOT>")
    2. If nodes returned and you need callers/callees:
       mcp__code-review-graph__query_graph_tool(pattern="callers_of", target="<node>", detail_level="minimal", repo_root="<REPO_ROOT>")
    3. If 0 results from step 1:
       mcp__code-review-graph__traverse_graph_tool(query="<term>", mode="bfs", depth=2, repo_root="<REPO_ROOT>")
    4. If exploring which subsystem owns a component:
       mcp__code-review-graph__get_community_tool(node="<node name>", repo_root="<REPO_ROOT>")
  Return: file paths and module names only — no file contents.
  """
)
```

Use this any time the answer depends on what exists in the codebase.

---

## Auto-Save on Completion

When the interview reaches shared understanding (or user says "done", "enough", "let's go"):

1. Produce the alignment summary:

```
---
## Grill-Me Summary — <TICKET_ID>

PROBLEM: <one sentence — what's broken or missing>
DESIRED_STATE: <one sentence — what success looks like>
TECHNICAL_LAYER: <frontend | backend | database | full-stack>
KNOWN_COMPONENTS: <comma-separated file paths / module names found during exploration>
OUT_OF_SCOPE: <bullet list, or "none stated">
CONSTRAINTS: <anything technically tricky, or "none stated">
KEY_DECISIONS: <bullet list of design decisions reached during interview>
---
```

2. Save it:
```bash
mkdir -p <REPO_ROOT>/.planning
```

Write to: `<REPO_ROOT>/.planning/grill-<TICKET_ID>.md`
Content: the full summary block above.

3. Verify:
```bash
[ -f "<REPO_ROOT>/.planning/grill-<TICKET_ID>.md" ] && echo "Saved OK" || echo "ERROR: save failed"
```

4. Ask the user:
```
Alignment summary saved to .planning/grill-<TICKET_ID>.md

Proceed to ticket investigation? (yes / no)
```

5. **If yes:** output:
```
Start a fresh session and run:

  /ticket <TICKET_ID>

The grill-me summary will auto-load. Notes are saved — no need to paste anything.
```

**If no:** output:
```
Notes saved to .planning/grill-<TICKET_ID>.md

Run /ticket <TICKET_ID> whenever you're ready — the summary will auto-load.
```
