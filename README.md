# jintech-omg-dev

[![CI](https://github.com/ahsan0444/jintech-omg-dev/actions/workflows/ci.yml/badge.svg)](https://github.com/ahsan0444/jintech-omg-dev/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ahsan0444/jintech-omg-dev)](https://github.com/ahsan0444/jintech-omg-dev/releases)

Claude Code plugin for Jintech OMG development. Bundles the full SDLC skill pipeline, the code-review-graph MCP server, an autonomous verify trust core (product-graph + scripted assertion-based testing), and enforcement hooks into a single installable unit.

**Supports macOS, Linux, and Windows** (CI-tested on ubuntu and windows).

---

## What's included

| Component | What it does |
|---|---|
| `/ticket` | Investigates a Jira ticket via subagents, produces a Plan Mode proposal |
| `/implement` | Executes an approved plan via subagents with TDD and layer compliance |
| `/verify` | **Autonomous trust core** — proves a change does what it should (or reports NOT done with evidence). Tiered (cheap curl-first → scripted headless Playwright), assertion-based, never a green status on unverified work. See [Agent OS](#agent-os) below. |
| `/prepr` | Pre-PR audit: Perl::Critic, OMG layer conventions, TT/JS/SQL/SCSS |
| `/pr` | Creates a Bitbucket draft PR, posts PR link back to Jira |
| `/grill-me` | Stress-tests a design/plan before /ticket runs |
| `/debug` | Root cause analysis — traces, ranks hypotheses, routes to /implement or /ticket |
| `/agent-os-setup` | One-time per-machine bootstrap for the verify workflow (data home, registry, Playwright harness, auth capture). Cross-platform, idempotent. |
| `code-review-graph` MCP | Semantic graph of code **structure** (50k+ nodes across the OMG codebase) — 14 tools wired into skills |
| `product-graph` MCP | Semantic graph of product **behaviour** — routes, Template Toolkit inventory/includes, SCSS design tokens, registered features. Tools: `pg_feature`, `pg_selectors`, `pg_route`, `pg_design_tokens`, `pg_query`. Complements (does not duplicate) code-review-graph. |
| Hooks | `skill-router` (UserPromptSubmit), `enforce-mcp-search` + `enforce-skill-usage` (PreToolUse), `post-edit-update` + `record-graph-empty` (PostToolUse), `session-start-status` (SessionStart) — all registered automatically via `hooks/hooks.json` |
| Commands | `/learn`, `/save-session`, `/resume-session`, `/embed-graph`, `/router-stats` |
| Routing manifest | `skill-routing-manifest.json` — regex intents → skills/inline procedures (see Hooks below) |
| Agents | `omg-investigator` (read-only locator — no Read/Edit/Write tools, MCP-graph-first), `omg-implementer` (single-step executor — OMG layer rules + TDD baked in), and `omg-verifier` (isolated /verify executor — runs the harness, judges by assertions, bounded impl-only self-fix). Skills spawn these instead of generic `Explore`/`general-purpose`, turning "no file reads in subagents" from a prompt rule into a tool permission. |

---

## Prerequisites

| Requirement | macOS | Windows |
|---|---|---|
| Claude Code (latest stable) | ✅ | ✅ |
| Python 3.12+ (3.14 recommended) | ✅ | ✅ — install from [python.org](https://www.python.org/downloads/) or Microsoft Store; ensure `python3` is on PATH. **`code-review-graph` requires Python 3.12 minimum** — Python 3.9 will fail at install. |
| Git | ✅ | ✅ — [Git for Windows](https://git-scm.com/download/win) (includes Git Bash) |
| Perl + Perl::Critic | ✅ | ✅ — [Strawberry Perl](https://strawberryperl.com/) recommended |
| Bitbucket credentials | ✅ | ✅ |
| Jira/Atlassian MCP | ✅ | ✅ |

> **Windows note:** All hook scripts and the CRG server are written in Python — no bash required. `python3` must be on your PATH (verify with `python3 --version` in a terminal).

---

## Installation

### 1. Add the Jintech plugin marketplace

```
/plugin marketplace add https://github.com/ahsan0444/claude-marketplace
```

### 2. Install this plugin

```
/plugin install jintech-omg-dev
```

This will:
- Copy skills and commands into your Claude Code installation
- Register the `code-review-graph` MCP server (auto-installs via pip on first use)
- Wire up the lifecycle hooks

### 3. Set required environment variables

#### macOS / Linux — add to `~/.zshrc` or `~/.bashrc`

```bash
export BITBUCKET_USER="your-bitbucket-username"
export BITBUCKET_TOKEN="your-bitbucket-app-password"
```

Then run `source ~/.zshrc`.

> **Security:** Use a Bitbucket **app password scoped to Pull Requests read/write only** — never your account password. The plugin's curl calls pass credentials via stdin (`curl -K -`), so the token never appears in the process list. Rotate the token if a session transcript is ever shared.

#### Windows — add to your PowerShell profile (`$PROFILE`) or System Environment Variables

```powershell
$env:BITBUCKET_USER = "your-bitbucket-username"
$env:BITBUCKET_TOKEN = "your-bitbucket-app-password"
```

To persist across sessions, set them as **System Environment Variables**:
> Start → "Edit the system environment variables" → Environment Variables → New

#### Optional environment overrides (all platforms)

Defaults match the standard Jintech setup — set these only if your machine differs. This is the **single place** to relocate the workspace; no skill files need editing.

```bash
export OMG_WORKSPACE_ROOT="/Users/Shared/Code"   # parent dir of omg/omg_db/omg_ice checkouts (Windows Git Bash: /c/Code)
export OMG_BITBUCKET_WORKSPACE="zlalani"         # Bitbucket Cloud workspace slug
export CLAUDE_SKILL_ROUTER_DISABLED=1            # kill switch for prompt routing (unset = enabled)
```

### 4. Initialise the code-review-graph (first time per repo)

Navigate to your OMG checkout and run:

#### macOS
```bash
cd /Users/Shared/Code/omg
code-review-graph register . --alias omg   # register the repo with CRG
code-review-graph build                     # parse all files (~5-10 min)
```

#### Windows
```powershell
cd C:\Code\omg        # adjust to your checkout path
code-review-graph register . --alias omg
code-review-graph build
```

**Then enable semantic search (one-time, ~2-5 min):**

After the build completes, restart Claude Code (so the MCP server picks up the new graph), then run:

```
/embed-graph
```

This generates vector embeddings locally using `all-MiniLM-L6-v2` (no API key required). Without this step, MCP search falls back to keyword matching only.

> **Auto-embed:** The plugin detects missing embeddings on startup and triggers embedding in the background automatically. If the `/embed-graph` command reports "already embedded", no action needed.

Subsequent updates run automatically after each file edit via the `PostToolUse` hook.

---

## Usage

Skills are invoked by short name within an active OMG project session:

```
/grill-me OMGXI-1234     # optional pre-investigation alignment
/ticket OMGXI-1234        # investigate + produce approved plan
/implement                # execute the approved plan
/verify <feature>         # autonomously prove the change works (assertion-based)
/prepr                    # pre-PR audit
/prepr fix                # audit + auto-fix warnings
/pr                       # create Bitbucket draft PR
/debug OMGXI-1234         # root cause analysis
/agent-os-setup           # one-time per-machine setup for /verify
```

Or with the fully-qualified plugin namespace from any directory:

```
/jintech-omg-dev:ticket OMGXI-1234
```

---

## Pipeline

```
/grill-me (optional, Session 1)
    ↓  saves .planning/grill-TICKET.md
/ticket (Session 2)
    ↓  saves .planning/approved-plan-TICKET.md
/implement (Session 3)
    ↓  deletes approved-plan after completion
/verify (Session 3b)
    ↓  STATUS: PASS — assertion exercises the change
/prepr (Session 4)
    ↓  no blockers
/pr (Session 5)
```

Each skill is a fresh session. See [WORKFLOW.md](WORKFLOW.md) for full architecture diagrams.

---

## Code-review-graph

The MCP server starts automatically when the plugin activates. It self-installs `code-review-graph` from PyPI into a plugin-local venv on first run — no manual pip install needed.

It requires a built graph at `.code-review-graph/graph.db` in your project root (Step 4 above).

**Manual commands** (run from inside your OMG checkout):

```bash
code-review-graph status    # check graph health and node count
code-review-graph update    # incremental update (changed files only)
code-review-graph build     # full rebuild (~5–10 min)
```

**Auto-rebuild schedule:**

| Platform | Mechanism | Schedule |
|---|---|---|
| macOS | launchd (`com.omg.graphify-rebuild.plist`) | Every Monday 3am |
| Windows | Task Scheduler | Set up manually — see below |

#### Windows: set up weekly auto-rebuild

Run once in PowerShell (Admin):

```powershell
$action  = New-ScheduledTaskAction -Execute "code-review-graph" -Argument "build" -WorkingDirectory "C:\Code\omg"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 3am
Register-ScheduledTask -TaskName "OMG-GraphRebuild" -Action $action -Trigger $trigger -RunLevel Highest
```

Adjust `-WorkingDirectory` to match your OMG checkout path.

---

## Agent OS

Two layers on top of the SDLC pipeline:

1. **Product-knowledge graph** (`product-graph` MCP) — what the product *does* and *looks like*: routes (`OMG*.pm`), Template Toolkit inventory/includes, SCSS design tokens, and a hand-editable **registry** of features. Complements `code-review-graph` (code structure); never duplicates it.
2. **Autonomous verify trust core** (`/verify` + `omg-verifier`) — tiered, assertion-based, never false-done:
   - **Tier 1** (always, cheap): dev-server restart + readiness probe + `curl` endpoint asserts. Backend-only changes stop here.
   - **Tier 2** (when the diff touches `.tt`/`.scss`/`.js` or a UI route): a **scripted headless Playwright** spec (selectors/URL pulled from the graph + registry). Result = exit code + a tiny result file; the page never enters the model's context. Specs persist as regression tests.
   - **Definition of Done**: a passing assertion that exercises THE CHANGE — not "app loaded". On failure: behavioral → leave server up + edits intact + alert; infrastructural → revert to last-known-good + alert. Self-fix is implementation-only (a spec-tamper guard rejects any run that modified the test).

**The plugin ships the engine** (MCP server, skill, agent, harness under `servers/`). **Per-product data** (registry, auth, specs) lives outside any production repo in a data home at `~/.agent-os/`.

### Setup

Run once per machine:

```
/agent-os-setup
```

This scaffolds the data home, builds the product graph, installs the Playwright harness, and walks you through capturing an authenticated session. The data-home scaffold + a full step-by-step setup guide live in a separate repo — see **[jintech-agent-os](https://github.com/ahsan0444/jintech-agent-os)** — which you clone to `~/.agent-os` and fill with your environment's (non-secret) registry facts. Secrets (`.env.local`, captured auth state) are gitignored and never committed.

**The exact files you edit and commands you run are spelled out in that repo's README + `docs/`** (a "Manual configuration" checklist — nothing is left implicit). In short:

1. `git clone …/jintech-agent-os ~/.agent-os`
2. `cp config.yml.example config.yml` → set `repo_root` (and `db_repo_root`) to your checkout.
3. Edit `~/.agent-os/<repo>/registry/env` for your environment (`BASE_URL`, `RESTART_CMD`, `RESTART_CMD_FALLBACK` compose path, `APP_CONTAINER`, `HEALTH_URL`). Defaults target the Jintech `britvic` sandbox.
4. `/agent-os-setup` (installs harness deps + browsers, builds the product graph).
5. `node "$CLAUDE_PLUGIN_ROOT/servers/verify/capture-auth.mjs" --repo <repo>` → complete SSO once.

Prereqs: Node 18+, the dev app running locally, access to your environment's host. **No manual `npm install` after plugin updates** — the verify harness self-heals (`ensureDeps()` runs `npm ci` automatically if its `node_modules` is missing on a freshly-cloned cache).

---

## Companion plugins, MCP servers & tools

The plugin works on its own, but the full workflow expects a few companions. Commands below
are copy-paste. The **official Anthropic marketplace is auto-installed** in Claude Code, so
its plugins install by name (`<plugin>@claude-plugins-official`) with no `marketplace add`.

### Required

```bash
# 1. This plugin (its own marketplace)
/plugin marketplace add https://github.com/ahsan0444/claude-marketplace
/plugin install jintech-omg-dev

# 2. Atlassian — Jira reads for /ticket, /pr, and the issue-tracker skill
/plugin install atlassian@claude-plugins-official
#    then authenticate the Atlassian MCP when prompted (OAuth via claude.ai)

# 3. Bitbucket credentials for /pr (shell rc — see "Set required environment variables" above)
export BITBUCKET_USER="…"; export BITBUCKET_TOKEN="…"   # app password, PR read/write scope only
```

```bash
# 4. Postgres MCP — DB lookups used by /db-script and investigations.
#    Connection string = your local omg-docker Postgres (defaults shown).
claude mcp add postgres --scope user -- \
  npx -y @modelcontextprotocol/server-postgres postgresql://pgdev:pgdev@localhost:5432/OMG
```

### Recommended

```bash
# Greenfield UI lane (frontend-design skill referenced by Agent OS)
/plugin install frontend-design@claude-plugins-official

# context7 — third-party library docs (CLAUDE.md routes lib internals here, not file reads)
/plugin install context7@claude-plugins-official

# Jam — bug repro capture for /debug (HTTP MCP; authenticate in browser)
claude mcp add --transport http Jam https://mcp.jam.dev/mcp
```

### Optional / personal (safe to skip — not required by any skill)

These are in the maintainer's setup but **not** needed for the OMG workflow:

| Tool | What it is | Install |
|---|---|---|
| `caveman` | Token-compression response style | `/plugin marketplace add JuliusBrussee/caveman` → `/plugin install caveman@caveman` |
| `superpowers` | General-purpose skill pack | `/plugin install superpowers@claude-plugins-official` |
| `claude-code-setup` | Setup-recommender skill | `/plugin install claude-code-setup@claude-plugins-official` |
| RTK (Rust Token Killer) | Personal CLI proxy hook | external binary — maintainer-only, ignore |
| Figma / Stitch / Canva MCPs | Design connectors | via `/plugin` or claude.ai connectors, as needed |

### Host tools / libraries

| Tool | Required? | Notes |
|---|---|---|
| Node 18+ | ✅ | verify harness (Playwright) |
| Python 3.12+ | ✅ | code-review-graph + product-graph (plugin-local venv) |
| Podman + podman-compose | ✅ | the OMG dev container + `/verify` restart/readiness |
| `omg-docker` checkout | ✅ | the compose project the container runs from |
| Git | ✅ | repos + PR flow |
| Perl::Critic | — | **not** a host install — the `perlcritic` skill runs it inside the omg Podman container |
| Playwright browsers | auto | `/agent-os-setup` installs them; harness self-heals node_modules after updates |

---

## Hooks

All hooks register automatically from `hooks/hooks.json` when the plugin is enabled. Every hook fails open — a broken or missing script never blocks your tools.

| Hook | Event | What it does |
|---|---|---|
| `skill-router` | UserPromptSubmit | Matches natural-language prompts against `skill-routing-manifest.json` and injects a routing instruction (e.g. "create a PR" → `/pr`). Kill switch: `export CLAUDE_SKILL_ROUTER_DISABLED=1`. Override the manifest by copying it to `~/.claude/skill-routing-manifest.json` or setting `SKILL_ROUTER_MANIFEST_OVERRIDE`. Prefix a prompt with `\` to bypass routing once. |
| `enforce-mcp-search` | PreToolUse (Grep/Bash) | **Steerable**, self-releasing: defaults grep inside `lib/` and `public/javascripts/` to the code-review-graph, but sanctions grep for literal/multi-word patterns, when the graph is stale (build SHA ≠ HEAD), and after a graph query for the same target returned empty (a one-shot, query-scoped breadcrumb). `views/` is exempt. A single source's silence is a proposal, not proof. |
| `enforce-skill-usage` | PreToolUse (Bash) | Denies `gh pr create` (OMG uses Bitbucket) and points to `/pr`. |
| `post-edit-update` | PostToolUse (Edit/Write) | Incremental `code-review-graph update` after source edits; also rebuilds the **product-graph** on `.tt`/`.scss`/`OMG*.pm` edits. Skips docs/config edits. |
| `record-graph-empty` | PostToolUse (MCP graph tools) | Records a query-scoped breadcrumb when a code-review-graph / product-graph query returns empty, so `enforce-mcp-search` can sanction one follow-up grep for that target (TTL 15 min). |
| `session-start-status` | SessionStart | Prints code-review-graph health (node count, staleness) **and** product-graph status (routes/templates/tokens/features) into context at session start. |

> **Permissions template:** `settings.json` at the plugin root is a *template* — Claude Code does not load it from a plugin. Copy its `permissions.allow` block into your project's `.claude/settings.json` to pre-approve the read-only Bash and MCP calls the skills make.

> **Design note — router limits:** regex intent matching has a permanent false-positive tail (it matches *mentions*, not intent — e.g. a prompt *discussing* the prepr skill can route to it). Run `/router-stats` periodically and tighten noisy patterns. Longer term, prefer letting Claude pick skills from their `description` triggers and keep the router only for the inline procedures that have no skill equivalent; if a routing instruction clearly doesn't fit the request, Claude is instructed (CLAUDE.md) to say so and proceed correctly rather than force-run the skill.

---

## Updating the plugin

```
/plugin update jintech-omg-dev
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python3: command not found` (Windows) | Hooks invoke `python3` literally. python.org installs ship only `python.exe` — create a shim once: `copy "%LocalAppData%\Programs\Python\Python314\python.exe" "%LocalAppData%\Programs\Python\Python314\python3.exe"` (adjust path; the Microsoft Store build already provides `python3`). Verify with `python3 --version`. |
| `code-review-graph: command not found` | The plugin venv may not have activated — restart Claude Code (the MCP server self-installs on first start), or reinstall via `/plugin` → jintech-omg-dev |
| `code-review-graph` install fails on Python 3.9/3.10/3.11 | Requires Python 3.12+. On macOS: `brew install python@3.14`. On Windows: download from python.org and ensure it's on PATH |
| Hook not firing | Verify hooks are registered: check `.claude/settings.json` in your project |
| Graph DB missing | Run `code-review-graph build` from inside the OMG repo root |
| MCP tools return 0 results | Ensure graph is built and registered: `code-review-graph register /path/to/omg --alias omg` then verify with `code-review-graph status` |

---

## Contributing

Changes to skills, hooks, or the CRG server go through the standard OMG development pipeline. Raise a PR against [github.com/ahsan0444/jintech-omg-dev](https://github.com/ahsan0444/jintech-omg-dev).

For questions: #dev-tooling on Slack or raise a Jira ticket in the TOOLS project.
