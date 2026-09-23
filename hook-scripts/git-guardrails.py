#!/usr/bin/env python3
"""
PreToolUse hook (matcher: Bash): deny destructive/protected-branch git commands
before they run.

Denies:
  - `git push` with any force flag (-f, --force, --force-with-lease[=...])
  - `git push` whose target is a protected branch — an explicit refspec
    (`git push origin master`, `git push origin HEAD:main`) or a bare
    `git push` while the current branch (via `git -C <cwd> branch --show-current`)
    is protected
  - `git commit` while the current branch is protected
  - `git reset --hard`, `git clean -f` (any -f/-fd/... combo), `git checkout -- .`
    / `git checkout .`, `git restore .`, `git branch -D`
  - gitleaks secret scan on `git commit` (see check_gitleaks)

Protected branches: env GIT_GUARDRAIL_PROTECTED, comma-separated glob-ish list
(fnmatch), default "master,main,omg-s*". Per-repo opt-out (solo repos pushed
straight to main): env GIT_GUARDRAIL_ALLOW_REPOS, comma-separated repo
basenames, default "jintech-omg-dev,claude-marketplace" — commands run inside
one of these repos are never denied by the protected-branch checks (force-push
and destructive-command checks still apply).

Commands are split on &&, ;, and | so every segment in a chain is checked.

Output contract (PreToolUse): deny = JSON on stdout
  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                           "permissionDecision": "deny",
                           "permissionDecisionReason": "..."}}
  + exit 0. Allow = silent exit 0. Fail-open on any internal error.
"""
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

DEFAULT_PROTECTED = "master,main,omg-s*"
DEFAULT_ALLOW_REPOS = "jintech-omg-dev,claude-marketplace"

GITLEAKS_TIMEOUT = 15
BRANCH_LOOKUP_TIMEOUT = 5

FORCE_FLAG_RE = re.compile(r'(^|\s)(-f|--force|--force-with-lease(=\S+)?)(\s|$)')


# ---------------------------------------------------------------- config
def protected_branches():
    raw = os.environ.get("GIT_GUARDRAIL_PROTECTED", DEFAULT_PROTECTED)
    return [p.strip() for p in raw.split(",") if p.strip()]


def allow_repos():
    raw = os.environ.get("GIT_GUARDRAIL_ALLOW_REPOS", DEFAULT_ALLOW_REPOS)
    return [r.strip() for r in raw.split(",") if r.strip()]


def is_protected_branch(branch, patterns=None):
    if not branch:
        return False
    patterns = patterns if patterns is not None else protected_branches()
    return any(fnmatch.fnmatch(branch, p) for p in patterns)


def repo_opts_out(repo_root, repos=None):
    if not repo_root:
        return False
    repos = repos if repos is not None else allow_repos()
    return os.path.basename(os.path.normpath(repo_root)) in repos


# ---------------------------------------------------------------- command splitting
def split_segments(command):
    """Split a shell command chain on &&, ;, | into individual segments.

    Pure string split — not a real shell parser, but good enough to catch
    each git invocation in a chain like `git add . && git commit -m x`.
    """
    if not command:
        return []
    parts = re.split(r'&&|\|\||;|\||\n', command)
    return [p.strip() for p in parts if p.strip()]


