---
name: pr
description: Creates a Bitbucket draft PR from the current branch using the Bitbucket REST API. Fetches Jira ticket content, generates a Perl critic report when Perl files changed, and derives a change summary from the implementation plan or git diff. If a PR already exists, rebases off the destination branch and pushes.
---

# /pr

You are the PR Orchestrator. You create a well-formed Bitbucket draft PR from the current branch via the Bitbucket Cloud REST API v2.

**Architecture:**
- Main context = orchestration, PR body synthesis, Bash calls, and Write tool only
- Subagents = ticket fetch (MCP) and perlcritic only — git/diff/PR-lookup never need a subagent

**Target: main context under 10k tokens at PR-complete.**

---

## Ground Rules

- **Never create a PR for omg-docker** — it is on GitLab. Stop and tell the user to create it manually.
- **Draft by default.** Always create as draft unless the user explicitly says otherwise.
- **Always confirm destination branch first** — ask in Step 2, then immediately check for an existing PR before any diff/conflict work.
- **Warn on merge conflicts** before creating the PR (Step 4).
- **Warn on perlcritic violations** before creating the PR (Step 6).
- **JSON safety:** Never pipe shell variables through `jq -n --arg` — Unicode in titles/descriptions causes parse errors. Always use the **Write tool** to write the JSON payload to `/tmp/pr_payload.json`, then `curl -d @/tmp/pr_payload.json`. (Windows: Git Bash maps `/tmp` automatically — if the Write tool cannot create `/tmp/...`, use `<REPO_ROOT>/.planning/pr_payload.json` for both the Write and the `-d @` path instead.)
- **One repo at a time.** For multi-repo tickets (e.g. omg + omg_db), the user runs /pr separately from each repo.
- **Auth:** Never put credentials in curl argv (`-u` / `-H` are visible in `ps`). All curl calls pipe a config stanza via stdin: `printf 'user = "%s:%s"\n' "$BITBUCKET_USER" "$BITBUCKET_TOKEN" | curl -s -K - ...`

---

## Repo → Bitbucket Slug Mapping

Workspace = `$OMG_BITBUCKET_WORKSPACE` (default `zlalani`) — set once in Step 1 as `BB_WORKSPACE`.

| REPO_NAME  | repo_slug | platform |
|---|---|---|
| omg        | omg       | Bitbucket |
| omg_db     | omg_db    | Bitbucket |
| omg_ice    | omg_ice   | Bitbucket |
| omg-docker | —         | GitLab — skip |

---

## Step 1 — Detect Repo and Credentials

Run directly in main context:

```bash
REPO_ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)
REPO_NAME=$(basename "$REPO_ROOT" 2>/dev/null)
CURRENT_BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null)
BB_WORKSPACE="${OMG_BITBUCKET_WORKSPACE:-zlalani}"   # single source — override via env

# Check for plan file and extract ticket ID / base branch from it
PLAN_FILE=$(ls "$REPO_ROOT/.planning/approved-plan-"*.md 2>/dev/null | head -1)
TICKET_ID_PLAN=$([ -n "$PLAN_FILE" ] && grep "^ticket:" "$PLAN_FILE" | sed 's/ticket: //' || echo "")
BASE_BRANCH_PLAN=$([ -n "$PLAN_FILE" ] && grep "^base:" "$PLAN_FILE" | sed 's/base: //' || echo "")

# Extract ticket ID from branch name as fallback
TICKET_ID_BRANCH=$(echo "$CURRENT_BRANCH" | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
TICKET_ID=${TICKET_ID_PLAN:-$TICKET_ID_BRANCH}

# Auto-detect base branch (suggestion only — confirmed with user in Step 2)
BASE_BRANCH_AUTO=$(git -C "$REPO_ROOT" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@')

# Verify credentials
[ -z "$BITBUCKET_TOKEN" ] && echo "BITBUCKET_TOKEN_MISSING=yes"
[ -z "$BITBUCKET_USER"  ] && echo "BITBUCKET_USER_MISSING=yes"

echo "REPO=$REPO_NAME"
echo "BRANCH=$CURRENT_BRANCH"
echo "TICKET_ID=${TICKET_ID:-none}"
echo "PLAN_FILE=${PLAN_FILE:-none}"
echo "BASE_BRANCH_AUTO=${BASE_BRANCH_AUTO:-unknown}"
echo "BASE_BRANCH_PLAN=${BASE_BRANCH_PLAN:-none}"
```

