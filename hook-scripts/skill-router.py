#!/usr/bin/env python3
"""UserPromptSubmit hook: route natural-language prompts to skills/procedures.

Pipeline:
  Stage 0: kill switch (CLAUDE_SKILL_ROUTER_DISABLED env) → silent exit
  Stage 1: prompt starts with / or \\ → silent exit (explicit command)
  Stage 2: high-confidence manifest scan; first match wins
  Stage 3: low-confidence scan (0 → silent, 1 → hedge, 2+ → menu)

Fail-open: any exception → sys.exit(0). Never block user input.
"""
import hashlib
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone

# Hard timeout — kill the process at 500ms regardless of state.
def _timeout():
    os._exit(0)

_timer = threading.Timer(0.5, _timeout)
_timer.daemon = True
_timer.start()


def _hook_script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def plugin_root():
    return os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(_hook_script_dir()))


def get_manifest_path():
    override = os.environ.get("SKILL_ROUTER_MANIFEST_OVERRIDE")
    if override and os.path.isfile(override):
        return override
    user_override = os.path.expanduser("~/.claude/skill-routing-manifest.json")
    if os.path.isfile(user_override):
        return user_override
    return os.path.join(plugin_root(), "skill-routing-manifest.json")


def load_manifest():
    path = get_manifest_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def match_intent(prompt, intent):
    for pat in intent.get("patterns", []):
        try:
            if re.search(pat, prompt, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def skill_base_name(skill_id):
    # "jintech-omg-dev:pr" → "pr"; "verify" → "verify"
    if ":" in skill_id:
        return skill_id.split(":", 1)[1]
    return skill_id


def render_skill_output(intent):
    action = intent["action"]
    skill_id = action["skill"]
    base = skill_base_name(skill_id)
    return (
        f"⚡ ROUTING ACTIVE: The user's request matches the `{base}` skill.\n"
        f"You MUST invoke the Skill tool with skill=\"{skill_id}\" before doing anything else.\n"
        f"Do not improvise the steps. The skill defines the exact procedure."
    )


def render_inline_output(intent):
    action = intent["action"]
    file_path = os.path.expanduser(action["file"])
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    return (
        f"⚡ PROCEDURE ACTIVE: {intent['id']}\n"
        f"{content}\n"
        f"Follow these steps exactly. Do not deviate."
    )


def render_output(intent):
    t = intent["action"]["type"]
    if t == "skill":
        return render_skill_output(intent)
    if t == "inline":
        return render_inline_output(intent)
    return None


def render_low_confidence_single(intent):
    base = render_output(intent)
    if base is None:
        return None
    return base + "\n(possible match — verify before proceeding)"


def render_clarification_menu(intents):
    lines = ["⚡ POSSIBLE MATCHES (possible match — verify): the prompt could match multiple intents:"]
    for it in intents:
        lines.append(f"  - {it['id']}")
    lines.append("Ask the user which one they intended before proceeding.")
    return "\n".join(lines)


def log_event(prompt, intent_id, action_type):
    try:
        log_dir = os.path.expanduser("~/.claude/logs")
        os.makedirs(log_dir, exist_ok=True)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(log_dir, f"intent-router-{date}.jsonl")
        if os.path.isfile(path) and os.path.getsize(path) > 10 * 1024 * 1024:
            return
        h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "prompt_hash": h,
            "matched_intent": intent_id,
            "action_type": action_type,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


SLASH_COMMAND_MAP = {
    "debug": "jintech-omg-dev:debug",
    "ticket": "jintech-omg-dev:ticket",
    "implement": "jintech-omg-dev:implement",
    "prepr": "jintech-omg-dev:prepr",
    "pr": "jintech-omg-dev:pr",
    "grill-me": "jintech-omg-dev:grill-me",
}


def main():
    # Stage 0: kill switch
    if os.environ.get("CLAUDE_SKILL_ROUTER_DISABLED"):
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        sys.exit(0)

    # Stage 0.5: intercept known slash commands → route to jintech-omg-dev skill variant.
    # Must run BEFORE Stage 1 exit so /debug, /ticket, etc. get a routing instruction
    # even though the slash command mechanism already pre-loads the base skill content.
    if prompt.startswith("/"):
        slash_match = re.match(r"^/([a-zA-Z0-9_-]+)(.*)", prompt)
        if slash_match:
            cmd = slash_match.group(1).lower()
            args = slash_match.group(2).strip()
            if cmd in SLASH_COMMAND_MAP:
                skill_id = SLASH_COMMAND_MAP[cmd]
                base = skill_base_name(skill_id)
                out = (
                    f"⚡ ROUTING ACTIVE: The user's request matches the `{base}` skill.\n"
                    f"You MUST invoke the Skill tool with skill=\"{skill_id}\" before doing anything else.\n"
                    f"Do not improvise the steps. The skill defines the exact procedure."
                )
                if args:
                    out += f"\nARGUMENTS: {args}"
                log_event(prompt, cmd, "skill")
                sys.stdout.write(out)
        sys.exit(0)  # Always exit for slash commands — routed or unknown

    # Stage 1: backslash explicit commands
    if prompt.startswith("\\"):
        sys.exit(0)

    try:
        manifest = load_manifest()
    except Exception:
        sys.exit(0)

    intents = manifest.get("intents", [])

    # Stage 2: high-confidence, first match wins
    for intent in intents:
        if intent.get("confidence") != "high":
            continue
        if match_intent(prompt, intent):
            out = render_output(intent)
            log_event(prompt, intent["id"], intent["action"]["type"])
            if out:
                sys.stdout.write(out)
            sys.exit(0)

    # Stage 3: low-confidence
    low_matches = [
        it for it in intents
        if it.get("confidence") == "low" and match_intent(prompt, it)
    ]
    if len(low_matches) == 0:
        sys.exit(0)
    if len(low_matches) == 1:
        out = render_low_confidence_single(low_matches[0])
        log_event(prompt, low_matches[0]["id"], low_matches[0]["action"]["type"])
        if out:
            sys.stdout.write(out)
        sys.exit(0)
    # 2+ low-confidence
    out = render_clarification_menu(low_matches)
    log_event(prompt, ",".join(i["id"] for i in low_matches), "menu")
    sys.stdout.write(out)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
