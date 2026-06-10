# jintech-omg-dev

Claude Code plugin for Jintech OMG development. Bundles the full SDLC skill pipeline, the code-review-graph MCP server, and enforcement hooks into a single installable unit.

**Supports macOS and Windows.**

---

## What's included

| Component | What it does |
|---|---|
| `/ticket` | Investigates a Jira ticket via subagents, produces a Plan Mode proposal |
| `/implement` | Executes an approved plan via subagents with TDD and layer compliance |
| `/prepr` | Pre-PR audit: Perl::Critic, OMG layer conventions, TT/JS/SQL/SCSS |
| `/pr` | Creates a Bitbucket draft PR, posts PR link back to Jira |
| `/grill-me` | Stress-tests a design/plan before /ticket runs |
| `/debug` | Root cause analysis — traces, ranks hypotheses, routes to /implement or /ticket |
| `code-review-graph` MCP | Semantic graph of 9k+ nodes, 78k+ edges across the OMG codebase — 14 tools wired into skills |
| Hooks | `skill-router` (UserPromptSubmit), `enforce-mcp-search` + `enforce-skill-usage` (PreToolUse), `post-edit-update` (PostToolUse), `session-start-status` (SessionStart) — all registered automatically via `hooks/hooks.json` |
| Commands | `/learn`, `/save-session`, `/resume-session`, `/embed-graph`, `/router-stats` |
| Routing manifest | `skill-routing-manifest.json` — regex intents → skills/inline procedures (see Hooks below) |
| Agents | `omg-investigator` (read-only locator — no Read/Edit/Write tools, MCP-graph-first) and `omg-implementer` (single-step executor — OMG layer rules + TDD baked into its system prompt). Skills spawn these instead of generic `Explore`/`general-purpose`, turning "no file reads in subagents" from a prompt rule into a tool permission. |

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
/prepr                    # pre-PR audit
/prepr fix                # audit + auto-fix warnings
/pr                       # create Bitbucket draft PR
/debug OMGXI-1234         # root cause analysis
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

## Hooks

All hooks register automatically from `hooks/hooks.json` when the plugin is enabled. Every hook fails open — a broken or missing script never blocks your tools.

| Hook | Event | What it does |
|---|---|---|
| `skill-router` | UserPromptSubmit | Matches natural-language prompts against `skill-routing-manifest.json` and injects a routing instruction (e.g. "create a PR" → `/pr`). Kill switch: `export CLAUDE_SKILL_ROUTER_DISABLED=1`. Override the manifest by copying it to `~/.claude/skill-routing-manifest.json` or setting `SKILL_ROUTER_MANIFEST_OVERRIDE`. Prefix a prompt with `\` to bypass routing once. |
| `enforce-mcp-search` | PreToolUse (Grep/Bash) | Denies grep inside `lib/`, `public/javascripts/`, `t/` of a repo with a built code-review-graph — directs Claude to MCP tools instead. `views/` is exempt. |
| `enforce-skill-usage` | PreToolUse (Bash) | Denies `gh pr create` (OMG uses Bitbucket) and points to `/pr`. |
| `post-edit-update` | PostToolUse (Edit/Write) | Incremental `code-review-graph update` after source-file edits. Skips docs/config edits. |
| `session-start-status` | SessionStart | Prints graph health (node count, staleness) into context at session start. |

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
