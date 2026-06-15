# Agent OS (jintech-omg-dev)

Two layers on top of the SDLC pipeline + code-review-graph (CRG):

1. **Product-knowledge graph** — what the product *does* and *looks like*, complementing CRG (code structure).
   - **Registry** (trusted, hand-editable) — `~/.agent-os/<repo>/registry/`: `env`, `auth.yml`, `features/<f>.yml`.
   - **product-graph MCP** (queryable) — `servers/product-graph/` builds `product.db` from routes (`OMG*.pm`), TT inventory/includes, SCSS tokens, and the registry. Tools: `pg_feature`, `pg_selectors`, `pg_route`, `pg_design_tokens`, `pg_query`.
2. **Autonomous verify trust core** — `/verify` skill + `omg-verifier` agent. Tiered, assertion-based, never false-done.

Engine (generic) lives in the plugin. Per-product DATA lives in `~/.agent-os/` (private, gitignored secrets). The production app repo (e.g. `omg`) is never written to.

## Pipeline
`/grill-me → /ticket → /implement → /verify → /prepr → /pr` (+ `/debug`). `/verify` is the new gate.

## Verification tiers
- **Tier 1** (always, cheap): restart (Podman) + readiness probe + `curl` endpoint asserts. Backend-only changes stop here.
- **Tier 2** (when diff touches `.tt`/`.scss`/`.js` or a UI route): scripted Playwright spec (selectors/URL from the graph+registry). Result = exit code + tiny result file; the page never enters context. Specs persist as regression in `~/.agent-os/<repo>/specs/`.

## Definition of Done
Done requires a passing assertion that exercises THE CHANGE — not "app loaded". On failure: behavioral → leave server up + edits intact + alert; infrastructural → revert to last-known-good + alert. Self-fix is implementation-only (a spec-tamper guard rejects any run that modified the test). Alert before any revert.

## UI lanes
- In-app changes: edit real TT/SCSS components (informed by `pg_design_tokens`), confirm via Tier-2.
- **Claude Code Chrome extension**: interactive FE dev / visual debug / discovery feeder into `registry/.pending/` — a *separate session*, NOT the verifier.
- Greenfield: `frontend-design` + `ui-ux-pro-max`, then translate to real components before "done".

## Retrieval discipline (enforce-mcp-search)
CRG is the default for codebase search, but the block is steerable/self-releasing: grep is sanctioned for literal/multi-word patterns, when the graph is stale (build SHA != HEAD), and after a graph query for the same target returned empty (a one-shot, query-scoped breadcrumb). A single source's silence is a proposal, not proof.

## Deployment model (important)
Live hooks/MCP run from the plugin **cache** `~/.claude/plugins/cache/.../<version>/`, not the dev repo. Ship changes by version-bump + reinstall (or, for local iteration, sync files into the cache). `~/.agent-os/` is data only and never published.

## Setup on a new machine
Run `/agent-os-setup` (see `commands/agent-os-setup.md`). Prereqs: Node 18+, Python 3.12+, Podman, the running dev container, and access to the SSO host.
