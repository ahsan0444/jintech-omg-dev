#!/usr/bin/env bash
# overnight.sh - bounded unattended "Ralph"-style loop for LOW-RISK OMG backlog
# work: locale backfill and perlcritic severity-5 fixes.
#
# Each iteration runs a FRESH `claude -p` session in a dedicated git worktree.
# The filesystem (the checklist file) is the only memory carried between
# iterations. Never commits from THIS script's own working tree, never pushes,
# never touches master.
#
# Owned by: jintech-omg-dev plugin (skills/overnight, tools/overnight.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OMG_REPO="${OMG_REPO:-/Users/Shared/Code/omg}"
HARD_MAX_ITER=25
DEFAULT_MAX_ITER=10

usage() {
  cat <<'EOF'
Usage: overnight.sh --task <locale|perlcritic> [options]

Bounded unattended loop (Ralph-style): a fresh `claude -p` session, in a
dedicated git worktree, fixes ONE checklist item per iteration, verifies it,
commits, and ticks it off. Stops on an empty checklist, --max-iter, or two
consecutive failed iterations.

Never touches master, never runs `git push`, never edits outside the worktree
it creates.

Options:
  --task <locale|perlcritic>   Required. Which backlog category to work.
  --max-iter N                 Max loop iterations. Default 10, hard cap 25.
  --worktree NAME              Worktree name. Default overnight-<task>-<date>.
  --dry-run                    Print the seeded checklist and the exact
                                `claude` command(s) that WOULD run, for both
                                the seed step and one loop iteration. Does not
                                create a worktree, does not invoke `claude`,
                                does not write anything outside /tmp.
  -h, --help                   Show this help and exit.

Examples:
  overnight.sh --task locale --dry-run
  overnight.sh --task perlcritic --max-iter 5
EOF
}

log() { printf '[overnight] %s\n' "$*" >&2; }
die() { printf '[overnight] ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------
TASK=""
MAX_ITER="$DEFAULT_MAX_ITER"
WORKTREE_NAME=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK="${2:-}"; shift 2 ;;
    --max-iter)
      MAX_ITER="${2:-}"; shift 2 ;;
    --worktree)
      WORKTREE_NAME="${2:-}"; shift 2 ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      die "unknown argument: $1 (see --help)" ;;
  esac
done

[[ "$TASK" == "locale" || "$TASK" == "perlcritic" ]] \
  || die "--task must be 'locale' or 'perlcritic' (got: '${TASK}')"

[[ "$MAX_ITER" =~ ^[0-9]+$ ]] || die "--max-iter must be a positive integer"
(( MAX_ITER >= 1 )) || die "--max-iter must be >= 1"
if (( MAX_ITER > HARD_MAX_ITER )); then
  log "WARN: --max-iter=${MAX_ITER} exceeds hard cap ${HARD_MAX_ITER}; capping"
  MAX_ITER=$HARD_MAX_ITER
fi

DATE_TAG="$(date +%Y%m%d)"
WORKTREE_NAME="${WORKTREE_NAME:-overnight-${TASK}-${DATE_TAG}}"
BRANCH_NAME="overnight/${TASK}-${DATE_TAG}"
WORKTREE_PATH="${OMG_REPO}/.claude/worktrees/${WORKTREE_NAME}"
CHECKLIST_REL=".planning/overnight-${TASK}.md"
SUMMARY_REL=".planning/overnight-${TASK}-summary.md"

[[ -d "$OMG_REPO/.git" ]] || die "$OMG_REPO is not a git repository (set OMG_REPO to override)"

# ---------------------------------------------------------------------------
# Deterministic checklist seeding (grep/perlcritic-based, no `claude -p` call
# needed — preferred per spec). Reads from $1 (a repo working tree, either the
# live OMG_REPO for --dry-run preview, or the freshly created worktree for a
# real run) and prints a checklist body to stdout.
# ---------------------------------------------------------------------------

