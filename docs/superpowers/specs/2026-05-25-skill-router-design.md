# Skill Router & Plugin Fixes — Design Spec
date: 2026-05-25
status: approved (v2 — post-Opus review)

---

## Problem

Natural language requests ("address the PR comments", "rebase the branch", "what's in this ticket") cause Claude to use raw training knowledge instead of the team's defined skill procedures. Skills only fire on explicit `/command` invocation. The gap produces inconsistent, off-script behaviour for all common dev actions.

Additionally, the jintech-omg-dev plugin has confirmed blockers: wrong JAM tool names and missing/malformed MCP permissions that silently break /ticket, /debug, /pr, /prepr, and /grill-me.

---

## Goals

1. Route all recognized natural-language dev intents to the correct skill or inline procedure — deterministically, without the user typing `/command`.
2. Fix all confirmed blockers in the jintech-omg-dev plugin.
3. Zero friction when no intent is matched — hook must fail-open.
4. Extensible: adding new routes requires editing one config file only.

---

## Architecture

```
User natural language message
        ↓
UserPromptSubmit → skill-router.py
        ↓  reads skill-routing-manifest.json
        ↓  4-stage pipeline:
        │   Stage 0: CLAUDE_SKILL_ROUTER_DISABLED=1 → silent pass
        │   Stage 1: prompt starts with "/" or "\" → silent pass (user chose)
        │   Stage 2: high-confidence keyword match → inject Tier 1 or Tier 2
        │   Stage 3: ambiguous match → inject clarification menu
        ↓  emits plain stdout text (non-JSON) → injected as system-reminder
Claude sees routing directive as <system-reminder>
        ↓
Follows inline procedure OR invokes skill via Skill tool
        ↓
PreToolUse backstop (v1: scope limited — see Component 4)
```

---

## Components

### 1. `hook-scripts/skill-router.py`

**Location:** `/Users/Shared/Code/jintech-omg-dev/hook-scripts/skill-router.py`
**Hook type:** `UserPromptSubmit`

**Stdin schema (actual Claude Code format):**
```json
{
  "hook_event_name": "UserPromptSubmit",
  "session_id": "...",
  "transcript_path": "...",
  "cwd": "...",
  "prompt": "..."
}
```
Read `data["prompt"]`, not `data["message"]`.

**Stdout output (plain text, not JSON):**
Claude Code injects non-JSON stdout from `UserPromptSubmit` hooks directly as context. Emit plain text — no JSON wrapper needed. Example:
```
⚡ ROUTING ACTIVE: ...
```

**Behaviour:**
- Hard timeout enforced by the script itself via `threading.Timer` — kill process at 500ms (python3 cold start + I/O can exceed 100ms; 500ms is the safe budget)
- Any exception → `sys.exit(0)` (fail-open, never block input)
- Load manifest from `~/.claude/skill-routing-manifest.json`; if missing, fall back to `$CLAUDE_PLUGIN_ROOT/skill-routing-manifest.json` (default shipped with plugin)
- Append `{timestamp, prompt_hash, matched_intent, action_type}` to `~/.claude/logs/intent-router-YYYY-MM-DD.jsonl` (daily rotation, 10MB cap before roll)
- Kill switch: check `os.environ.get("CLAUDE_SKILL_ROUTER_DISABLED")` first — if set, `sys.exit(0)`

**4-stage pipeline:**
```
Stage 0: CLAUDE_SKILL_ROUTER_DISABLED is set → exit 0
Stage 1: prompt starts with "/" or "\" → exit 0
Stage 2: scan manifest intents in order (high-confidence only first)
         → first high-confidence match wins → inject Tier 1 or Tier 2
Stage 3: if no high match → scan low-confidence
         decision matrix:
           0 low  → silent
           1 low  → inject with hedge ("possible match — verify")
           2+ low → inject clarification menu
```

**Tie-breaking for high-confidence matches:** first entry in manifest wins. Document this in manifest comments — order is significant.

