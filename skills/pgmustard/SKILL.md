---
name: pgmustard
description: Run a real pgMustard query-plan review against DB function(s) added/modified in the current branch's dbscripts, using the pgMustard save/score API when a token is available (falls back to local EXPLAIN emulation otherwise), producing a plain-English review with a 0-5 tip score.
argument-hint: [optional: path to a specific dbscripts deploy .sql file]
disable-model-invocation: false
---

# pgMustard Skill

Runs the real pgMustard analysis via their save/score API (confirmed working — see "API reference"
below), falling back to a local `EXPLAIN (ANALYZE, BUFFERS)` emulation only when no API token is
configured. Either way: find the DB function(s) changed on the current branch, run a real
`EXPLAIN` against the podman Postgres server, submit it, and produce the same style of
plain-English review pgMustard's UI gives, ending with a 0.0-5.0 score.

**Never hardcode the API token in this file, in any output, or in any git-committed artifact.**
Read it from the `PGMUSTARD_API_KEY` environment variable (or Claude settings `env` block) at
run time. If it's missing, say so and fall back to local emulation — do not ask the user to paste
it into chat, and if a token does appear in a chat message, treat it as compromised: tell the user
to rotate it (Account page → API tokens) before using it.

---

## Step 0 — Check for an API token

```bash
echo "${PGMUSTARD_API_KEY:+present}"
```

- **Present** → use the real API (Steps 1-4 below use it).
- **Absent** → fall back to local emulation only: run `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)`
  against the podman DB and build the review table directly from that output, using the same
  output format in Step 5. Skip Steps "Submit to pgMustard" below entirely in that case.

## Step 1 — Find the target deploy script(s)

If the user passed a file path as an argument, use that file directly.

Otherwise, find deploy scripts added/modified on the current branch — **always diff against the
branch's actual parent (the sprint branch it was created from), never against `master`**:

```bash
git show-branch -a 2>/dev/null | grep '\*' | grep -v "$(git rev-parse --abbrev-ref HEAD)" | head -n1 | awk -F'[][~^]' '{print $2}'
```

Then diff against that parent branch:

```bash
git diff --name-only --diff-filter=ACMR <parent_branch>...HEAD -- 'dbscripts/*/deploy/*.sql'
```

- If none found, also check unstaged/staged changes: `git status --porcelain -- 'dbscripts/*/deploy/*.sql'`
- If multiple scripts are found, list them and ask the user which one(s) to analyze (or process all, if the user says so).
- If none found at all, tell the user no deploy scripts were changed on this branch and stop.

## Step 2 — Extract the function definition

Read the deploy script. Per `dbscripts/CLAUDE.md`, function deploy scripts follow the pattern:
`DROP FUNCTION IF EXISTS ...` followed by `CREATE OR REPLACE FUNCTION <schema>.<name>(<params>) RETURNS ...`.

Extract:
- Fully-qualified function name (e.g. `public.planning_media_schedules_get`)
- Ordered parameter list with types (ignore `OUT`/`RETURNS TABLE` columns — only `IN` params matter for the call)
- Any `DEFAULT` values on params (these can be omitted from the call)

## Step 3 — Find real-time argument values

Do not call the function with placeholder/fake values — pgMustard-style review requires a
realistic plan. Inspect the function body's `WHERE` clause to infer which underlying
table/columns each parameter filters on, then query the podman DB for a value combination that
yields a reasonable number of matching rows (prefer a case with the most matches among the top
few, not the single largest, to keep the query representative rather than a worst-case outlier):

```bash
podman exec -e PGPASSWORD=pgdev postgres_db psql -U pgdev -d OMG -c "<exploratory SELECT ... GROUP BY ... ORDER BY count(*) DESC LIMIT 5;>"
```

Pick one row of resulting values to use as the real-time call arguments.

**Prefer the actual SQL body inlined (not just `SELECT * FROM function(...)`) when the function is
`plpgsql`** — a raw function call collapses to one opaque `Function Scan` node in `EXPLAIN`, hiding
every join/scan inside it (see "black-box limitation" below). Inlining the `RETURN QUERY` body's
`SELECT` directly (substituting real literal argument values, and casting `string_to_array(...)`
results to the correct array type Postgres expects) exposes the real plan. Get the JSON form for
the API submission:

```bash
podman exec -e PGPASSWORD=pgdev postgres_db psql -U pgdev -d OMG -c "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <inlined SELECT with real literal values>;"
```

If inlining isn't practical (e.g. deeply nested calls, dynamic SQL), fall back to the direct
function call and note the black-box limitation explicitly in the review.

## Step 4 — Submit to pgMustard (when a token is available)

### API reference (confirmed working — see `https://www.pgmustard.com/docs/save-endpoint` and
`/docs/score-endpoint` for the canonical docs if these ever drift)

**Save endpoint** — persists the plan and returns a shareable explore URL:
```
POST https://app.pgmustard.com/api/v1/save
Authorization: Bearer $PGMUSTARD_API_KEY
Content-Type: application/json
Accept: application/json

{
  "plan": <EXPLAIN ANALYZE, BUFFERS, FORMAT JSON output — the array under "QUERY PLAN">,
  "name": "<TICKET-ID> <function name>",
  "access_level": "private",
  "query_text": "<the SQL that was run>"
}
```
Response: `{"id", "explore_url", "duration_ms", "top_tip_score", "buffers_kb"}`.
Default `access_level` to `"private"` unless the user explicitly asks for `"team"` or `"published"`
— this schema/query data shouldn't go public by default.