seed_checklist_locale() {
  local repo="$1"
  local en_json="${repo}/locale/default/en.json"
  local views_dir="${repo}/views"
  local js_dir="${repo}/public/javascripts"

  echo "# Overnight checklist — locale backfill"
  echo
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Source: deterministic grep over views/**/*.tt and public/javascripts/**/*.js"
  echo

  if [[ ! -f "$en_json" ]]; then
    echo "- [ ] FAILED-SEED: ${en_json} not found — cannot compute locale gaps"
    return
  fi

  # en.json (and siblings) carry a leading `# <file>.json` comment line that
  # is not valid JSON — strip it before handing to jq.
  local strip_comment='/^#/d'

  # Extract keys passed to l('key') / loc('key') style calls. Confirmed
  # against this repo: both `l(...)` and `loc(...)` are used in views/.
  local keys_file
  keys_file="$(mktemp)"
  grep -rhoE "\b(l|loc)\(\s*['\"][A-Za-z0-9_.-]+['\"]" \
    "$views_dir" "$js_dir" 2>/dev/null \
    | sed -E "s/^(l|loc)\([[:space:]]*['\"]//; s/['\"]\$//" \
    | sort -u > "$keys_file" || true

  local total=0 missing=0 key present
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    total=$((total + 1))
    present="$(sed "$strip_comment" "$en_json" | jq -e --arg k "$key" 'has($k)' 2>/dev/null || echo false)"
    if [[ "$present" != "true" ]]; then
      missing=$((missing + 1))
      echo "- [ ] locale key \`${key}\` missing from locale/default/en.json (add to en.json placeholder + all sibling language files)"
    fi
  done < "$keys_file"
  rm -f "$keys_file"

  echo
  echo "<!-- scanned ${total} unique keys, ${missing} missing from en.json -->"
  if (( missing == 0 )); then
    echo "- [ ] NO-OP: no missing locale keys found by the deterministic scan"
  fi
}

seed_checklist_perlcritic() {
  local repo="$1"
  local rel_lib="lib"

  echo "# Overnight checklist — perlcritic severity-5 fixes"
  echo
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Source: perlcritic --severity 5 via podman exec omg, profile tools/perl_critic/.perlcriticrc"
  echo

  if ! command -v podman >/dev/null 2>&1; then
    echo "- [ ] FAILED-SEED: podman not found on PATH — cannot run perlcritic"
    return
  fi
  if ! podman exec omg true >/dev/null 2>&1; then
    echo "- [ ] FAILED-SEED: podman container 'omg' is not running — start it and re-seed"
    return
  fi

  # Custom pipe-delimited --verbose format so output is trivially parseable
  # and always carries the filename (the profile's default `verbose = 8`
  # format omits the filename on repeated violations within one file).
  local raw
  raw="$(podman exec omg bash -c \
    "/opt/local/bin/perlcritic --severity 5 --verbose '%f|%l|%s|%p|%m\n' --profile=/var/www/OMG/tools/perl_critic/.perlcriticrc /var/www/OMG/${rel_lib} 2>/dev/null" \
    || true)"

  local count=0
  local file ln sev policy msg
  while IFS='|' read -r file ln sev policy msg; do
    [[ -z "$file" || -z "$ln" ]] && continue
    file="${file#/var/www/OMG/}"
    count=$((count + 1))
    echo "- [ ] perlcritic (severity ${sev}): ${policy} — ${msg} at ${file}:${ln}"
  done <<< "$raw"

  echo
  echo "<!-- ${count} severity-5 violations found -->"
  if (( count == 0 )); then
    echo "- [ ] NO-OP: no severity-5 perlcritic violations found"
  fi
}

seed_checklist() {
  local repo="$1"
  case "$TASK" in
    locale) seed_checklist_locale "$repo" ;;
    perlcritic) seed_checklist_perlcritic "$repo" ;;
  esac
}

# ---------------------------------------------------------------------------
# Per-iteration prompt (fresh `claude -p` session; filesystem = memory)
# ---------------------------------------------------------------------------

