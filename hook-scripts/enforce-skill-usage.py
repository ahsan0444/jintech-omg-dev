#!/usr/bin/env python3
"""
PreToolUse hook: block gh pr create (wrong platform — OMG uses Bitbucket).
v1 scope: GitHub CLI only. v2 will expand based on audit log data.
Exit 2 = hard block. Exit 0 = allow.
"""
import sys
import json

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = data.get("tool_name", "")
tool_input = data.get("tool_input", {})

if tool == "Bash":
    cmd = tool_input.get("command", "")
    if "gh pr create" in cmd:
        print(
            "BLOCKED: OMG uses Bitbucket, not GitHub CLI.\n"
            "Use the /pr skill instead:\n"
            "  Skill tool: skill=\"jintech-omg-dev:pr\""
        )
        sys.exit(2)

sys.exit(0)