**Score endpoint** — returns the actual tips/findings (zero to three, prioritized):
```
POST https://app.pgmustard.com/api/v1/score
Authorization: Bearer $PGMUSTARD_API_KEY
Content-Type: application/json
Accept: application/json

{ "plan": <same JSON plan array> }
```
Response: `{"best-tips": [{"tip-category", "tip-title", "score", "tip-explanation": [...], "learn-more-links": [...]}], "query-time", "query-blocks"}`.
**Tip scores are 0-5, higher = more optimization potential (i.e. higher score = worse/more actionable).**
This is the OPPOSITE direction from the skill's own overall 0-5 "rating" in Step 5, which is
5=best — don't conflate the two when writing the summary.

Call both endpoints (save first, for the shareable link; then score, for the actual findings) with
the same `plan` payload. A subscription tier or credit limit may reject the call (e.g. 402/403) —
if so, say so plainly and fall back to local emulation instead of retrying blindly.

## Step 5 — Output format

Present the results in this exact order:

### 1. Query run

Show the exact `EXPLAIN (ANALYZE, BUFFERS)` command/query that was executed (the inlined
version if used), in a code block, so the user can rerun it themselves. If the real API was used,
include the `explore_url` from the save-endpoint response here too.

### 2. Raw query plan table

Turn the plan nodes into a table:

| Node | Type | Est. Rows | Actual Rows | Est/Actual Ratio | Width | Loops | Actual Time (ms) | Shared Hit | Shared Read |
|---|---|---|---|---|---|---|---|---|---|

One row per plan node (indent nested nodes with `↳` in the Node column to preserve tree shape).
`Width` is the planner's estimated average row size in bytes for that node (from `width=N` in
the plan output).

### 3. pgMustard-style review table

**This table is mandatory in every run.** If the real API was called, source this directly from
the score-endpoint's `best-tips` (map each tip's `tip-category`/`tip-title` into "Category",
`tip-explanation` joined into "Findings", `score` bucketed into 🔴/🟡/🟢 severity per the scale
below, and `learn-more-links` folded into "Tips"). If falling back to local emulation, build it
manually — even a single opaque `Function Scan` node still has findings worth reporting (planner
row-estimate default vs actual, buffer hit/read split, the black-box limitation itself).

Severity bucketing from a tip `score` (0-5, higher = worse): score ≥ 3.5 → 🔴 High;
1.5-3.5 → 🟡 Medium; < 1.5 → 🟢 Low.

Use exactly these four columns, in this order and with these exact headers:

| Category | Findings | Severity | Tips |
|---|---|---|---|

Cover, where applicable:
- Row estimate mismatches (stale stats / bad selectivity)
- Buffer/IO split (cache hit vs disk read → CPU-bound vs IO-bound)
- Risky node types (Seq Scan on large tables, disk-spilling Sort/Hash, Nested Loop over large
  row counts, missing index opportunities — especially on JSONB `->>` operators which can't use
  a plain btree index)
- The opaque/black-box limitation, when the plan (or part of it) is a bare Function Scan

Omit a row only if it is genuinely not applicable (e.g. no Seq Scan appears anywhere) — do not
invent findings, but do not drop the table structure either.

### 4. Rating

Present as a two-column table, not prose. **This is the skill's own overall rating, 0-5 where
5=best — separate from pgMustard's raw tip scores, which run the other direction (see Step 4).**

| Rating | Suggestions |
|---|---|
| ⭐⭐⭐☆☆ (X.X / 5.0) | One or more concrete, actionable suggestions tied to the findings above (or "No changes needed" if 5.0). |

Render the star count by rounding X.X to the nearest half-star out of 5.

Scoring guide:
- 5.0 — no row-estimate mismatches, all buffers cache hits, no risky node types, fast execution.
- 3.5-4.5 — minor row-estimate drift or a modest disk-read share, no red flags.
- 2.0-3.5 — one clear yellow-flag issue (e.g. moderate estimate mismatch, some disk reads,
  JSONB filter without index) but overall functional.
- 0-2.0 — a red-flag issue present (seq scan on a large table, disk-spilling sort/hash, large
  nested loop, very high buffer touches per row).

### 5. Next step prompt

End by asking whether the user wants the plan/feedback discussed further, wants you to propose
an index/rewrite fix for any flagged issue, or wants the `explore_url` posted to the PR description
(if it wasn't already, per the calling context — e.g. `/pr` or a PR-comment-resolution pass).

---

## Worked example (real API, verified)

A repeat-booking date-range query (`time_for_users_in_agencies_jobs_by_date_range_get`, OMGXI-10175)
inlined and run via `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, submitted to both endpoints:

```bash
curl -X POST https://app.pgmustard.com/api/v1/save \
  -H "Authorization: Bearer $PGMUSTARD_API_KEY" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"plan": [...], "name": "OMGXI-10175 jobs_by_date_range_get", "access_level": "private"}'
# => {"id":"...", "explore_url":"https://app.pgmustard.com/#/explore/...", "top_tip_score":2.26, "buffers_kb":320320}

curl -X POST https://app.pgmustard.com/api/v1/score \
  -H "Authorization: Bearer $PGMUSTARD_API_KEY" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"plan": [...]}'
# => best-tips: "Row Estimate: out by a factor of 72" (score 2.26) — a nested loop where the planner
#    estimated 1 row/iteration but got 72, three times over in the plan (repeated at different join
#    levels). Matches Postgres's flat per-iteration default for correlated subplans; not fixable via
#    ANALYZE here since it's inherent to how the planner costs a nested loop against a CTE.
```

This confirms the real API path works end-to-end with the `PGMUSTARD_API_KEY` env var — no further
endpoint discovery needed for future runs.