build_iteration_prompt() {
  local checklist_path="$1"
  cat <<EOF
You are one bounded, unattended iteration of an overnight backlog loop.
Read the checklist at ${checklist_path}.
Pick the FIRST unchecked ("- [ ]") item, ignoring any line starting with
"FAILED-SEED" or "NO-OP" (those mean nothing to do — leave them and stop).

Fix ONLY that one item. Do not touch any other item, any other file, or any
out-of-scope code, even if you notice something else that looks wrong.

Task-specific rules:
- locale: add the missing key to locale/default/en.json using the source
  string as the English value, then add the same key to every sibling file
  under locale/default/ (es.json, fr.json, ja.json, pt.json, pt-br.json,
  zh-cn.json) using the English value as a translator placeholder. Preserve
  the existing leading comment line and formatting; make the smallest
  possible diff (no re-sorting, no re-indenting the whole file).
- perlcritic: fix ONLY the exact policy violation at the exact file:line
  listed. Make the minimal change that satisfies the policy. Do not
  refactor surrounding code.

Verify before committing:
- locale: for EVERY locale/default/*.json file you touched, run
  \`sed '/^#/d' <file> | python3 -m json.tool > /dev/null\` (the first line is
  a non-JSON comment header — strip it first) and confirm it succeeds.
- perlcritic: run
  \`podman exec omg bash -c "perl -c /var/www/OMG/<path-to-file>"\`
  and confirm it reports "syntax OK".

If verification fails, revert your change for this item, mark the checklist
line as "- [x] FAILED: <one-line reason>" (not "- [X]"), and stop — do not
retry within this iteration.

If verification succeeds:
1. Tick the item: change its "- [ ]" to "- [x]" in ${checklist_path}.
2. Commit with a plain, short message (no ticket IDs) describing only what
   changed, e.g. "Add missing locale key <key>" or "Fix <Policy> in <file>".
3. Stop. Do not pick up a second item.

You have no network access and cannot push, run DB writes, or edit files
outside this worktree — those tools are disabled for this session.
EOF
}

# ---------------------------------------------------------------------------
# --dry-run: print seeded checklist + exact claude command(s), do nothing else
# ---------------------------------------------------------------------------
if (( DRY_RUN )); then
  log "DRY RUN for task='${TASK}' (no worktree created, no claude invocation)"
  echo "=================================================================="
  echo "Would create worktree at: ${WORKTREE_PATH}"
  echo "Would create branch:      ${BRANCH_NAME}"
  echo "Checklist would be at:    ${WORKTREE_PATH}/${CHECKLIST_REL}"
  echo "Summary would be at:      ${WORKTREE_PATH}/${SUMMARY_REL}"
  echo "=================================================================="
  echo
  echo "----- SEEDED CHECKLIST (preview, computed against ${OMG_REPO}) -----"
  seed_checklist "$OMG_REPO"
  echo "----------------------------------------------------------------"
  echo
  TMP_PROMPT="$(mktemp)"
  build_iteration_prompt "${WORKTREE_PATH}/${CHECKLIST_REL}" > "$TMP_PROMPT"
  echo "----- EXACT claude COMMAND FOR ONE ITERATION -----"
  cat <<EOF
cd "${WORKTREE_PATH}" && claude -p "\$(cat ${TMP_PROMPT})" \\
  --permission-mode acceptEdits \\
  --output-format json \\
  --max-budget-usd 2 \\
  --disallowedTools "Bash(git push:*)" "Bash(curl:*)" "Bash(wget:*)" "Bash(psql:*)" "WebFetch" "WebSearch" "mcp__postgres__query"
EOF
  echo "---------------------------------------------------"
  echo
  echo "(prompt body written to: ${TMP_PROMPT} — inspect and rm when done)"
  echo
  echo "NOTE: this claude CLI build has no --max-turns flag (verified via"
  echo "'claude --help'); --max-budget-usd is used instead as the per-iteration"
  echo "runaway cap."
  exit 0
fi

# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------
command -v claude >/dev/null 2>&1 || die "claude CLI not found on PATH"

CURRENT_BRANCH="$(git -C "$OMG_REPO" rev-parse --abbrev-ref HEAD)"
log "base branch for worktree: ${CURRENT_BRANCH}"

if [[ -e "$WORKTREE_PATH" ]]; then
  die "worktree path already exists: ${WORKTREE_PATH} (pick a different --worktree name)"
fi

mkdir -p "${OMG_REPO}/.claude/worktrees"
log "creating worktree ${WORKTREE_PATH} on new branch ${BRANCH_NAME} (from ${CURRENT_BRANCH})"
git -C "$OMG_REPO" worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" "$CURRENT_BRANCH"

mkdir -p "${WORKTREE_PATH}/.planning"
CHECKLIST_PATH="${WORKTREE_PATH}/${CHECKLIST_REL}"
SUMMARY_PATH="${WORKTREE_PATH}/${SUMMARY_REL}"

log "seeding checklist -> ${CHECKLIST_PATH}"
seed_checklist "$WORKTREE_PATH" > "$CHECKLIST_PATH"

DISALLOWED=(
  "Bash(git push:*)"
  "Bash(curl:*)"
  "Bash(wget:*)"
  "Bash(psql:*)"
  "WebFetch"
  "WebSearch"
  "mcp__postgres__query"
)

ITER=0
CONSEC_FAIL=0
DONE_ITEMS=()
FAILED_ITEMS=()

remaining_unchecked() {
  grep -c '^- \[ \]' "$CHECKLIST_PATH" 2>/dev/null || echo 0
}

while (( ITER < MAX_ITER )); do
  REMAINING="$(remaining_unchecked)"
  if (( REMAINING == 0 )); then
    log "checklist has no unchecked items — stopping"
    break
  fi

  ITER=$((ITER + 1))
  log "iteration ${ITER}/${MAX_ITER} — ${REMAINING} unchecked item(s) remain"

  PROMPT_FILE="$(mktemp)"
  build_iteration_prompt "$CHECKLIST_PATH" > "$PROMPT_FILE"

  set +e
  ITER_OUTPUT="$(cd "$WORKTREE_PATH" && claude -p "$(cat "$PROMPT_FILE")" \
    --permission-mode acceptEdits \
    --output-format json \
    --max-budget-usd 2 \
    --disallowedTools "${DISALLOWED[@]}" 2>&1)"
  ITER_RC=$?
  set -e
  rm -f "$PROMPT_FILE"

  echo "$ITER_OUTPUT" >> "${WORKTREE_PATH}/.planning/overnight-${TASK}-iterations.log"

  if (( ITER_RC != 0 )); then
    log "iteration ${ITER} exited non-zero (rc=${ITER_RC})"
    CONSEC_FAIL=$((CONSEC_FAIL + 1))
    FAILED_ITEMS+=("iteration ${ITER}: claude exited rc=${ITER_RC}")
  elif grep -q '^- \[x\] FAILED:' "$CHECKLIST_PATH" 2>/dev/null; then
    log "iteration ${ITER} recorded a FAILED item in the checklist"
    CONSEC_FAIL=$((CONSEC_FAIL + 1))
    FAILED_ITEMS+=("iteration ${ITER}: see checklist FAILED entries")
  else
    CONSEC_FAIL=0
    DONE_ITEMS+=("iteration ${ITER}: completed (see git log in worktree)")
  fi

  if (( CONSEC_FAIL >= 2 )); then
    log "two consecutive failed iterations — stopping"
    break
  fi
done

# ---------------------------------------------------------------------------
# Morning summary
# ---------------------------------------------------------------------------
{
  echo "# Overnight summary — ${TASK} (${DATE_TAG})"
  echo
  echo "Worktree: ${WORKTREE_PATH}"
  echo "Branch:   ${BRANCH_NAME}"
  echo "Iterations run: ${ITER} (max ${MAX_ITER})"
  echo
  echo "## Items completed"
  if (( ${#DONE_ITEMS[@]} == 0 )); then
    echo "- none"
  else
    for i in "${DONE_ITEMS[@]}"; do echo "- $i"; done
  fi
  echo
  echo "## Items failed"
  if (( ${#FAILED_ITEMS[@]} == 0 )); then
    echo "- none"
  else
    for i in "${FAILED_ITEMS[@]}"; do echo "- $i"; done
  fi
  echo
  echo "## Commits"
  git -C "$WORKTREE_PATH" log --oneline "${CURRENT_BRANCH}..HEAD" 2>/dev/null || echo "- none"
  echo
  echo "## Diffstat"
  git -C "$WORKTREE_PATH" diff --stat "${CURRENT_BRANCH}..HEAD" 2>/dev/null || echo "- none"
} > "$SUMMARY_PATH"

log "done. worktree: ${WORKTREE_PATH}"
log "summary: ${SUMMARY_PATH}"
echo "$WORKTREE_PATH"
