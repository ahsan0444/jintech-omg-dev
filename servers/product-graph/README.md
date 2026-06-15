# product-graph

A generic, repo-agnostic engine that builds a queryable **product-knowledge graph**
for any product repo registered in an Agent OS data home. It lives in the plugin
(`servers/product-graph/`) and reads two things:

1. **Repo source** (`repo_root` from `config.yml`) — Perl routes, TT templates, SCSS tokens.
2. **Private data home** (`$AGENT_OS_HOME/<data>/registry/`) — the trusted feature registry.

The output is a deterministic SQLite graph (`nodes` + `edges`) at:

    $AGENT_OS_HOME/<data>/.product-graph/product.db

## What it extracts

| Extractor | Source | Node type | Notes |
|---|---|---|---|
| `extract/routes.py` | `lib/OMG*.pm` | `route` | Dancer2 `get/post/put/patch/del`, `any [...]`, `ajax [...]` with `\&controller::sub` handlers. Inline `sub {}` and `qr{}` regex routes are skipped. |
| `extract/tt.py` | `views/**/*.tt` | `template` | + `includes` edges for `INCLUDE`/`PROCESS`/`WRAPPER`. |
| `extract/scss.py` | `public/css/**/*.scss`, `public/custom/**/*.scss` | `design_token` | SCSS `$vars` and CSS `--custom-props`. **Source only.** |
| `extract/registry.py` | `$AGENT_OS_HOME/<data>/registry/` | `feature` | One node per `features/*.yml`; + `tests_route` edges to matching route nodes. |

## Never reads minified / compiled / bundled files

The SCSS extractor scans **source `.scss` only** and explicitly skips any `*.min.*`
file and anything under `node_modules/`, `dist/`, or `vendor/`. No compiled `.css`,
no bundles, ever.

## Build

PyYAML is required (config + registry parsing). Everything else is stdlib.

    pip install pyyaml         # or: pip install -r requirements.txt
    python build.py --repo omg

Rebuild is idempotent — the schema is dropped and recreated every run, so output
is deterministic.

## Query (CLI)

    python build.py --repo omg query feature   <name>          # feature node attrs as JSON
    python build.py --repo omg query selectors <feature>       # feature selectors dict
    python build.py --repo omg query route     <path-substr>   # matching route nodes
    python build.py --repo omg query token     <substr>        # matching design tokens

## Serve (MCP, stdio)

Requires the `mcp` package. The DB must already be built by `build.py`.

    pip install -r requirements.txt
    python serve.py

Tools (each takes `repo: str = "omg"`):

- `pg_feature(name, repo)`
- `pg_selectors(feature, repo)`
- `pg_route(path, repo)`
- `pg_design_tokens(query, repo)`
- `pg_query(node_type, name_substring, repo)`

Responses are compact JSON.

## Resolution

`AGENT_OS_HOME` (default `~/.agent-os`) → `config.yml` maps each repo `name` to its
`repo_root` (source) and `data` dir. Cross-platform paths via `os.path` / `expanduser`.

## Embeddings — DEFERRED

Semantic / vector search over the graph is intentionally **not** implemented yet.
It will be added later by reusing CRG's (code-review-graph) embedding library so the
two engines share one embedding path rather than duplicating it.
