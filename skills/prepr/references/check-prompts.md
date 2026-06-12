# /prepr — Per-Bucket Check Templates

Loaded on demand by SKILL.md Step 1. Each § is a complete Agent() template — use verbatim, filling `<placeholders>` from Step 0 (file lists, REPO_ROOT).

---

# § Check templates 1a–1e

### 1a — Perl Review (Haiku, Explore)

```
Agent(
  description="Perl review — perlcritic + OMG conventions",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed Perl files: <list from Step 0>
  Repo root: <REPO_ROOT>

  PHASE 0 — Graph-based structural review (MCP, 1-3 calls, run before linting):
    For each changed Perl file (use module basename as node name):
    mcp__code-review-graph__get_review_context_tool(node="<module_basename>", repo_root="<REPO_ROOT>")
    → surfaces the node's role, its callers, callees, and any known complexity flags.
    Flag nodes with >10 callers as WARNING (high-impact change).

    mcp__code-review-graph__find_large_functions_tool(repo_root="<REPO_ROOT>")
    → check if any changed files contain functions flagged as overly large/complex.
    Flag matches as WARNING with function name and line count.

    mcp__code-review-graph__get_knowledge_gaps_tool(repo_root="<REPO_ROOT>")
    → check if any changed nodes appear in the gaps list (no test coverage).
    Flag matches as WARNING: "No test coverage for <node> — add tests before PR."

    If graph absent or any tool errors: skip Phase 0 silently and continue.

  PHASE 1 — Perl::Critic (canonical command — single source of truth is the
  /perlcritic skill in the OMG repo; keep this block in sync with it):
    Map each local path to its container path:
      <REPO_ROOT>/lib/... → /var/www/OMG/lib/...
    Run once for all files (skip files that no longer exist on disk):
      Bash("podman exec omg bash -c \"perlcritic --profile=/var/www/OMG/tools/perl_critic/.perlcriticrc --severity 3 --verbose '%f|%l|%s|%p|%m\\n' <CONTAINER_PATHS>\"")
    Output is one violation per line: file|line|severity|Policy::Name|message.
    Non-zero exit with output = violations found, not an error.
    If `podman exec omg true` fails: report PERLCRITIC: unavailable (container down) and skip.
    Never fall back to a host perlcritic binary — it lacks the project profile and
    produces different results.

  PHASE 2 — OMG Layer Conventions (grep-based, run for each file):

  For files in lib/*/dao/ (*_db.pm):
    - CHECK: must NOT contain 'bless'
      Grep: grep -n 'bless' <file>
    - CHECK: must not return blessed objects
      Grep: grep -n 'return.*->new' <file>

  For files in lib/*/dom/ (*_dom.pm):
    - CHECK: must contain 'sub TO_JSON'
      Grep: grep -n 'sub TO_JSON' <file>
    - CHECK: TO_JSON must return '{ %{ shift() } }'
      Grep: grep -n 'TO_JSON' -A2 <file>

  For files in lib/*/*_helper.pm:
    - CHECK: must not call foreign _controller methods
      Grep: grep -n '_controller->' <file>
    - CHECK: must not directly call foreign _db methods
      Grep: grep -n '_db->' <file>

  For files in lib/*/*_controller.pm:
    - CHECK: must not call foreign _controller methods
      Grep: grep -n '_controller->' <file>
    - CHECK: should not import foreign DAOs directly
      Grep: grep -n 'use.*_db;' <file>

  For route files (OMG*.pm):
    - CHECK: OMG_ajax.pm should only have AJAX routes
      Grep: grep -n 'template\|redirect' lib/OMG_ajax.pm (if changed)

  PHASE 3 — General Perl hygiene (all files):
    - CHECK: no hardcoded environment values
      Grep: grep -n 'localhost\|127\.0\.0\.1\|password.*=.*["\x27][^"\x27]*["\x27]' <file>
    - CHECK: use strict and use warnings present
      Grep: grep -n 'use strict\|use warnings' <file>

  Return schema only, per file (no prose):

  FILE: <path>
  GRAPH_ROLE: <node role summary from get_review_context_tool, or "unknown">
  LARGE_FUNCTIONS: <function names flagged by find_large_functions_tool, or "none">
  COVERAGE_GAPS: <nodes with no test coverage from get_knowledge_gaps_tool, or "none">
  PERLCRITIC: <violations list, or "clean">
  BLOCKER: <description — line N, or "none">
  WARNING: <description — line N, or "none">
  """
)
```

---

### 1b — Template Review (Haiku, Explore)

```
Agent(
  description="TT template review — OMG conventions",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed .tt files: <list from Step 0>
  Note: this codebase uses <% %> Template Toolkit tags (not [% %]).

  For each file:

  1. HTML encoding — user content must use | html_entity or | html:
     Grep: grep -n '<% [a-zA-Z]' <file> | grep -v '| html_entity\|| html\|l(\|IF\|FOREACH\|INCLUDE\|PROCESS\|END\|USE\|SET\|BLOCK\|#\|SWITCH\|CASE\|WRAPPER'
     Flag unfiltered variable output as BLOCKER.

  2. Hardcoded English strings — must use l() for display text:
     Grep: grep -n '>[A-Z][a-z]' <file> | grep -v 'l(\|<%#\|class=\|id=\|href=\|src=\|type=\|name=\|value=\|placeholder.*l('
     Flag suspicious hardcoded strings as WARNING.

  3. Module JS/CSS loaded in template instead of layout:
     Grep: grep -n '<script\|<link' <file>
     Flag shared layout resources loaded here as WARNING.

  4. Hidden inputs missing meaningful id attributes:
     Grep: grep -n 'type="hidden"' <file>
     Flag missing id as WARNING.

  5. Inline JavaScript:
     Grep: grep -n 'onclick=\|onchange=\|onsubmit=' <file>
     Flag as WARNING — should use event listeners.

  Return schema only, per file (no prose):

  FILE: <path>
  BLOCKER: <issue — line N, or "none">
  WARNING: <issue — line N, or "none">
  """
)
```

