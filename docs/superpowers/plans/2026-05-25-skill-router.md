# Skill Router & Plugin Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all confirmed plugin blockers (JAM tool names, MCP permissions) and build a deterministic UserPromptSubmit hook that routes natural-language dev requests to the correct skill or inline procedure.

**Architecture:** A Python hook (`skill-router.py`) reads a manifest JSON on every prompt, runs a 4-stage pipeline (kill-switch → bypass → high-confidence match → ambiguous menu), and emits plain-text instructions into Claude's context. Inline procedures (Markdown files) are injected for stateless actions; skills are invoked for multi-step workflows. A PreToolUse script blocks the one clearly-wrong pattern (GitHub CLI in a Bitbucket project).

**Tech Stack:** Python 3 (stdlib only), Claude Code hook system (UserPromptSubmit / PreToolUse), Bitbucket REST API v2, Atlassian MCP tools, pytest

---

## File Map

### Created
- `hook-scripts/skill-router.py` — UserPromptSubmit hook: intent detection + routing
- `hook-scripts/enforce-skill-usage.py` — PreToolUse hook: block `gh pr create`
- `skill-routing-manifest.json` — 20-route config (shipped with plugin, user-override at `~/.claude/`)
- `procedures/inline/pr-address-comments.md`
- `procedures/inline/pr-fetch-comments.md`
- `procedures/inline/ticket-status.md`
- `procedures/inline/ticket-comment.md`
- `procedures/inline/ticket-transition.md`
- `procedures/inline/git-branch-summary.md`
- `procedures/inline/help-skills.md`
- `tests/test_skill_router.py`
- `tests/router-fixtures.jsonl`

### Modified
- `skills/ticket/SKILL.md` — JAM tool names (grep-replace)
- `skills/debug/SKILL.md` — JAM tool names (grep-replace)
- `settings.json` — add 13 MCP permissions, fix 3 names, add PreToolUse hook
- `~/.claude/settings.json` (user-level) — add UserPromptSubmit hook entry

---

## Task 1: Fix JAM Tool Names

**Files:**
- Modify: `skills/ticket/SKILL.md`
- Modify: `skills/debug/SKILL.md`

- [ ] **Step 1.1: Grep-replace in ticket/SKILL.md**

```bash
cd /Users/Shared/Code/jintech-omg-dev
sed -i '' \
  -e 's/mcp__JAM-MCP__getVideoTranscript/mcp__Jam__getVideoTranscript/g' \
  -e 's/mcp__JAM-MCP__getUserEvents/mcp__Jam__getUserEvents/g' \
  -e 's/mcp__JAM-MCP__getConsoleLogs/mcp__Jam__getConsoleLogs/g' \
  -e 's/mcp__JAM-MCP__getNetworkRequests/mcp__Jam__getNetworkRequests/g' \
  -e 's/mcp__JAM-MCP__getScreenshots/mcp__Jam__getScreenshots/g' \
  skills/ticket/SKILL.md
```

- [ ] **Step 1.2: Grep-replace in debug/SKILL.md**

```bash
cd /Users/Shared/Code/jintech-omg-dev
sed -i '' \
  -e 's/mcp__JAM-MCP__getVideoTranscript/mcp__Jam__getVideoTranscript/g' \
  -e 's/mcp__JAM-MCP__getUserEvents/mcp__Jam__getUserEvents/g' \
  -e 's/mcp__JAM-MCP__getConsoleLogs/mcp__Jam__getConsoleLogs/g' \
  -e 's/mcp__JAM-MCP__getNetworkRequests/mcp__Jam__getNetworkRequests/g' \
  skills/debug/SKILL.md
```

- [ ] **Step 1.3: Verify no old names remain**

```bash
cd /Users/Shared/Code/jintech-omg-dev
grep -rn "JAM-MCP" skills/
```

Expected: no output.

- [ ] **Step 1.4: Commit**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add skills/ticket/SKILL.md skills/debug/SKILL.md
git commit -m "fix: correct JAM MCP tool names (JAM-MCP -> Jam) in ticket and debug skills"
```

---

## Task 2: Fix MCP Permissions

**Files:**
- Modify: `settings.json`

- [ ] **Step 2.1: Read current permissions**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -c "import json; d=json.load(open('settings.json')); print(json.dumps(d['permissions']['allow'], indent=2))"
```

- [ ] **Step 2.2: Apply permission fixes**

Open `settings.json`. In `permissions.allow`, make these changes:

Replace the three malformed entries:
```json
"mcp__code-review-graph__get_architecture_overview"
"mcp__code-review-graph__get_impact_radius"
"mcp__code-review-graph__detect_changes"
```

With:
```json
"mcp__code-review-graph__get_architecture_overview_tool",
"mcp__code-review-graph__get_impact_radius_tool",
"mcp__code-review-graph__detect_changes_tool",
```

Add these 13 entries at the end of the `permissions.allow` array:
```json
"mcp__code-review-graph__get_affected_flows_tool",
"mcp__code-review-graph__get_review_context_tool",
"mcp__code-review-graph__find_large_functions_tool",
"mcp__code-review-graph__get_knowledge_gaps_tool",
"mcp__code-review-graph__cross_repo_search_tool",
"mcp__code-review-graph__get_community_tool",
"mcp__code-review-graph__get_suggested_questions_tool",
"mcp__code-review-graph__get_flow_tool",
"mcp__Jam__getVideoTranscript",
"mcp__Jam__getUserEvents",
"mcp__Jam__getConsoleLogs",
"mcp__Jam__getNetworkRequests",
"mcp__Jam__getScreenshots"
```