**Output format (Tier 1 — skill redirect):**
```
⚡ ROUTING ACTIVE: The user's request matches the `<skill>` skill.
You MUST invoke the Skill tool with skill="<plugin:skill>" before doing anything else.
Do not improvise the steps. The skill defines the exact procedure.
```

**Output format (Tier 2 — inline procedure):**
```
⚡ PROCEDURE ACTIVE: <intent-id>
<full procedure file content>
Follow these steps exactly. Do not deviate.
```
If procedure file is missing → log warning, emit nothing, `sys.exit(0)`.

---

### 2. `skill-routing-manifest.json`

**Shipped with plugin at:** `jintech-omg-dev/skill-routing-manifest.json` (default)
**User override at:** `~/.claude/skill-routing-manifest.json` (takes precedence if present)

Config-driven routing table. New routes = edit manifest only. Order is significant — first high-confidence match wins.

**Structure:**
```json
{
  "_comment": "Order matters: first high-confidence match wins.",
  "intents": [
    {
      "id": "<kebab-case-verb-object>",
      "patterns": ["<python regex>"],
      "confidence": "high | low",
      "action": {
        "type": "skill | inline",
        "skill": "jintech-omg-dev:pr",
        "file": "~/.claude/procedures/inline/pr-address-comments.md"
      }
    }
  ]
}
```

**Full initial routing table (17 routes + 3 additions from review):**

| Intent ID | Sample pattern | Confidence | Action |
|---|---|---|---|
| `pr-create` | `\b(create\|raise\|open\|draft)\s+(a\s+)?pr\b` | high | skill: `jintech-omg-dev:pr` |
| `pr-update` | `\bupdate\b.*\bpr\b(?!.*description says)` | high | skill: `jintech-omg-dev:pr` |
| `pr-rebase` | `\brebase\b.*\b(pr\|branch\|onto)\b` | high | skill: `jintech-omg-dev:pr` |
| `pr-comments-address` | `\b(address\|respond to\|handle)\b.*\b(pr\|review)\s+comments?\b` | high | inline: `pr-address-comments.md` |
| `pr-comments-fetch` | `\bfetch\b.*\b(review\|pr)\s+comments?\b\|\bshow\b.*\bpr\b.*\bcomments?\b` | high | inline: `pr-fetch-comments.md` |
| `ticket-investigate` | `\b(investigate\|look into\|work on\|start on)\b.*\bticket\b` | high | skill: `jintech-omg-dev:ticket` |
| `ticket-id-direct` | `\bOMGXI-[0-9]+\b(?!.*already\|.*finished\|.*fixed\|.*closed)` | high | skill: `jintech-omg-dev:ticket` |
| `ticket-status` | `\b(what.?s\|check)\b.*\bticket\b.*\bstatus\b\|\bticket\b.*\bstatus\b` | high | inline: `ticket-status.md` |
| `ticket-comment` | `\b(add\|post)\b.*\b(comment\|note)\b.*\bticket\b` | high | inline: `ticket-comment.md` |
| `ticket-transition` | `\b(transition\|move\|set)\b.*\bticket\b.*\b(in.?progress\|done\|review\|to.?do)\b` | high | inline: `ticket-transition.md` |
| `implement` | `\bimplement\b.*\bplan\b\|\b(start\|begin)\b.*\bimplementing\b(?!.*don.?t\|.*not yet)` | high | skill: `jintech-omg-dev:implement` |
| `prepr` | `\bpre.?pr\b\|\b(check\|run)\b.*\bbefore\b.*\bpr\b` | high | skill: `jintech-omg-dev:prepr` |
| `debug` | `\b(debug\|diagnose)\b.*\bthis\b\|\bsomething.?s broken\b(?!.*was\|.*before)` | high | skill: `jintech-omg-dev:debug` |
| `grill-me` | `\bgrill\b.*\b(me\|my\|this)\b\|\bstress.?test.*plan\b` | high | skill: `jintech-omg-dev:grill-me` |
| `code-review` | `\breview\b.*\b(diff\|code\|branch\|changes)\b` | high | skill: `code-review` |
| `verify` | `\bverify\b.*\b(works?\|change\|fix\|this)\b(?!.*can you\|.*does it)` | high | skill: `verify` |
| `git-branch-summary` | `\bwhat.?s in\b.*\bbranch\b\|\bwhat.*changed\b.*\bbranch\b` | high | inline: `git-branch-summary.md` |
| `session-resume` | `\b(resume\|continue\|pick up)\b.*\b(session\|where)\b` | high | skill: `jintech-omg-dev:resume-session` |
| `session-save` | `\b(save\|record)\b.*\b(session\|progress\|where we)\b` | high | skill: `jintech-omg-dev:save-session` |
| `commit` | `\b(commit\b.*\bthis\|write.*commit.*message\|make.*commit)\b(?!.*don.?t\|.*not yet)` | high | skill: `caveman:caveman-commit` |
| `help-skills` | `\bwhat skills\b\|\bwhat can you do\b\|\blist.*skills\b\|\bavailable.*commands\b` | low | inline: `help-skills.md` |