**Stop conditions:**
- **REPO_ROOT empty** → *"Not inside a git repository."* Stop.
- **REPO_NAME = omg-docker** → *"omg-docker is on GitLab — create the PR manually."* Stop.
- **BITBUCKET_TOKEN_MISSING = yes** → *"BITBUCKET_TOKEN is not set. Add it to ~/.zshrc and restart the shell."* Stop.
- **BITBUCKET_USER_MISSING = yes** → *"BITBUCKET_USER is not set. Add it to ~/.zshrc and restart the shell."* Stop.

If TICKET_ID = none: note it — PR will be created without ticket content; title derived from branch name.

---

## Step 2 — Confirm Destination Branch and Check for Existing PR

**Always pause here.** Show the detected branch and ask for confirmation.

```
Branch:      <CURRENT_BRANCH>
Destination: <BASE_BRANCH_PLAN if set, else BASE_BRANCH_AUTO if set, else "unknown">
             [source: plan file | origin/HEAD | unknown]

Confirm destination branch (press Enter to accept, or type a different branch):
```

Wait for user response.
- **Enter / blank** → keep the displayed value as BASE_BRANCH.
- **Any text** → set BASE_BRANCH to the typed value.

Record BASE_BRANCH. **Immediately** run the PR lookup in the same step:

```bash
PR_CHECK=$(printf 'user = "%s:%s"\n' "$BITBUCKET_USER" "$BITBUCKET_TOKEN" | curl -s -K - \
  "https://api.bitbucket.org/2.0/repositories/${BB_WORKSPACE}/${REPO_NAME}/pullrequests?q=source.branch.name%3D%22${CURRENT_BRANCH}%22")
PR_URL_EXISTING=$(echo "$PR_CHECK" | grep -o "https://bitbucket.org/${BB_WORKSPACE}/${REPO_NAME}/pull-requests/[0-9]*" | head -1)
PR_EXISTS=$([ -n "$PR_URL_EXISTING" ] && echo "yes" || echo "no")

echo "PR_EXISTS=$PR_EXISTS | PR_URL=$PR_URL_EXISTING"
```

**If PR_EXISTS = yes**, surface it immediately:

```
PR already exists: <PR_URL_EXISTING>

Update description? (yes / no)
```

- **no** → stop. Output the Next Up footer with the existing PR URL.
- **yes** → skip Steps 3 and 4; go straight to Step 5 to fetch ticket content and build the description.

**If PR_EXISTS = no**, continue to Step 3.

---

## Step 3 — Gather Branch Data

Only reached when no existing PR was found. Run all data gathering in one bash block.

```bash
# Git diff summary
DIFF_STAT=$(git -C "$REPO_ROOT" diff origin/${BASE_BRANCH}...HEAD --stat 2>/dev/null | head -20)
COMMITS=$(git -C "$REPO_ROOT" log origin/${BASE_BRANCH}...HEAD --oneline 2>/dev/null | head -10)
FILES_CHANGED=$(git -C "$REPO_ROOT" diff origin/${BASE_BRANCH}...HEAD --name-only 2>/dev/null | wc -l | tr -d ' ')

# Perl files changed (for perlcritic in Step 5)
PERL_FILES=$(git -C "$REPO_ROOT" diff --name-only origin/${BASE_BRANCH}...HEAD 2>/dev/null | grep '\.pm$' | tr '\n' ' ')

# Conflict detection — non-destructive test merge; abort immediately after
git -C "$REPO_ROOT" fetch origin ${BASE_BRANCH} --quiet 2>/dev/null
MERGE_TEST=$(git -C "$REPO_ROOT" merge --no-commit --no-ff origin/${BASE_BRANCH} 2>&1)
git -C "$REPO_ROOT" merge --abort 2>/dev/null
CONFLICT_FILES=$(echo "$MERGE_TEST" | grep "CONFLICT" | sed 's/.*Merge conflict in //' | sed 's/CONFLICT ([^)]*): //')

echo "FILES_CHANGED=$FILES_CHANGED"
echo "PERL_FILES=${PERL_FILES:-none}"
echo "CONFLICT_FILES=${CONFLICT_FILES:-none}"
```

---

## Step 4 — Conflict Blocker Check

If `CONFLICT_FILES` is not empty, output immediately and wait:

```
⚠️  Merge conflicts detected with origin/<BASE_BRANCH>:

<CONFLICT_FILES — one file per line>

These must be resolved before this PR will merge cleanly.
Fix now, or create the PR anyway with known conflicts? (fix / create)
```

- **fix** → Stop. *"Run `git rebase origin/<BASE_BRANCH>`, resolve conflicts, push, then re-run /pr."*
- **create** → proceed. Conflicts will be noted in the PR body.

---

## Step 5 — Extract Plan Data and Spawn Subagents

### 5a — Extract Plan Data (if present)

If PLAN_FILE was found, extract only what's needed via targeted bash — do not read the full file:

```bash
# Step summaries (numbered items only — skip grep/code blocks)
PLAN_STEPS=$(grep -E '^\s+[0-9]+\.' "$PLAN_FILE" 2>/dev/null | head -20)
# Definition of Done checklist
PLAN_DOD=$(sed -n '/## Definition of Done/,/^##/p' "$PLAN_FILE" 2>/dev/null | grep -v '^##' | head -20)
```

If no plan file: Changes section will use DIFF_STAT and COMMITS from Step 3.

### 5b — Spawn Subagents (in one message, only what requires MCP or external tools)

---

#### Risk Assessment (always — provides risk tier and affected flows for PR body)

```
Agent(
  description="Semantic risk assessment for PR branch",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed files: <PERL_FILES and all other changed files from Step 3>
  Repo root: <REPO_ROOT>
  Tool call budget: 3.

  PHASE 1 — Risk-score changed files:
    mcp__code-review-graph__detect_changes_tool(changed_files=["<file1>", "<file2>", ...], repo_root="<REPO_ROOT>")
    If graph absent or tool errors: return RISK_TIER: unknown and stop.

  PHASE 2 — Affected flows (only for high-risk nodes from Phase 1):
    For the single highest-risk node:
    mcp__code-review-graph__get_affected_flows_tool(node="<highest risk node>", repo_root="<REPO_ROOT>")
    → returns execution flows this change participates in.

  Return schema only (no prose):

  RISK_TIER: high | medium | low | unknown
  HIGH_RISK_FILES:
    - <file path> — <reason: hub node | bridge node | cross-community>
  AFFECTED_FLOWS:
    - <flow name> — <criticality>
  (omit HIGH_RISK_FILES and AFFECTED_FLOWS if RISK_TIER is low or unknown)
  """
)
```

---

#### Ticket Fetch (only if TICKET_ID is known)

```
Agent(
  description="Fetch ticket <TICKET_ID> for PR body",
  subagent_type="Explore",
  model="haiku",
  prompt="""
  Fetch Jira ticket <TICKET_ID>.
  TOOL DISCOVERY: Atlassian MCP tool names vary by install (mcp__plugin_atlassian_atlassian__*, mcp__claude_ai_Atlassian__*, or mcp__atlassian__*). If a call fails with unknown tool, run ToolSearch(query="+jira <tool name>") and use the returned variant. Names below use the mcp__plugin_atlassian_atlassian__ prefix.
  First call mcp__plugin_atlassian_atlassian__getAccessibleAtlassianResources to get the cloudId.
  Then call mcp__plugin_atlassian_atlassian__getJiraIssue with that cloudId and issueIdOrKey="<TICKET_ID>".
  Do not retry more than once. If it fails return ERROR: <reason>.

  Return ONLY the schema below. No prose, no preamble.

  TITLE: <ticket title>
  JIRA_URL: <full URL to the Jira issue>
  SUMMARY: <3-5 sentence condensed description — key facts only>
  ACCEPTANCE_CRITERIA: <bullet list, or "none">
  FIGMA_URL: <url or "none">
  CONFLUENCE_URL: <url or "none">
  """
)
```

---

#### Perlcritic Check (only if PERL_FILES is not "none")

```
Agent(
  description="Perlcritic check on changed Perl files",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed Perl files: <PERL_FILES>

  Canonical perlcritic command (single source of truth is the /perlcritic skill
  in the OMG repo; keep this block in sync with it):
    Map each local path to its container path: <REPO_ROOT>/lib/... → /var/www/OMG/lib/...
    Skip files that no longer exist on disk.
    Run once for all remaining files:
      Bash("podman exec omg bash -c \"perlcritic --profile=/var/www/OMG/tools/perl_critic/.perlcriticrc --severity 3 --verbose '%f|%l|%s|%p|%m\\n' <CONTAINER_PATHS>\"")
    Output is one violation per line: file|line|severity|Policy::Name|message.
    Non-zero exit with output = violations found, not an error.
    If `podman exec omg true` fails: PERLCRITIC_AVAILABLE: no (container down).
    Never fall back to a host perlcritic binary — no project profile, different results.

  Return ONLY the schema below. No prose, no preamble.

  PERLCRITIC_AVAILABLE: yes | no
  VIOLATIONS:
    <file>: <violation — severity N — line N>
    (or "none")
  """
)
```

---

## Step 6 — Perlcritic Blocker Check

After subagents return, if VIOLATIONS is not "none" and PERLCRITIC_AVAILABLE = yes:

```
⚠️  Perlcritic violations found:

<violations list>

These would be flagged as blockers by /prepr. Create the PR anyway? (yes / no)
```

- **no** → stop. *"Run /perlcritic to work through the violations, then re-run /pr."*
- **yes** → proceed. Violations will be included in the PR body.