- [ ] **Step 2.3: Verify JSON is valid**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -c "import json; json.load(open('settings.json')); print('valid')"
```

Expected: `valid`

- [ ] **Step 2.4: Verify count**

```bash
python3 -c "import json; d=json.load(open('settings.json')); mcp=[x for x in d['permissions']['allow'] if x.startswith('mcp__')]; print(len(mcp), 'MCP entries')"
```

Expected: `29 MCP entries` (16 code-review-graph + 5 Jam + 6 Atlassian + 2 others that were already there)

- [ ] **Step 2.5: Commit**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add settings.json
git commit -m "fix: correct MCP permission names and add 13 missing tool entries"
```

---

## Task 3: enforce-skill-usage.py (PreToolUse Backstop)

**Files:**
- Create: `hook-scripts/enforce-skill-usage.py`
- Modify: `settings.json`

- [ ] **Step 3.1: Write the hook**

Create `/Users/Shared/Code/jintech-omg-dev/hook-scripts/enforce-skill-usage.py`:

```python
#!/usr/bin/env python3
"""
PreToolUse hook: block gh pr create (wrong platform — OMG uses Bitbucket).
v1 scope: GitHub CLI only. v2 will expand based on audit log data.
Exit 2 = hard block. Exit 0 = allow.
"""
import sys
import json

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = data.get("tool_name", "")
tool_input = data.get("tool_input", {})

if tool == "Bash":
    cmd = tool_input.get("command", "")
    if "gh pr create" in cmd:
        print(
            "BLOCKED: OMG uses Bitbucket, not GitHub CLI.\n"
            "Use the /pr skill instead:\n"
            "  Skill tool: skill=\"jintech-omg-dev:pr\""
        )
        sys.exit(2)

sys.exit(0)
```

- [ ] **Step 3.2: Wire into settings.json PreToolUse hooks**

In `/Users/Shared/Code/jintech-omg-dev/settings.json`, add a `hooks` section:

```json
"hooks": {
  "PreToolUse": [
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"/Users/Shared/Code/jintech-omg-dev/hook-scripts/enforce-skill-usage.py\""
        }
      ]
    }
  ]
}
```

Note: this is separate from the existing `PreToolUse` hooks in `~/.claude/settings.json` (which has `enforce-mcp-search.py`). Both will fire.

- [ ] **Step 3.3: Verify JSON is valid**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -c "import json; json.load(open('settings.json')); print('valid')"
```

- [ ] **Step 3.4: Test hook manually**

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"gh pr create --title test"}}' \
  | python3 hook-scripts/enforce-skill-usage.py
echo "Exit code: $?"
```

Expected: prints block message, exit code 2.

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push"}}' \
  | python3 hook-scripts/enforce-skill-usage.py
echo "Exit code: $?"
```

Expected: no output, exit code 0.

- [ ] **Step 3.5: Commit**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add hook-scripts/enforce-skill-usage.py settings.json
git commit -m "feat: add enforce-skill-usage PreToolUse hook; block gh pr create in Bitbucket project"
```

---

## Task 4: skill-routing-manifest.json

**Files:**
- Create: `skill-routing-manifest.json`

- [ ] **Step 4.1: Create the manifest**

Create `/Users/Shared/Code/jintech-omg-dev/skill-routing-manifest.json`:

