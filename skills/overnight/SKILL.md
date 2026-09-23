---
name: overnight
description: Launch a bounded, unattended "Ralph"-style loop that works through a low-risk OMG backlog checklist overnight — one fresh `claude -p` session per item, in an isolated git worktree, never on master, never pushed. Currently supports locale key backfill and perlcritic severity-5 fixes.
disable-model-invocation: true
argument-hint: "<locale|perlcritic> [max-iter]"
---

# /overnight

EMERGING — new, not yet battle-tested. Review every commit before merging
anything it produces.

Runs `${CLAUDE_PLUGIN_ROOT}/tools/overnight.sh`, which drives a fresh,
disposable `claude -p` session per loop iteration inside a dedicated git
worktree. The checklist file on disk is the only memory carried between
iterations ("Ralph"-style: filesystem as memory, no long-lived context).

## When to use this

**Only** for mechanical, low-risk, easily-verified backlog work where a wrong
fix is cheap to spot and cheap to discard:

- **locale** — add locale JSON keys that are referenced in templates/JS but
  missing from `locale/default/en.json` (and its sibling language files).
- **perlcritic** — fix individual perlcritic severity-5 violations, one file:line
  at a time.

**Never** use this for:

- DB migrations or anything touching `omg_db` / `dbscripts/`
- Business logic changes of any kind
- Anything that needs judgment about UX, naming, or architecture
- Anything you would not be comfortable an unattended agent doing 25 times in
  a row with nobody watching

If in doubt, it does not belong in `/overnight` — use `/ticket` + `/implement`
instead.

## How to launch

Run it in a separate terminal, or in the background — never block the current
session on it:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/tools/overnight.sh --task locale --max-iter 10
# or
bash ${CLAUDE_PLUGIN_ROOT}/tools/overnight.sh --task perlcritic --max-iter 10 &
```

Always try `--dry-run` first when unsure what it will do — it prints the
seeded checklist and the exact `claude` command it would run, without
touching the filesystem or creating a worktree:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/tools/overnight.sh --task locale --dry-run
```

Flags: `--task <locale|perlcritic>` (required), `--max-iter N` (default 10,
hard cap 25), `--worktree NAME` (default `overnight-<task>-<date>`),
`--dry-run`.

## What it does

1. Creates a git worktree at `/Users/Shared/Code/omg/.claude/worktrees/<name>`
   on a brand-new branch `overnight/<task>-<date>`, based off whatever branch
   is currently checked out in the main repo. Never creates or checks out
   `master`, never pushes anything anywhere.
2. Seeds `.planning/overnight-<task>.md` in the worktree with a checklist,
   computed deterministically (grep + jq for locale gaps; `perlcritic
   --severity 5` for perlcritic) rather than by asking a model to find items —
   more reliable and free.
3. Loops: each iteration launches a **fresh** `claude -p` session
   (`--permission-mode acceptEdits`, `--output-format json`,
   `--max-budget-usd 2` as the per-iteration runaway cap — this CLI build has
   no `--max-turns` flag, verified via `claude --help`) with
   `--disallowedTools` blocking `git push`, `curl`, `wget`, `psql`, WebFetch,
   WebSearch, and DB-write MCP tools. The prompt tells it to read the
   checklist, fix ONLY the first unchecked item, run the matching check
   (`perl -c` via `podman exec omg` for `.pm` files; strip the JSON files'
   leading `#` comment line and run `python3 -m json.tool` for locale JSON),
   tick the item, and commit with a short plain message.
4. Stops when the checklist is empty, `--max-iter` is reached, or two
   iterations in a row fail.
5. Writes `.planning/overnight-<task>-summary.md` (items done/failed, commits,
   diffstat) and prints the worktree path.

## Morning review

1. Read the summary: `cat <worktree>/.planning/overnight-<task>-summary.md`
2. Read every commit, not just the diffstat:
   `git -C <worktree> log -p`
3. Decide per commit — cherry-pick the good ones onto a real branch, or
   discard the whole run:
   `git worktree remove <worktree>` (add `--force` if it has uncommitted
   changes you've already reviewed and don't want).
4. Never merge the `overnight/*` branch directly — treat every commit as an
   unreviewed PR from a very literal-minded junior contributor.