---

### 1c — JavaScript Review (Haiku, Explore)

```
Agent(
  description="JS review — OMG namespace conventions",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed .js files (excluding *.min.js): <list from Step 0>

  IMPORTANT: Check only NEW code introduced in this diff — not pre-existing issues.
  For each file, run: git -C <REPO_ROOT> diff <file>
  Then apply checks only to lines starting with + (added lines), ignoring lines starting with -.

  For each file:

  1. No new raw $.ajax calls — must use omg.dataDelivery:
     From diff added lines: grep '\.ajax('
     Flag only NEW $.ajax additions as BLOCKER. Pre-existing $.ajax calls are not in scope.

  2. No new top-level globals — all code under omg namespace:
     From diff added lines: grep '^+var \|^+let \|^+const \|^+function '
     Flag new top-level declarations outside omg namespace as WARNING.

  3. No new hardcoded display strings in alerts:
     From diff added lines: grep 'showFlashAlert\|alert(' | grep -v 'localText\.'
     Flag new hardcoded strings as WARNING.

  4. New files should use const/let not var:
     Check if file is newly added (git status in <REPO_ROOT>).
     If new: grep -n '^var ' in full file and flag as WARNING.

  5. New class-based JS selectors (prefer data-ref):
     From diff added lines: grep "\$('\.[a-z]\|querySelector('\.[a-z]"
     Flag as WARNING (not blocker — legacy code uses them).

  Return schema only, per file (no prose):

  FILE: <path>
  BLOCKER: <issue — line N, or "none">
  WARNING: <issue — line N, or "none">
  """
)
```

---

### 1d — CSS/SCSS Review (Haiku, Explore)

```
Agent(
  description="CSS/SCSS review",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed CSS files: <css list from Step 0>
  Changed SCSS files: <scss list from Step 0>
  Repo root: <REPO_ROOT>

  CHECK 1 — Direct CSS edits:
    Only flag public/css/*.css files as BLOCKER if a corresponding SCSS source exists
    (i.e. the CSS is compiled output and should not be edited directly).
    To check: find <REPO_ROOT>/public -name "*.scss" | xargs grep -rl "<css_basename_without_ext>" 2>/dev/null
    If a matching SCSS source is found: flag the CSS file as BLOCKER.
    If no SCSS source found: the file is managed directly — skip, no violation.
    Exception: public/css/bryntum/*_omg.css overrides — flag as WARNING not blocker regardless.

  CHECK 2 — SCSS import order (for changed app.scss only):
    Grep: grep -n '@import' <file>
    Expected order: style → login → global → bootstrap
    Flag wrong order as WARNING.

  CHECK 3 — !important overuse:
    Grep: grep -c '!important' <file>
    If count > 5 in a single file: flag as WARNING with count.

  Return schema only (no prose):

  CSS_DIRECT_EDITS: <list of blocked files, or "none">
  SCSS_WARNINGS: <list with line numbers, or "none">
  """
)
```

---

### 1e — SQL / DB Script Review (Haiku, Explore)

```
Agent(
  description="SQL/DB script review — OMG naming conventions",
  subagent_type="omg-investigator",
  model="haiku",
  prompt="""
  Changed SQL files: <list from Step 0>
  Repo root: <REPO_ROOT>

  For each file:

  1. File naming convention: dbscripts/s<sprint>/<n>_<TICKET>_<description>.sql
     Flag non-conforming names as BLOCKER.

  2. Deploy/rollback pair:
     Check that for every deploy file a matching rollback exists.
     ls <parent_dir>/rollback/ for matching name.
     Missing rollback = BLOCKER.

  3. Function naming: <entity>_<scope>_<verb> pattern:
     Grep: grep -n 'CREATE.*FUNCTION\|REPLACE.*FUNCTION' <file>
     Flag functions not following pattern as WARNING.

  4. Table conventions (ALTER/CREATE TABLE):
     Grep: grep -n 'ALTER TABLE\|CREATE TABLE' <file>
     - FK columns must have fk_ prefix
     - New tables should have is_deleted column
     Flag violations as WARNING.

  5. Sensitive data encryption variants:
     Grep: grep -n 'email\|password\|phone\|bank\|card' <file>
     If sensitive fields found with no _enc function variant: flag as WARNING.

  6. Live DB validation (psql CLI only — if psql unavailable, skip and note in WARNING):
     a. For each CREATE OR REPLACE FUNCTION: check if function exists with DIFFERENT signature:
        Bash("psql -t -A -c \"SELECT proname, pg_get_function_arguments(oid) FROM pg_proc WHERE proname = '<name>'\" 2>/dev/null")
        Different signature = BLOCKER.
     b. For each table referenced: confirm it exists:
        Bash("psql -t -A -c \"SELECT tablename FROM pg_tables WHERE tablename = '<table>'\" 2>/dev/null")
        Missing = BLOCKER.
     c. For each ADD COLUMN: confirm it doesn't already exist:
        Bash("psql -t -A -c \"SELECT column_name FROM information_schema.columns WHERE table_name = '<table>' AND column_name = '<column>'\" 2>/dev/null")
        Already exists = BLOCKER.

  Return schema only, per file (no prose):

  FILE: <path>
  BLOCKER: <issue, or "none">
  WARNING: <issue, or "none">
  """
)
```

---