```json
{
  "_comment": "Order matters: first high-confidence match wins. Edit ~/.claude/skill-routing-manifest.json to override.",
  "intents": [
    {
      "id": "pr-create",
      "patterns": ["\\b(create|raise|open|draft)\\s+(a\\s+)?pr\\b"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:pr"}
    },
    {
      "id": "pr-update",
      "patterns": ["\\bupdate\\b.*\\bpr\\b(?!.*description says)"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:pr"}
    },
    {
      "id": "pr-rebase",
      "patterns": ["\\brebase\\b.*\\b(pr|branch|onto)\\b"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:pr"}
    },
    {
      "id": "pr-comments-address",
      "patterns": ["\\b(address|respond to|handle)\\b.*\\b(pr|review)\\s+comments?\\b"],
      "confidence": "high",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/pr-address-comments.md"}
    },
    {
      "id": "pr-comments-fetch",
      "patterns": [
        "\\bfetch\\b.*\\b(review|pr)\\s+comments?\\b",
        "\\bshow\\b.*\\bpr\\b.*\\bcomments?\\b"
      ],
      "confidence": "high",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/pr-fetch-comments.md"}
    },
    {
      "id": "ticket-investigate",
      "patterns": ["\\b(investigate|look into|work on|start on)\\b.*\\bticket\\b"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:ticket"}
    },
    {
      "id": "ticket-id-direct",
      "patterns": ["\\bOMGXI-[0-9]+\\b(?!.*already|.*finished|.*fixed|.*closed)"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:ticket"}
    },
    {
      "id": "ticket-status",
      "patterns": [
        "\\b(what'?s|check)\\b.*\\bticket\\b.*\\bstatus\\b",
        "\\bticket\\b.*\\bstatus\\b"
      ],
      "confidence": "high",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/ticket-status.md"}
    },
    {
      "id": "ticket-comment",
      "patterns": ["\\b(add|post)\\b.*\\b(comment|note)\\b.*\\bticket\\b"],
      "confidence": "high",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/ticket-comment.md"}
    },
    {
      "id": "ticket-transition",
      "patterns": ["\\b(transition|move|set)\\b.*\\bticket\\b.*\\b(in.?progress|done|review|to.?do)\\b"],
      "confidence": "high",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/ticket-transition.md"}
    },
    {
      "id": "implement",
      "patterns": [
        "\\bimplement\\b.*\\bplan\\b",
        "\\b(start|begin)\\b.*\\bimplementing\\b(?!.*don't|.*not yet)"
      ],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:implement"}
    },
    {
      "id": "prepr",
      "patterns": [
        "\\bpre.?pr\\b",
        "\\b(check|run)\\b.*\\bbefore\\b.*\\bpr\\b"
      ],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:prepr"}
    },
    {
      "id": "debug",
      "patterns": [
        "\\b(debug|diagnose)\\b.*\\bthis\\b",
        "\\bsomething.?s broken\\b(?!.*was|.*before)"
      ],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:debug"}
    },
    {
      "id": "grill-me",
      "patterns": [
        "\\bgrill\\b.*\\b(me|my|this)\\b",
        "\\bstress.?test.*plan\\b"
      ],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:grill-me"}
    },
    {
      "id": "code-review",
      "patterns": ["\\breview\\b.*\\b(diff|code|branch|changes)\\b"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "code-review"}
    },
    {
      "id": "verify",
      "patterns": ["\\bverify\\b.*\\b(works?|change|fix|this)\\b(?!.*can you|.*does it)"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "verify"}
    },
    {
      "id": "git-branch-summary",
      "patterns": [
        "\\bwhat.?s in\\b.*\\bbranch\\b",
        "\\bwhat.*changed\\b.*\\bbranch\\b"
      ],
      "confidence": "high",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/git-branch-summary.md"}
    },
    {
      "id": "session-resume",
      "patterns": ["\\b(resume|continue|pick up)\\b.*\\b(session|where)\\b"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:resume-session"}
    },
    {
      "id": "session-save",
      "patterns": ["\\b(save|record)\\b.*\\b(session|progress|where we)\\b"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "jintech-omg-dev:save-session"}
    },
    {
      "id": "commit",
      "patterns": ["\\b(commit\\b.*\\bthis|write.*commit.*message|make.*commit)\\b(?!.*don't|.*not yet)"],
      "confidence": "high",
      "action": {"type": "skill", "skill": "caveman:caveman-commit"}
    },
    {
      "id": "help-skills",
      "patterns": [
        "\\bwhat skills\\b",
        "\\bwhat can you do\\b",
        "\\blist.*skills\\b",
        "\\bavailable.*commands\\b"
      ],
      "confidence": "low",
      "action": {"type": "inline", "file": "~/.claude/procedures/inline/help-skills.md"}
    }
  ]
}
```

- [ ] **Step 4.2: Validate JSON**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -c "import json; d=json.load(open('skill-routing-manifest.json')); print(len(d['intents']), 'intents loaded')"
```

Expected: `21 intents loaded`

- [ ] **Step 4.3: Commit**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add skill-routing-manifest.json
git commit -m "feat: add skill-routing-manifest with 21 intent routes"
```

---

## Task 5: Inline Procedure Files

**Files:**
- Create: `procedures/inline/pr-address-comments.md`
- Create: `procedures/inline/pr-fetch-comments.md`
- Create: `procedures/inline/ticket-status.md`
- Create: `procedures/inline/ticket-comment.md`
- Create: `procedures/inline/ticket-transition.md`
- Create: `procedures/inline/git-branch-summary.md`
- Create: `procedures/inline/help-skills.md`

- [ ] **Step 5.1: pr-address-comments.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/pr-address-comments.md`:

```markdown
# Procedure: Address PR Review Comments

## Step 1 — Identify PR

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")
CURRENT_BRANCH=$(git branch --show-current)
PR_JSON=$(curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO_NAME}/pullrequests?q=source.branch.name%3D%22${CURRENT_BRANCH}%22")
PR_ID=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); prs=d.get('values',[]); print(prs[0]['id'] if prs else 'none')")
echo "PR_ID=$PR_ID"
```

If PR_ID = none: stop and tell user no open PR found for this branch.

## Step 2 — Fetch Unresolved Comments

```bash
curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO_NAME}/pullrequests/${PR_ID}/comments" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
comments = [c for c in data.get('values', [])
            if not c.get('deleted') and not c.get('resolved')
            and c.get('content', {}).get('raw', '').strip()]
print(f'OPEN COMMENTS: {len(comments)}')
for c in comments:
    cid = c['id']
    file = c.get('inline', {}).get('path', 'general')
    line = c.get('inline', {}).get('to', 'N/A')
    author = c.get('author', {}).get('display_name', '?')
    text = c['content']['raw']
    print(f'--- ID:{cid} {file}:{line} by {author}')
    print(text[:300])
"
```

## Step 3 — Address Each Comment

For each open comment:
- Read the referenced file at the indicated line using the Read tool
- Make the minimal edit that satisfies the comment using the Edit tool
- Do not rewrite surrounding code

## Step 4 — Report

List each comment addressed: comment ID, file, line, what changed.
Do not call the Bitbucket API to mark comments resolved unless the user explicitly asks.
```

- [ ] **Step 5.2: pr-fetch-comments.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/pr-fetch-comments.md`:

```markdown
# Procedure: Fetch PR Review Comments