**Notes on false-positive mitigations applied:**
- Negative lookaheads on past-tense/negation contexts (`already`, `finished`, `don't`, `not yet`, `was`)
- `pr-update` excludes "the PR description says" (informational)
- `ticket-id-direct` split from `ticket-investigate` with negation guard
- `verify` excludes interrogative form "can you confirm"

---

### 3. Inline procedure files

**Location:** `~/.claude/procedures/inline/` (user-level, not in plugin)
**Plugin default copies:** `jintech-omg-dev/procedures/inline/` (populated on install)

Each file: max 30 lines, single clear purpose, ≤3 decision points. If more → promote to a skill.

Files to create (8 total — added `help-skills.md`):
- `pr-address-comments.md` — fetch unresolved Bitbucket comments, group by file, apply changes, mark resolved
- `pr-fetch-comments.md` — fetch and display unresolved review comments from Bitbucket API
- `ticket-status.md` — get ticket ID from branch/context, fetch via Atlassian MCP, show status + summary
- `ticket-comment.md` — post comment via Atlassian MCP (`addCommentToJiraIssue`)
- `ticket-transition.md` — fetch transitions, apply target transition via Atlassian MCP (`transitionJiraIssue`)
- `git-branch-summary.md` — `git diff --stat` + `git log --oneline` vs `origin/master`, formatted output
- `help-skills.md` — list all available skills and their trigger phrases

**Note:** `pr-rebase.md` removed — rebase logic already lives inside `/pr` skill (Step 8). Route `pr-rebase` → `jintech-omg-dev:pr` instead.

---

### 4. PreToolUse backstop — v1 scope

**v1 is limited to one safe case only:** block `gh pr create` (GitHub CLI), since OMG uses Bitbucket not GitHub. This is unambiguous — `gh pr create` is always wrong in this project.

All other backstop patterns are deferred to v2 after audit log data shows real misfire patterns. Reason: blocking `curl` or `git push` unconditionally would break the `/pr` skill itself.

```python
# Only block gh pr create (wrong platform)
if tool == "Bash" and "gh pr create" in command:
    print("BLOCKED: OMG uses Bitbucket, not GitHub. Use /pr skill instead.")
    sys.exit(2)
```

This is added as a new file: `hook-scripts/enforce-skill-usage.py` (separate from `enforce-mcp-search.py`).

---

### 5. `settings.json` — hook wiring

**Global `~/.claude/settings.json`** — add to `UserPromptSubmit` hooks array after `caveman-mode-tracker`:
```json
{
  "type": "command",
  "command": "python3 /Users/Shared/Code/jintech-omg-dev/hook-scripts/skill-router.py",
  "timeout": 5,
  "statusMessage": "Routing intent..."
}
```

**Plugin `settings.json` (`/Users/Shared/Code/jintech-omg-dev/settings.json`)** — add to `PreToolUse` hooks:
```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"/Users/Shared/Code/jintech-omg-dev/hook-scripts/enforce-skill-usage.py\""
    }
  ]
}
```