---

## Step 7 — Synthesise PR Content

### Title

- **With ticket:** `<TICKET_ID> - <TITLE from ticket fetch>`
  Example: `OMGXI-123 - Fix user login timeout`
- **Without ticket:** humanise the branch name — strip leading ticket prefix, replace hyphens with spaces, title case.
  Example: `omgxi-123-fix-login-timeout` → `Fix Login Timeout`

### Body

Build in this exact order. Omit any section entirely (including its heading) if it has no content.

```markdown
<JIRA_URL>

---

## Summary
<SUMMARY from ticket>

## Acceptance Criteria
- [ ] <criterion one>
- [ ] <criterion two>

## Resources
- Figma: <FIGMA_URL>
- Confluence: <CONFLUENCE_URL>

---

## Changes
<completed steps from plan change log, one per line>
<Definition of Done checklist if present>

---

## Risk Assessment
**Risk tier: <RISK_TIER from risk assessment subagent>**
<If high or medium: list HIGH_RISK_FILES with reason>
<If AFFECTED_FLOWS present: "Affected flows: <flow names>">
<If low: omit this section entirely>
<If unknown: omit this section entirely>
```

**Acceptance Criteria** must always use checkboxes (`- [ ]`), never plain bullets.

If no plan file, synthesise a human-readable description of what changed from the DIFF_STAT and COMMITS captured in Step 3. Do not paste raw git output. Instead write one bullet per changed file — bold the filename, then plain-English description of *what* changed and *why*. Example:

```markdown
## Changes
- **`views/resources/resources_scheduler.tt`** — Added grouping toolbar to Capacity View to match existing List View layout
- **`lib/resources/resources_helper.pm`** — Removed legacy grouping buttons incorrectly rendered above the Bryntum header
- **`locale/en.json`** — Added locale keys for the new grouping label across all supported languages
```

If Perl files changed, append a **grouped table per file** — never a flat list:

```markdown
## Perl Critic

### lib/path/to/file.pm

| Line | Sev | Violation |
|-----:|:---:|-----------|
| 72   |  3  | `die` used instead of `croak` |
| 150  |  3  | Hard tabs used |

### lib/path/to/other_file.pm

| Line | Sev | Violation |
|-----:|:---:|-----------|
| 61   |  3  | High complexity (47) — `showProjects` |
```

If no violations: `## Perl Critic\nNo violations found.`

---

## Step 8 — Create or Update PR

### If PR_EXISTS = no

Use the **Write tool** to create `/tmp/pr_payload.json` with the complete payload as valid JSON. The Write tool handles Unicode and special characters — no shell quoting needed.

Structure to write:
```json
{
  "title": "<PR_TITLE>",
  "description": "<PR_BODY — use \\n for newlines, escape backslashes and quotes>",
  "source": {"branch": {"name": "<CURRENT_BRANCH>"}},
  "destination": {"branch": {"name": "<BASE_BRANCH>"}},
  "draft": true
}
```

Then run in main context:

```bash
printf 'user = "%s:%s"\n' "$BITBUCKET_USER" "$BITBUCKET_TOKEN" | curl -s -K - -X POST \
  -H "Content-Type: application/json" \
  -d @/tmp/pr_payload.json \
  "https://api.bitbucket.org/2.0/repositories/${BB_WORKSPACE}/<REPO_NAME>/pullrequests" \
  -o /tmp/pr_response.json -w "HTTP_STATUS:%{http_code}\n"

python3 -c "
import json
with open('/tmp/pr_response.json') as f:
    r = json.load(f)
if 'error' in r:
    print('ERROR:', r['error'].get('message', str(r['error'])))
else:
    print('PR_URL:', r['links']['html']['href'])
"
```

If PR_URL returned: output `Draft PR created: <PR_URL>`
If ERROR returned: surface the error to the user and stop.

---

### If PR_EXISTS = yes

Read `references/update-existing-pr.md` and follow it exactly: extract PR_ID, check whether rebase is needed (`merge-base --is-ancestor`), rebase + `push --force-with-lease` if so, then PUT the updated description.

---

## Step 9 — Multi-repo Note (conditional)

If REPO_NAME = omg and the ticket SUMMARY contained DB-related keywords (table, schema, ALTER, migration, stored procedure, postgres):

> *"If this ticket also touches omg_db, cd into <WS_ROOT>/omg_db and run /pr to create a companion PR."*

---

```
---
# Next Up

  Draft PR: <PR_URL>
  When ready: remove draft status and assign reviewers on Bitbucket.

Also available:
  - /prepr — run pre-PR checks if not done yet
  - /ticket <ticket-id> — start a new ticket

Done — start a fresh session for the next phase.
---
```