## Step 1 — Identify PR

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")
CURRENT_BRANCH=$(git branch --show-current)
PR_JSON=$(curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO_NAME}/pullrequests?q=source.branch.name%3D%22${CURRENT_BRANCH}%22")
PR_ID=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); prs=d.get('values',[]); print(prs[0]['id'] if prs else 'none')")
```

If PR_ID = none: tell user no open PR for this branch.

## Step 2 — List All Comments

```bash
curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO_NAME}/pullrequests/${PR_ID}/comments" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
comments = [c for c in data.get('values', [])
            if not c.get('deleted') and c.get('content', {}).get('raw', '').strip()]
open_c = [c for c in comments if not c.get('resolved')]
resolved_c = [c for c in comments if c.get('resolved')]
print(f'Open: {len(open_c)}  Resolved: {len(resolved_c)}  Total: {len(comments)}')
print()
for c in open_c:
    file = c.get('inline', {}).get('path', 'general comment')
    line = c.get('inline', {}).get('to', '')
    author = c.get('author', {}).get('display_name', '?')
    text = c['content']['raw']
    print(f'[OPEN] {file}:{line} — {author}')
    print(f'  {text[:300]}')
    print()
"
```
```

- [ ] **Step 5.3: ticket-status.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/ticket-status.md`:

```markdown
# Procedure: Fetch Ticket Status

## Step 1 — Get Ticket ID

Extract from current branch or use ticket ID from user message:
```bash
TICKET_ID=$(git branch --show-current | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
echo "TICKET_ID=${TICKET_ID:-none}"
```

If TICKET_ID = none: ask the user to provide the ticket ID.

## Step 2 — Fetch via Atlassian MCP

```
1. Call mcp__claude_ai_Atlassian__getAccessibleAtlassianResources → get cloudId
2. Call mcp__claude_ai_Atlassian__getJiraIssue with cloudId and issueIdOrKey=<TICKET_ID>
```

## Step 3 — Display

Show in this format:
- **Ticket:** OMGXI-XXXX — <title>
- **Status:** <status>
- **Assignee:** <name>
- **Summary:** <2-3 sentence description>
- **Acceptance Criteria:** (if present)
```

- [ ] **Step 5.4: ticket-comment.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/ticket-comment.md`:

```markdown
# Procedure: Add Comment to Ticket

## Step 1 — Get Ticket ID and Comment Text

```bash
TICKET_ID=$(git branch --show-current | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
echo "TICKET_ID=${TICKET_ID:-none}"
```

If TICKET_ID = none: ask user for ticket ID.
If comment text not provided in user message: ask for it.

## Step 2 — Post Comment

```
1. Call mcp__claude_ai_Atlassian__getAccessibleAtlassianResources → get cloudId
2. Call mcp__claude_ai_Atlassian__addCommentToJiraIssue with:
     cloudId = <cloudId>
     issueIdOrKey = <TICKET_ID>
     body = <comment text from user>
```

## Step 3 — Confirm

Report: "Comment added to <TICKET_ID>."
```

- [ ] **Step 5.5: ticket-transition.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/ticket-transition.md`:

```markdown
# Procedure: Transition Ticket Status

## Step 1 — Get Ticket ID

```bash
TICKET_ID=$(git branch --show-current | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
echo "TICKET_ID=${TICKET_ID:-none}"
```

If TICKET_ID = none: ask user for ticket ID.

## Step 2 — Fetch Available Transitions

```
1. Call mcp__claude_ai_Atlassian__getAccessibleAtlassianResources → get cloudId
2. Call mcp__claude_ai_Atlassian__getTransitionsForJiraIssue with cloudId and issueIdOrKey=<TICKET_ID>
   → returns list of {id, name} transition objects
```

## Step 3 — Apply Transition

Match the user's requested status to the closest transition name (case-insensitive).
```
Call mcp__claude_ai_Atlassian__transitionJiraIssue with:
  cloudId = <cloudId>
  issueIdOrKey = <TICKET_ID>
  transitionId = <matched transition id>
```

If no close match: show the available transition names and ask the user to choose.

## Step 4 — Confirm

Report: "<TICKET_ID> transitioned to <new status>."
```

- [ ] **Step 5.6: git-branch-summary.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/git-branch-summary.md`:

```markdown
# Procedure: Show Branch Changes

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
BASE=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@' || echo "master")

echo "=== Branch: $(git branch --show-current) vs origin/$BASE ==="
echo ""
echo "--- Commits ---"
git log origin/${BASE}...HEAD --oneline

echo ""
echo "--- Files changed ---"
git diff origin/${BASE}...HEAD --stat

echo ""
echo "--- File list ---"
git diff origin/${BASE}...HEAD --name-status
```
```

- [ ] **Step 5.7: help-skills.md**

Create `/Users/Shared/Code/jintech-omg-dev/procedures/inline/help-skills.md`:

```markdown
# Available Skills & Natural Language Triggers

## SDLC Skills (jintech-omg-dev)
- `/ticket` — Investigate a Jira ticket and produce an implementation plan
  → "investigate OMGXI-1234" / "look into ticket X" / mention ticket ID directly
- `/implement` — Execute an approved plan
  → "start implementing the plan" / "implement this"
- `/pr` — Create, update, or rebase a Bitbucket PR
  → "create a PR" / "raise a PR" / "rebase this branch" / "update the PR"
- `/prepr` — Pre-PR audit: perlcritic, risk, standards
  → "run prepr" / "check before raising PR" / "pre-PR checks"
- `/debug` — Root cause analysis for broken behaviour
  → "debug this" / "something's broken" / "diagnose the issue"
- `/grill-me` — Spec-polishing interview
  → "grill me on this design" / "stress test the plan"

## Review & Quality Skills
- `/code-review` — Review current diff for correctness bugs
  → "review the diff" / "review the code" / "review branch changes"
- `/verify` — Verify a change works by running the app
  → "verify this works" / "confirm the fix works"

## Session Skills
- `/save-session` — Save current session state to resume later
  → "save the session" / "save where we are"
- `/resume-session` — Resume from last saved session
  → "resume where we left off" / "continue the session"

## Inline Procedures (no skill invocation needed)
- Address PR review comments → "address the PR comments"
- Fetch PR review comments → "fetch the review comments" / "show PR comments"
- Ticket status → "what's the ticket status" / "check ticket status"
- Add ticket comment → "add a comment to the ticket"
- Transition ticket → "move ticket to in progress" / "set ticket to done"
- Branch summary → "what's in this branch" / "what changed"
```

- [ ] **Step 5.8: Commit all procedure files**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add procedures/inline/
git commit -m "feat: add 7 inline procedure files for PR, ticket, git, and help actions"
```

---

## Task 6: skill-router.py

**Files:**
- Create: `tests/test_skill_router.py`
- Create: `hook-scripts/skill-router.py`

- [ ] **Step 6.1: Write tests first**

Create `/Users/Shared/Code/jintech-omg-dev/tests/test_skill_router.py`:

```python
"""Tests for skill-router.py intent matching and output."""
import json
import subprocess
import sys
import os
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "hook-scripts" / "skill-router.py"
MANIFEST = Path(__file__).parent.parent / "skill-routing-manifest.json"


def run_router(prompt: str, env_extra: dict = None) -> tuple[str, int]:
    """Run skill-router.py with given prompt, return (stdout, exit_code)."""
    payload = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "test",
        "transcript_path": "/tmp/test",
        "cwd": "/tmp",
        "prompt": prompt
    })
    env = os.environ.copy()
    # Point to test manifest
    env["SKILL_ROUTER_MANIFEST_OVERRIDE"] = str(MANIFEST)
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload, capture_output=True, text=True, env=env
    )
    return result.stdout.strip(), result.returncode


class TestBypass:
    def test_slash_command_bypassed(self):
        out, code = run_router("/ticket OMGXI-1234")
        assert out == ""
        assert code == 0

    def test_backslash_bypassed(self):
        out, code = run_router("\\raw: do something")
        assert out == ""
        assert code == 0

    def test_kill_switch(self):
        out, code = run_router("address the PR comments",
                               {"CLAUDE_SKILL_ROUTER_DISABLED": "1"})
        assert out == ""
        assert code == 0


class TestHighConfidenceSkillRoutes:
    def test_pr_create(self):
        out, _ = run_router("create a PR for this branch")
        assert "ROUTING ACTIVE" in out
        assert "jintech-omg-dev:pr" in out

    def test_pr_rebase(self):
        out, _ = run_router("rebase the branch onto master")
        assert "jintech-omg-dev:pr" in out

    def test_ticket_id_direct(self):
        out, _ = run_router("OMGXI-9400")
        assert "jintech-omg-dev:ticket" in out

    def test_ticket_investigate(self):
        out, _ = run_router("investigate ticket OMGXI-9400")
        assert "jintech-omg-dev:ticket" in out

    def test_implement(self):
        out, _ = run_router("start implementing the plan")
        assert "jintech-omg-dev:implement" in out

    def test_prepr(self):
        out, _ = run_router("run pre-PR checks")
        assert "jintech-omg-dev:prepr" in out

    def test_debug(self):
        out, _ = run_router("debug this error")
        assert "jintech-omg-dev:debug" in out

    def test_grill_me(self):
        out, _ = run_router("grill me on this design")
        assert "jintech-omg-dev:grill-me" in out

    def test_commit(self):
        out, _ = run_router("commit this")
        assert "caveman:caveman-commit" in out

    def test_session_resume(self):
        out, _ = run_router("resume where we left off")
        assert "jintech-omg-dev:resume-session" in out


class TestHighConfidenceInlineRoutes:
    def test_pr_address_comments(self):
        out, _ = run_router("address the PR comments")
        assert "PROCEDURE ACTIVE" in out
        assert "pr-comments-address" in out

    def test_pr_fetch_comments(self):
        out, _ = run_router("fetch the review comments")
        assert "PROCEDURE ACTIVE" in out
        assert "pr-comments-fetch" in out

    def test_ticket_status(self):
        out, _ = run_router("what's the ticket status")
        assert "PROCEDURE ACTIVE" in out
        assert "ticket-status" in out

    def test_git_branch_summary(self):
        out, _ = run_router("what's in this branch")
        assert "PROCEDURE ACTIVE" in out
        assert "git-branch-summary" in out


class TestNegativePatterns:
    def test_finished_ticket_not_routed(self):
        out, _ = run_router("I already finished OMGXI-9400")
        assert "ROUTING ACTIVE" not in out
        assert "PROCEDURE ACTIVE" not in out

    def test_dont_implement_not_routed(self):
        out, _ = run_router("don't implement yet, just plan")
        assert "jintech-omg-dev:implement" not in out

    def test_pr_description_info_not_routed(self):
        out, _ = run_router("the PR description says it should work fine")
        assert "ROUTING ACTIVE" not in out

    def test_no_match_silent(self):
        out, _ = run_router("what time is it in Tokyo")
        assert out == ""

    def test_fail_open_on_bad_json(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input="not json", capture_output=True, text=True
        )
        assert result.returncode == 0
```

- [ ] **Step 6.2: Run tests — verify they all fail**

```bash
cd /Users/Shared/Code/jintech-omg-dev
pip install pytest -q 2>/dev/null || true
python3 -m pytest tests/test_skill_router.py -v 2>&1 | head -30
```

Expected: errors like `FileNotFoundError` or `ModuleNotFoundError` since `skill-router.py` doesn't exist yet.

- [ ] **Step 6.3: Write skill-router.py**

Create `/Users/Shared/Code/jintech-omg-dev/hook-scripts/skill-router.py`:

```python
#!/usr/bin/env python3
"""
UserPromptSubmit hook: route natural-language requests to skills or inline procedures.

Reads manifest from (in priority order):
  1. SKILL_ROUTER_MANIFEST_OVERRIDE env var (tests only)
  2. ~/.claude/skill-routing-manifest.json (user override)
  3. $CLAUDE_PLUGIN_ROOT/skill-routing-manifest.json (plugin default)

Emits plain stdout text — injected as <system-reminder> by Claude Code.
Fail-open: any exception → silent exit 0. Never blocks user input.
"""
import sys
import json
import os
import re
import hashlib
import threading
from datetime import datetime
from pathlib import Path

KILL_SWITCH = os.environ.get("CLAUDE_SKILL_ROUTER_DISABLED")
PLUGIN_ROOT = os.environ.get(
    "CLAUDE_PLUGIN_ROOT",
    str(Path(__file__).parent.parent)
)
TIMEOUT_SECS = 0.5
LOG_DIR = Path.home() / ".claude" / "logs"


def get_manifest_path() -> Path | None:
    # Test override
    override = os.environ.get("SKILL_ROUTER_MANIFEST_OVERRIDE")
    if override and Path(override).exists():
        return Path(override)
    # User override
    user_path = Path.home() / ".claude" / "skill-routing-manifest.json"
    if user_path.exists():
        return user_path
    # Plugin default
    plugin_path = Path(PLUGIN_ROOT) / "skill-routing-manifest.json"
    if plugin_path.exists():
        return plugin_path
    return None


def load_manifest(path: Path) -> list:
    data = json.loads(path.read_text())
    return data.get("intents", [])


def match_intents(prompt: str, intents: list) -> tuple[list, list]:
    """Return (high_confidence_matches, low_confidence_matches)."""
    high, low = [], []
    for intent in intents:
        patterns = intent.get("patterns", [])
        confidence = intent.get("confidence", "low")
        for pattern in patterns:
            try:
                if re.search(pattern, prompt, re.IGNORECASE):
                    (high if confidence == "high" else low).append(intent)
                    break
            except re.error:
                continue
    return high, low


def resolve_file(path_str: str) -> Path:
    return Path(path_str.replace("~", str(Path.home())))


def build_output(intent: dict) -> str | None:
    action = intent.get("action", {})
    action_type = action.get("type")

    if action_type == "skill":
        skill = action["skill"]
        return (
            f"⚡ ROUTING ACTIVE: The user's request matches the `{skill}` skill.\n"
            f"You MUST invoke the Skill tool with skill=\"{skill}\" before doing anything else.\n"
            f"Do not improvise the steps. The skill defines the exact procedure."
        )

    if action_type == "inline":
        proc_file = resolve_file(action.get("file", ""))
        if not proc_file.exists():
            _log(intent["id"], "inline_file_missing", "")
            return None
        content = proc_file.read_text().strip()
        intent_id = intent["id"]
        return (
            f"⚡ PROCEDURE ACTIVE: {intent_id}\n"
            f"{content}\n"
            f"Follow these steps exactly. Do not deviate."
        )

    return None


def _log(intent_id: str, status: str, prompt: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"intent-router-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        if log_file.exists() and log_file.stat().st_size > 10 * 1024 * 1024:
            return
        entry = {
            "ts": datetime.now().isoformat(),
            "intent": intent_id,
            "status": status,
            "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:12]
        }
        with log_file.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> None:
    if KILL_SWITCH:
        return

    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return

    # Stage 1: explicit command bypass
    if prompt.startswith("/") or prompt.startswith("\\"):
        return

    manifest_path = get_manifest_path()
    if not manifest_path:
        return

    try:
        intents = load_manifest(manifest_path)
    except Exception:
        return

    high_matches, low_matches = match_intents(prompt, intents)

    output = None
    matched_id = None

    if high_matches:
        # First high-confidence match wins
        intent = high_matches[0]
        matched_id = intent["id"]
        output = build_output(intent)

    elif len(low_matches) == 0:
        return

    elif len(low_matches) == 1:
        intent = low_matches[0]
        matched_id = intent["id"]
        action = intent["action"]
        ref = action.get("skill") or action.get("file", "unknown")
        output = (
            f"⚡ POSSIBLE ROUTING: This request may match `{ref}`. "
            f"Verify with the user before proceeding if intent is unclear."
        )

    else:
        options = " / ".join(f"`{i['id']}`" for i in low_matches[:4])
        matched_id = "ambiguous"
        output = (
            f"⚡ AMBIGUOUS INTENT: This request may match multiple procedures: {options}. "
            f"Ask the user which they want before proceeding."
        )

    if output:
        print(output)
        _log(matched_id, "matched", prompt)


if __name__ == "__main__":
    timer = threading.Timer(TIMEOUT_SECS, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    try:
        main()
    except Exception:
        pass
    finally:
        timer.cancel()
```

- [ ] **Step 6.4: Run tests — verify they pass**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -m pytest tests/test_skill_router.py -v
```

Expected: all tests pass. If inline tests fail because procedure files don't exist at `~/.claude/procedures/inline/` yet, that's expected — they'll be resolved in Task 8.

- [ ] **Step 6.5: Commit**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add hook-scripts/skill-router.py tests/test_skill_router.py
git commit -m "feat: add skill-router UserPromptSubmit hook with tests"
```

---

## Task 7: Test Fixtures

**Files:**
- Create: `tests/router-fixtures.jsonl`

- [ ] **Step 7.1: Create fixtures**

Create `/Users/Shared/Code/jintech-omg-dev/tests/router-fixtures.jsonl`:

```jsonl
{"prompt": "address the PR comments", "expected_intent": "pr-comments-address"}
{"prompt": "address PR review comments", "expected_intent": "pr-comments-address"}
{"prompt": "respond to the review comments", "expected_intent": "pr-comments-address"}
{"prompt": "fetch the PR comments", "expected_intent": "pr-comments-fetch"}
{"prompt": "show me the review comments on this PR", "expected_intent": "pr-comments-fetch"}
{"prompt": "create a PR", "expected_intent": "pr-create"}
{"prompt": "raise a PR for this branch", "expected_intent": "pr-create"}
{"prompt": "open a draft PR", "expected_intent": "pr-create"}
{"prompt": "rebase this branch onto master", "expected_intent": "pr-rebase"}
{"prompt": "rebase the PR", "expected_intent": "pr-rebase"}
{"prompt": "OMGXI-9400", "expected_intent": "ticket-id-direct"}
{"prompt": "look into ticket OMGXI-9400", "expected_intent": "ticket-investigate"}
{"prompt": "investigate OMGXI-1234", "expected_intent": "ticket-investigate"}
{"prompt": "what's the ticket status", "expected_intent": "ticket-status"}
{"prompt": "add a comment to the ticket", "expected_intent": "ticket-comment"}
{"prompt": "post a note on the ticket", "expected_intent": "ticket-comment"}
{"prompt": "transition ticket to in progress", "expected_intent": "ticket-transition"}
{"prompt": "move ticket to done", "expected_intent": "ticket-transition"}
{"prompt": "start implementing the plan", "expected_intent": "implement"}
{"prompt": "run prepr", "expected_intent": "prepr"}
{"prompt": "check before raising PR", "expected_intent": "prepr"}
{"prompt": "debug this error", "expected_intent": "debug"}
{"prompt": "something's broken in the login flow", "expected_intent": "debug"}
{"prompt": "grill me on this design", "expected_intent": "grill-me"}
{"prompt": "review the diff", "expected_intent": "code-review"}
{"prompt": "what changed in this branch", "expected_intent": "git-branch-summary"}
{"prompt": "what's in this branch", "expected_intent": "git-branch-summary"}
{"prompt": "save the session", "expected_intent": "session-save"}
{"prompt": "resume where we left off", "expected_intent": "session-resume"}
{"prompt": "commit this", "expected_intent": "commit"}
{"prompt": "I already finished OMGXI-9400", "expected_intent": null}
{"prompt": "don't implement yet, just plan", "expected_intent": null}
{"prompt": "/ticket OMGXI-9400", "expected_intent": null}
{"prompt": "the PR description says it should work", "expected_intent": null}
{"prompt": "something was not working before the fix", "expected_intent": null}
{"prompt": "what time is it in Tokyo", "expected_intent": null}
```

- [ ] **Step 7.2: Write fixture runner**

Add to `tests/test_skill_router.py` (append at end of file):

```python
class TestFixtures:
    """Run all router-fixtures.jsonl entries through the hook."""

    def test_all_fixtures(self):
        fixtures_path = Path(__file__).parent / "router-fixtures.jsonl"
        fixtures = [json.loads(line) for line in fixtures_path.read_text().splitlines() if line.strip()]

        failures = []
        for f in fixtures:
            prompt = f["prompt"]
            expected = f["expected_intent"]
            out, _ = run_router(prompt)

            if expected is None:
                if "ROUTING ACTIVE" in out or "PROCEDURE ACTIVE" in out:
                    failures.append(f"FALSE POSITIVE: '{prompt}' → got output: {out[:80]}")
            else:
                if expected not in out:
                    failures.append(f"MISSED: '{prompt}' → expected '{expected}' in output, got: {out[:80]}")

        if failures:
            raise AssertionError("\n" + "\n".join(failures))
```

- [ ] **Step 7.3: Run all tests including fixtures**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -m pytest tests/test_skill_router.py -v
```

Expected: all pass. Fix any failing patterns in `skill-routing-manifest.json` before continuing.

- [ ] **Step 7.4: Commit**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git add tests/router-fixtures.jsonl tests/test_skill_router.py
git commit -m "test: add router fixture suite (36 prompts) and fixture runner"
```

---

## Task 8: Wire Hooks + User-Level Setup

**Files:**
- Modify: `~/.claude/settings.json` (global user settings)
- Modify: `~/.claude/procedures/inline/` (copy/symlink procedure files)

- [ ] **Step 8.1: Copy procedure files to user-level location**

```bash
mkdir -p ~/.claude/procedures/inline
cp /Users/Shared/Code/jintech-omg-dev/procedures/inline/*.md ~/.claude/procedures/inline/
ls ~/.claude/procedures/inline/
```

Expected: 7 `.md` files listed.

- [ ] **Step 8.2: Add skill-router hook to global settings.json**

Open `~/.claude/settings.json`. In the `hooks.UserPromptSubmit` array, add after the `caveman-mode-tracker` entry:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "\"/opt/homebrew/Cellar/node/25.8.2/bin/node\" \"~/.claude/hooks/caveman-mode-tracker.js\"",
      "timeout": 5,
      "statusMessage": "Tracking caveman mode..."
    },
    {
      "type": "command",
      "command": "python3 \"/Users/Shared/Code/jintech-omg-dev/hook-scripts/skill-router.py\"",
      "timeout": 5,
      "statusMessage": "Routing intent..."
    }
  ]
}
```

- [ ] **Step 8.3: Validate global settings.json is valid JSON**

```bash
python3 -c "import json; json.load(open('~/.claude/settings.json')); print('valid')"
```

Expected: `valid`

- [ ] **Step 8.4: Test kill switch works**

```bash
CLAUDE_SKILL_ROUTER_DISABLED=1 \
  echo '{"hook_event_name":"UserPromptSubmit","prompt":"address the PR comments","session_id":"x","transcript_path":"/tmp","cwd":"/tmp"}' \
  | python3 /Users/Shared/Code/jintech-omg-dev/hook-scripts/skill-router.py
