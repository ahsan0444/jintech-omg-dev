# jintech-omg-dev

Claude Code plugin for Jintech OMG development. Bundles the full SDLC skill pipeline, the code-review-graph MCP server, and enforcement hooks into a single installable unit.

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
| `code-review-graph` MCP | Semantic graph of 49k+ nodes across the OMG codebase |
| Hooks | `enforce-mcp-search` (PreToolUse), `post-edit-update` (PostToolUse), `session-start-status` (SessionStart) |
| Commands | `/learn`, `/save-session`, `/resume-session` |

---

## Prerequisites

- Claude Code (latest stable)
- macOS or Linux
- Python 3.9+ (for the CRG server)
- Access to the Jintech private PyPI registry (`JINTECH_PYPI_URL` env var)
- Bitbucket credentials (`BITBUCKET_USER`, `BITBUCKET_TOKEN`)
- Jira/Atlassian MCP configured

---

## Installation

### 1. Add the Jintech plugin marketplace

```bash
/plugin marketplace add https://github.com/jintech/claude-marketplace
```

### 2. Install this plugin

```bash
/plugin install jintech-omg-dev
```

This will:
- Copy skills and commands into your Claude Code installation
- Register the `code-review-graph` MCP server
- Install hooks into your session lifecycle

### 3. Set required environment variables

Add to `~/.zshrc` (or `~/.bashrc`):

```bash
export JINTECH_PYPI_URL="https://pypi.jintech.com/simple"
export BITBUCKET_USER="your-bitbucket-username"
export BITBUCKET_TOKEN="your-bitbucket-app-password"
```

Restart your shell or run `source ~/.zshrc`.

### 4. Initialise the code-review-graph for each repo (first time only)

```bash
cd /Users/Shared/Code/omg
code-review-graph build
```

This takes ~5–10 minutes on first run. Subsequent updates are incremental (triggered automatically after each file edit).

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

Each skill is a fresh session. See [WORKFLOW.md](WORKFLOW.md) for architecture diagrams.

---

## Code-review-graph

The graph MCP server is started automatically when the plugin activates. It requires a built graph at `.code-review-graph/graph.db` in the project root.

Manual commands:

```bash
code-review-graph status    # check graph health
code-review-graph update    # incremental update (changed files only)
code-review-graph build     # full rebuild (~5-10 min)
```

The graph auto-updates after every file edit via the `PostToolUse` hook. Weekly full rebuilds run via launchd (Monday 3am).

---

## Updating the plugin

```bash
/plugin update jintech-omg-dev
```

---

## Contributing

Changes to skills, hooks, or the CRG server go through the standard OMG development pipeline. Raise a PR against `github.com/jintech/jintech-omg-dev`.

For questions: #dev-tooling on Slack or raise a Jira ticket in the TOOLS project.
