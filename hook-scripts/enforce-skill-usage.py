#!/usr/bin/env python3
"""
PreToolUse hook: block `gh pr create` (wrong platform — OMG uses Bitbucket).
v1 scope: GitHub CLI only. v2 will expand based on audit log data.

Output contract: JSON permissionDecision on stdout + exit 0 (official PreToolUse
decision format). Allow = silent exit 0. Fail-open on bad input.
"""
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = data.get("tool_name", "")
tool_input = data.get("tool_input", {})

if tool == "Bash":
    cmd = tool_input.get("command", "")
    if "gh pr create" in cmd:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: OMG uses Bitbucket, not GitHub CLI.\n"
                    "Use the /pr skill instead:\n"
                    "  Skill tool: skill=\"jintech-omg-dev:pr\""
                ),
            }
        }))
        sys.exit(0)

sys.exit(0)
