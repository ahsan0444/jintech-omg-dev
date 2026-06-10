# Jintech OMG Dev — Agent Instruction Layer

This file is loaded automatically by Claude Code when the `jintech-omg-dev` plugin is active. It governs how Claude behaves across all OMG development sessions.

---

## Model Ladder

| Task | Model | Subagent type |
|---|---|---|
| File reads, greps, ticket fetches, test runs | `haiku` | `Explore` |
| Plan synthesis, orchestration, simple/medium edits | `sonnet` | `general-purpose` or main context |
| Complex/architectural edits, hard debugging | `opus` | `general-purpose` |

Default to the cheapest model that can do the job. Never spend Opus on a pure read.

---

## Session Discipline

**One phase = one fresh session.** The pipeline is:

```
/grill-me (optional)  →  /ticket  →  /implement  →  /prepr  →  /pr
```

- Each skill hands off via a saved artifact (`.planning/` files), not in-session state.
- Exception: `/grill-me` may flow directly into `/ticket` in the same session if the user confirms.
- After `/implement` completes, the approved plan file is deleted — always start `/prepr` fresh.

---

## Subagent Discipline

- **Orchestrate, don't gather.** Main context is for decisions and synthesis only. All reads, greps, MCP calls, and file edits happen inside subagents.
- **Never re-read.** If a subagent returned a file path and line range, trust it. Do not open that file again in main context or in another subagent.
- **Locations, not contents.** Subagents return paths and line ranges — not file contents. The one exception: up to 20 lines when diagnosing a failed edit.
- **No file reads in subagents.** Subagents must not use sed, cat, Read, head, tail, less, or full-file grep patterns.
- **Parallel by default.** When steps have no dependencies, spawn them all in one message.

---

## MCP Search Policy (OMG repos only)

When working inside `omg/lib/`, `omg/public/javascripts/`, or `omg/t/`:

- Use `code-review-graph` MCP tools first, always.
- Grep is blocked in those directories by the `enforce-mcp-search` hook.
- `views/` (Template Toolkit) is exempt — grep is permitted there since MCP has no TT coverage.
- If all MCP searches return 0 results: set CONFIDENCE: low. Do not fall back to grep in covered dirs.

MCP tools:
- `semantic_search_nodes_tool` — find by name/keyword
- `query_graph_tool` — trace callers, callees, imports, tests
- `traverse_graph_tool` — BFS/DFS when semantic search misses
- `get_impact_radius` — blast radius before editing
- `detect_changes` — risk-scored analysis of uncommitted changes

---

## OMG Architecture — Layer Rules

| Layer | File pattern | Rule |
|---|---|---|
| DAO | `*_db.pm` in `lib/*/dao/` | Return unblessed hashes/arrays only. No `bless()`, no `->new()` in returns. |
| DOM | `*_dom.pm` in `lib/*/dom/` | Must have `sub TO_JSON { return { %{ shift() } }; }` |
| Helper | `*_helper.pm` | Sole public API. No foreign `_controller->` or `_db->` calls. |
| Controller | `*_controller.pm` | Calls helpers only. No direct DAO imports, no foreign controller calls. |
| Route | `OMG*.pm` | `OMG_ajax.pm` contains AJAX routes only — no `template` or `redirect`. |

---

## Project Roots (OMG workspace)

```
/Users/Shared/Code/omg          — primary Perl/TT/JS app
/Users/Shared/Code/omg_db       — PostgreSQL schema companion
/Users/Shared/Code/omg_ice      — ICE reporting
/Users/Shared/Code/omg-docker   — Docker (GitLab — no Bitbucket PR)
```

Repo detection falls back through this list in order if `git rev-parse` fails from cwd.
The parent dir is `$OMG_WORKSPACE_ROOT` (default `/Users/Shared/Code`); the Bitbucket workspace slug is `$OMG_BITBUCKET_WORKSPACE` (default `zlalani`). Honour these env vars — never hardcode either value in new commands or edits.

---

## Planning Artifacts

| File | Written by | Read by | Deleted by |
|---|---|---|---|
| `.planning/grill-TICKET.md` | `/grill-me` | `/ticket` (auto-load) | Never (manual) |
| `.planning/approved-plan-TICKET.md` | `/ticket` | `/implement` | `/implement` on completion |

---

## Bitbucket Workspace

All OMG repos use workspace `zlalani` on Bitbucket Cloud.
`omg-docker` is on GitLab — never raise a Bitbucket PR for it.

Required environment variables:
- `BITBUCKET_USER` — your Bitbucket username
- `BITBUCKET_TOKEN` — Bitbucket app password with PR read/write scope

---

## Active Hooks (plugin-registered)

| Hook | Event | Behaviour |
|---|---|---|
| `skill-router` | UserPromptSubmit | Injects routing instructions for matched intents. A routing instruction is a strong hint — if the matched skill clearly does not fit the user's actual request, say so and proceed with the right approach instead of force-running it. |
| `enforce-mcp-search` | PreToolUse | Denies grep in MCP-covered dirs — follow the deny message's MCP steps; do not retry grep verbatim. |
| `enforce-skill-usage` | PreToolUse | Denies `gh pr create` — use `/pr`. |
| `post-edit-update` | PostToolUse | Auto-updates the code graph after source edits — no action needed. |
| `session-start-status` | SessionStart | Prints graph status — if it reports staleness, suggest `code-review-graph update`. |

---

## Never Do

- Read minified/compiled JS (`*.min.js`, bundled Bryntum sources)
- Read the full `graph.db` — use MCP tools only
- Implement in a `/ticket` session
- Investigate in an `/implement` session
- Create a PR for `omg-docker` (GitLab repo)
- Amend published commits
- Force-push without `--force-with-lease`