echo "Exit: $?"
```

Expected: no output, exit 0.

- [ ] **Step 8.5: Test hook fires correctly**

```bash
echo '{"hook_event_name":"UserPromptSubmit","prompt":"address the PR comments","session_id":"x","transcript_path":"/tmp","cwd":"/tmp"}' \
  | python3 /Users/Shared/Code/jintech-omg-dev/hook-scripts/skill-router.py
```

Expected: prints `⚡ PROCEDURE ACTIVE: pr-comments-address` followed by procedure content.

---

## Task 9: Plugin Update + Final Validation

- [ ] **Step 9.1: Commit any remaining changes and push plugin source**

```bash
cd /Users/Shared/Code/jintech-omg-dev
git status
git push
```

- [ ] **Step 9.2: Update plugin cache**

In Claude Code, run:
```
! /plugin update jintech-omg-dev
```

Wait for confirmation that the plugin updated successfully.

- [ ] **Step 9.3: Verify JAM fixes in cache**

```bash
grep -c "JAM-MCP" ~/.claude/plugins/cache/jintech-claude-marketplace/jintech-omg-dev/*/skills/ticket/SKILL.md
grep -c "JAM-MCP" ~/.claude/plugins/cache/jintech-claude-marketplace/jintech-omg-dev/*/skills/debug/SKILL.md
```

Expected: both return `0`.

- [ ] **Step 9.4: Verify permissions in cache**

```bash
python3 -c "
import json, glob
files = glob.glob('~/.claude/plugins/cache/jintech-claude-marketplace/jintech-omg-dev/*/settings.json')
d = json.load(open(files[0]))
mcp = [x for x in d['permissions']['allow'] if x.startswith('mcp__')]
print(f'{len(mcp)} MCP permissions')
missing = [t for t in ['get_affected_flows_tool','get_review_context_tool','find_large_functions_tool','get_knowledge_gaps_tool'] if not any(t in x for x in mcp)]
print('Still missing:', missing or 'none')
"
```

Expected: `29 MCP permissions`, `Still missing: none`

- [ ] **Step 9.5: End-to-end routing test in a real session**

Start a new Claude Code session. Type (without slash):
```
address the PR comments
```

Expected: Claude sees `⚡ PROCEDURE ACTIVE: pr-comments-address` in context and follows the procedure steps.

Verify audit log was written:
```bash
ls ~/.claude/logs/intent-router-*.jsonl
tail -3 ~/.claude/logs/intent-router-$(date +%Y-%m-%d).jsonl
```

- [ ] **Step 9.6: Fix C — Review stale CLAUDE.md skill paths**

Open `~/.claude/CLAUDE.md`. Find the `## Skills` section. Each skill entry has a path like:
```
- **ticket** (`/Users/Shared/Code/.claude/skills/ticket/SKILL.md`)
```