def tokenize(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def is_git_command(tokens):
    return bool(tokens) and os.path.basename(tokens[0]) == "git"


def git_subcommand(tokens):
    """First non-flag token after `git` (skips global flags like -C <dir>)."""
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t == "-C":
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, i
    return "", i


# ---------------------------------------------------------------- current branch
def current_branch(cwd):
    try:
        r = subprocess.run(
            ["git", "-C", cwd or ".", "branch", "--show-current"],
            capture_output=True, text=True, timeout=BRANCH_LOOKUP_TIMEOUT,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def get_repo_root(cwd):
    try:
        r = subprocess.run(
            ["git", "-C", cwd or ".", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=BRANCH_LOOKUP_TIMEOUT,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


# ---------------------------------------------------------------- push target parsing
def push_refspec_branch(tokens, sub_idx):
    """Best-effort extraction of the destination branch from `git push` args.

    Looks at the first non-flag arg after `push` as the remote, and the arg
    after that as the refspec (`<src>:<dst>` or a bare branch name pushed to
    the same-named remote branch). Returns '' if no explicit branch is given
    (bare `git push`).
    """
    args = tokens[sub_idx + 1:]
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        return ""
    # positional[0] is the remote (e.g. "origin"); positional[1] if present
    # is the refspec.
    if len(positional) < 2:
        return ""
    refspec = positional[1]
    if ":" in refspec:
        dst = refspec.split(":", 1)[1]
    else:
        dst = refspec
    dst = dst.lstrip("+")  # leading + also means force
    return dst


def push_has_force(segment, tokens):
    if FORCE_FLAG_RE.search(" " + segment + " "):
        return True
    return any(t.startswith("+") and len(t) > 1 for t in tokens)


# ---------------------------------------------------------------- destructive commands
DESTRUCTIVE_RESET_HARD = re.compile(r'\bgit\s+reset\b.*--hard\b')
DESTRUCTIVE_CLEAN_F = re.compile(r'\bgit\s+clean\b\s+(-[a-zA-Z]*f[a-zA-Z]*\b|.*--force\b)')
DESTRUCTIVE_CHECKOUT_DOT = re.compile(r'\bgit\s+checkout\b\s+(--\s+)?\.\s*$')
DESTRUCTIVE_RESTORE_DOT = re.compile(r'\bgit\s+restore\b\s+\.\s*$')
DESTRUCTIVE_BRANCH_D = re.compile(r'\bgit\s+branch\b.*(-D\b|--delete\s+--force\b)')


def destructive_reason(segment):
    seg = segment.strip()
    if DESTRUCTIVE_RESET_HARD.search(seg):
        return "git reset --hard discards uncommitted work — deny."
    if DESTRUCTIVE_CLEAN_F.search(seg):
        return "git clean -f permanently deletes untracked files — deny."
    if DESTRUCTIVE_CHECKOUT_DOT.search(seg) or DESTRUCTIVE_RESTORE_DOT.search(seg):
        return "git checkout/restore over the whole working tree discards local changes — deny."
    if DESTRUCTIVE_BRANCH_D.search(seg):
        return "git branch -D force-deletes a branch — deny."
    return ""


# ---------------------------------------------------------------- gitleaks
def gitleaks_available():
    try:
        r = subprocess.run(["gitleaks", "--help"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0 or bool(r.stdout or r.stderr)
    except Exception:
        return False


def run_gitleaks(cwd):
    """Run gitleaks against staged changes. Returns '' if clean/missing, else
    a trimmed findings summary (max 20 lines)."""
    if not gitleaks_available():
        return ""
    for args in (["gitleaks", "git", "--staged", "--redact", "--no-banner"],
                 ["gitleaks", "protect", "--staged", "--redact"]):
        try:
            r = subprocess.run(
                args, capture_output=True, text=True, timeout=GITLEAKS_TIMEOUT,
                cwd=cwd or ".",
            )
        except Exception:
            continue
        if r.returncode == 0:
            return ""
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if "unknown command" in out.lower() or "unknown flag" in out.lower():
            continue  # try the older syntax
        lines = out.splitlines()[:20]
        return "\n".join(lines)
    return ""


# ---------------------------------------------------------------- decision
def evaluate_segment(segment, cwd):
    """Returns a deny reason string, or '' to allow this segment."""
    tokens = tokenize(segment)
    if not is_git_command(tokens):
        return ""

    sub, sub_idx = git_subcommand(tokens)

    reason = destructive_reason(segment)
    if reason:
        return reason

    repo_root = get_repo_root(cwd)
    opted_out = repo_opts_out(repo_root)

    if sub == "push":
        if push_has_force(segment, tokens):
            return ("Force push blocked. Ask the user to run this push "
                    "themselves if a force push is really needed.")
        if not opted_out:
            dst = push_refspec_branch(tokens, sub_idx)
            if dst:
                if is_protected_branch(dst):
                    return f"git push targets protected branch '{dst}' — ask the user to push this themselves."
            else:
                branch = current_branch(cwd)
                if is_protected_branch(branch):
                    return f"Bare git push on protected branch '{branch}' — ask the user to push this themselves."
        return ""

    if sub == "commit":
        if not opted_out:
            branch = current_branch(cwd)
            if is_protected_branch(branch):
                return f"git commit on protected branch '{branch}' — ask the user to commit this themselves."
        findings = run_gitleaks(cwd)
        if findings:
            return f"gitleaks found potential secrets in staged changes:\n{findings}"
        return ""

    if sub == "branch":
        # handled by destructive_reason above (covers -D); nothing else here
        return ""

    return ""


def effective_cwd(tokens, cwd):
    """Directory a segment acts on: `cd <dir>` changes it, `git -C <dir>` overrides it."""
    if tokens and tokens[0] == "cd" and len(tokens) > 1:
        return os.path.normpath(os.path.join(cwd or ".", os.path.expanduser(tokens[1])))
    if is_git_command(tokens) and "-C" in tokens:
        i = tokens.index("-C")
        if i + 1 < len(tokens):
            return os.path.normpath(os.path.join(cwd or ".", os.path.expanduser(tokens[i + 1])))
    return cwd


def evaluate_command(command, cwd):
    for segment in split_segments(command):
        tokens = tokenize(segment)
        if tokens and tokens[0] == "cd":
            cwd = effective_cwd(tokens, cwd)
            continue
        reason = evaluate_segment(segment, effective_cwd(tokens, cwd))
        if reason:
            return reason
    return ""


def deny_json(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


# ---------------------------------------------------------------- main
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    tool_input = data.get("tool_input", {}) or {}
    command = tool_input.get("command") or ""
    if not command:
        sys.exit(0)

    cwd = data.get("cwd") or os.getcwd()

    try:
        reason = evaluate_command(command, cwd)
    except Exception:
        sys.exit(0)

    if reason:
        print(json.dumps(deny_json(reason)))

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
