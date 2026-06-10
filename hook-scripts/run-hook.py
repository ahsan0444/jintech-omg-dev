#!/usr/bin/env python3
"""Fail-open hook dispatcher — cross-platform replacement for `sh -c '[ -f ... ]'` wrappers.

Usage (from hooks/hooks.json):
    python3 "${CLAUDE_PLUGIN_ROOT}/hook-scripts/run-hook.py" <script-name>

Resolves <script-name>.py next to this file and executes it with the same
stdin/stdout/stderr, so the target script's exit code and output contracts
(e.g. PreToolUse exit 2 = block) pass through unchanged.

If the target script is missing or raises unexpectedly, exits 0 — a broken
plugin install must never block the user's tools. Works identically on
macOS, Linux, and Windows (no shell builtins required).
"""
import os
import runpy
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit(0)
    name = os.path.basename(sys.argv[1])
    if not name.endswith(".py"):
        name += ".py"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    if not os.path.isfile(path):
        sys.exit(0)
    # Shift argv so the target script sees its own name in argv[0]
    sys.argv = [path] + sys.argv[2:]
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit:
        raise
    except Exception:
        # Fail open: never let a dispatcher bug block a tool call
        sys.exit(0)


if __name__ == "__main__":
    main()