That directory no longer contains these skills (only `graphify` remains). Replace each path reference with the plugin location note. Example replacement:

```markdown
- **ticket** (loaded via `jintech-omg-dev` plugin — `jintech-omg-dev:ticket`) - investigates a Jira ticket...
```

Repeat for: implement, prepr, pr, grill-me, debug.

This is a manual review step — read the section, update the paths, verify no broken references remain.

- [ ] **Step 9.7: Run full test suite one final time**

```bash
cd /Users/Shared/Code/jintech-omg-dev
python3 -m pytest tests/test_skill_router.py -v
```

Expected: all 36+ tests pass.

---

## Definition of Done Checklist

- [ ] `skill-router.py` written, wired in `~/.claude/settings.json`, 36 fixtures passing
- [ ] `enforce-skill-usage.py` written, wired in plugin `settings.json`
- [ ] `skill-routing-manifest.json` created with 21 routes, valid JSON
- [ ] All 7 inline procedure files created in plugin + copied to `~/.claude/procedures/inline/`
- [ ] `tests/router-fixtures.jsonl` created with 36 entries, all passing
- [ ] JAM tool names grep-replaced — `grep "JAM-MCP" skills/` returns nothing
- [ ] `settings.json` permissions: 3 corrected + 13 added (29 total MCP entries)
- [ ] Plugin cache updated via `/plugin update`
- [ ] Audit log at `~/.claude/logs/intent-router-YYYY-MM-DD.jsonl` written on first matched prompt
- [ ] Kill switch `CLAUDE_SKILL_ROUTER_DISABLED=1` tested — hook exits silently
- [ ] `~/.claude/CLAUDE.md` stale skill paths reviewed and updated
