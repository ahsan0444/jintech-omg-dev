# /ticket — Conditional Subagent Templates

Loaded on demand by SKILL.md. Each § is a complete Agent() template — use verbatim, filling `<placeholders>` from Step 0/1 context.

---

# § Step 2a — Specs (Confluence) + Step 2b — Bug Context (JAM)

### Step 2a — Specs (Haiku, Explore, conditional)

```
Agent(
  description="Fetch Confluence specs for <TICKET_ID>",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  TOOL DISCOVERY: Atlassian MCP tool names vary by install (mcp__plugin_atlassian_atlassian__*, mcp__claude_ai_Atlassian__*, or mcp__atlassian__*). If a call fails with unknown tool, run ToolSearch(query="+jira <tool name>") and use the returned variant. Names below use the mcp__plugin_atlassian_atlassian__ prefix.

  Call mcp__plugin_atlassian_atlassian__getConfluencePage for: <CONFLUENCE_URL>
  Extract only: requirements, constraints, data contracts, technical decisions.
  If unavailable return: CONFLUENCE_REQUIREMENTS: unavailable

  Return schema only (no prose):

  CONFLUENCE_REQUIREMENTS: <bullet list or "unavailable">
  CONFLUENCE_CONSTRAINTS: <bullet list or "none">
  """
)
```

**Discard rule:** If CONFLUENCE_REQUIREMENTS is "unavailable", drop this result entirely — do not include in synthesis.

---

### Step 2b — Bug Context / JAM (Haiku, Explore, conditional)

> **Note:** This step is lower priority than 2c. If the user denies this agent or it times out, treat the result as if JAM_URL was not found and skip this step's output during synthesis. Do not retry.

```
Agent(
  description="Fetch JAM context for <TICKET_ID>",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Investigate JAM session: <JAM_URL>

  Tool call budget: 4 (one per JAM tool). Stop at the earliest phase where ROOT_CAUSE is identifiable.

  PHASE 1 (always — counts as 2 calls): mcp__Jam__getVideoTranscript AND mcp__Jam__getUserEvents.
  If ROOT_CAUSE is identifiable after Phase 1 — STOP. Do not run Phase 2.

  PHASE 2 (ONLY if ROOT_CAUSE is still "unclear" after Phase 1 — counts as 2 calls):
  mcp__Jam__getConsoleLogs AND mcp__Jam__getNetworkRequests.

  PHASE 3 (only if visual state is directly required to identify AFFECTED_COMPONENT — counts as 1 call,
  only run if budget permits and phases 1-2 left AFFECTED_COMPONENT unknown):
  mcp__Jam__getScreenshots.

  Return schema only (no prose):

  ROOT_CAUSE: <one sentence or "unclear">
  REPRODUCTION_STEPS: <numbered list max 5>
  FIRST_CONSOLE_ERROR: <message only — no stack trace, or "none">
  FAILED_REQUEST: <METHOD url status, or "none">
  AFFECTED_COMPONENT: <file or component name, or "unknown">
  """
)
```

**Discard rule:** If ROOT_CAUSE is "unclear" and all remaining fields are "none" or "unknown", drop this result — do not include in synthesis.

---


---

# § Step 2c retry — broader terms

**If CONFIDENCE=low or AFFECTED_FILES is empty**, spawn one retry:

```
Agent(
  description="Retry codebase query — broader terms",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <REPO_ROOT>
  Ticket context: <SUMMARY from Step 1>
  User notes: <any additional context supplied by the user at invocation>
  Previous queries returned no clear files. Tool call budget: 3.

  HARD RULES: no file reads (sed/cat/Read/head/tail/less/more), no full-file greps (grep -n "." / grep -c ""), no find-then-read. Paths and line ranges only.

  MCP ONLY — grep is policy-blocked.
  mcp__code-review-graph__traverse_graph_tool(query="<broader keyword>", mode="bfs", depth=3, repo_root="<REPO_ROOT>")
  mcp__code-review-graph__semantic_search_nodes_tool(query="<alternative term>", detail_level="minimal", repo_root="<REPO_ROOT>")

  **Exception — "absent by design":** If MCP searches return 0 results AND the ticket clearly describes adding something new (a new header, config value, route, or import that does not yet exist), that is a CONFIDENCE: high finding. Set CONFIDENCE: high and record the insertion point explicitly:
    - AFFECTED_FILES: <most logical insertion point based on DATA_FLOW> — grep: "(not present — new addition required)" — <reason this is the right location>

  Return schema only (no prose):

  CONFIDENCE: high | low
  AFFECTED_FILES:
    - <absolute path>:<line range> — grep: "<unique string>" — <one-line reason>
  DATA_FLOW: <1-2 sentences>
  RISKS: <one line, or "none">
  """
)
```


---

# § Step 2c-db — DB Companion query

### Step 2c-db — Codebase Query, DB Companion (Haiku, Explore, conditional)

Runs in parallel with Step 2c. Spawn only if DB_COMPANION is set.

```
Agent(
  description="Query DB companion for <TICKET_ID>",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Working directory: <DB_COMPANION>
  Ticket context: <SUMMARY from Step 1>
  Tool call budget: 2. Stop after grep if files are found.

  HARD RULES: no file reads (sed/cat/Read/head/tail/less/more), no full-file greps (grep -n "." / grep -c ""), no find-then-read. Paths and line ranges only.

  PHASE 1 — Find relevant SQL scripts:
    Grep(pattern="<entity or function name from ticket>", path="<DB_COMPANION>/dbscripts", glob="*.sql")

  PHASE 2 — Existing DB functions:
    Bash("psql -t -A -c \"SELECT proname, pg_get_function_arguments(oid) as args FROM pg_proc WHERE proname ILIKE '%<entity_from_summary>%' ORDER BY proname\" 2>/dev/null")

  Return schema only (no prose):

  AFFECTED_FILES:
    - <absolute path>:<line range or "new file"> — <one-line reason>
  EXISTING_FUNCTIONS: <name(args) list, or "none">
  RISKS: <one line, or "none">
  """
)
```

---