**Skill name format:** verified — Claude Code `Skill` tool accepts `plugin:skill` form e.g. `jintech-omg-dev:pr`. Use this form in all injected directives.

---

## Plugin Bug Fixes

### Fix A — JAM tool naming (`ticket/SKILL.md`, `debug/SKILL.md`)

Grep-replace all occurrences (do not rely on line numbers — they drift):
```
mcp__JAM-MCP__getVideoTranscript   → mcp__Jam__getVideoTranscript
mcp__JAM-MCP__getUserEvents        → mcp__Jam__getUserEvents
mcp__JAM-MCP__getConsoleLogs       → mcp__Jam__getConsoleLogs
mcp__JAM-MCP__getNetworkRequests   → mcp__Jam__getNetworkRequests
mcp__JAM-MCP__getScreenshots       → mcp__Jam__getScreenshots
```

Files: `skills/ticket/SKILL.md`, `skills/debug/SKILL.md`

---

### Fix B — `settings.json` MCP permissions

**Location:** `/Users/Shared/Code/jintech-omg-dev/settings.json` → `permissions.allow` array.

Correct 3 malformed entries (wrong names, missing `_tool` suffix):
```json
"mcp__code-review-graph__get_architecture_overview_tool",
"mcp__code-review-graph__get_impact_radius_tool",
"mcp__code-review-graph__detect_changes_tool"
```
(replace the versions without `_tool`)

Add 13 missing entries to `permissions.allow`:
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

---

### Fix C — Global CLAUDE.md stale skill paths

`~/.claude/CLAUDE.md` has `skills` section with paths like `/Users/Shared/Code/.claude/skills/ticket/SKILL.md`. That directory only contains `graphify`. Skills are now served by the jintech-omg-dev plugin.

**This is a user-decision fix** — not automated. The implementation plan will note: "User should review `~/.claude/CLAUDE.md` skills section and replace path references with the note that skills are loaded via the `jintech-omg-dev` plugin."

---

## Test Fixtures

File: `jintech-omg-dev/tests/router-fixtures.jsonl`

Each line: `{"prompt": "...", "expected_intent": "<id or null>"}`. Minimum 20 entries covering true positives, true negatives, and negation cases. The implementation must create this file and the hook must pass all fixtures before DoD is met.

---

## Deployment Order

1. Fix plugin source (`/Users/Shared/Code/jintech-omg-dev`): Fix A, Fix B, new hook scripts, manifest, procedures
2. Commit + push plugin source
3. Run `! /plugin update jintech-omg-dev` to sync cache
4. Create `~/.claude/procedures/inline/` files (or symlink from plugin default copies)
5. Update global `~/.claude/settings.json` to wire `skill-router.py` hook
6. Set `CLAUDE_SKILL_ROUTER_DISABLED=1` in shell, start new session, verify plugin fixes work
7. Unset env var, test routing with 3+ natural language prompts, verify audit log written
8. User reviews and updates `~/.claude/CLAUDE.md` skill section (Fix C)

---

## Definition of Done

- [ ] `skill-router.py` written, wired in global `~/.claude/settings.json`
- [ ] `enforce-skill-usage.py` written, wired in plugin `settings.json`
- [ ] `skill-routing-manifest.json` created (20 routes) — shipped with plugin + user override path documented
- [ ] All 7 inline procedure files created in `~/.claude/procedures/inline/`
- [ ] `tests/router-fixtures.jsonl` created with ≥20 fixtures, all passing
- [ ] JAM tool names grep-replaced in `ticket/SKILL.md` and `debug/SKILL.md`
- [ ] `settings.json` permissions: 3 corrected + 13 added
- [ ] Plugin cache updated via `/plugin update`
- [ ] Audit log at `~/.claude/logs/intent-router-YYYY-MM-DD.jsonl` written on first matched prompt
- [ ] User has reviewed and updated `~/.claude/CLAUDE.md` stale skill paths
- [ ] Kill switch `CLAUDE_SKILL_ROUTER_DISABLED=1` tested — hook exits silently
