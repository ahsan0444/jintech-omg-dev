#!/usr/bin/env python3
"""
SessionEnd hook: scan the session transcript for user messages that look like
corrections ("no", "wrong", "actually", ...) and stash them as raw material
for the weekly consolidate-memory pass.

Input (SessionEnd, per official docs): JSON on stdin with at least
  session_id, transcript_path, cwd, reason ("clear"|"resume"|"logout"|
  "prompt_input_exit"|"other"), hook_event_name.

Only real, user-typed turns count: message.role == "user" AND
message.content is a plain string (tool_result turns arrive as a list of
content blocks and are skipped), further filtered to drop synthetic text
that starts with '<' (e.g. <task-notification>, <bash-input>, other
system-injected blocks) and anything starting with "[SYSTEM NOTIFICATION".

A message is "correction-shaped" if it matches CORRECTION_RE and its length
is in [MIN_LEN, MAX_LEN]. For each match we keep the trimmed message plus up
to 200 trailing chars of the preceding assistant text turn, for context.

Secrets are redacted before anything is written to disk (see redact()).

Output: appends a dated section to
  ~/.claude/projects/<slug>/memory/_pending-corrections.md
where slug = cwd with '/' replaced by '-'. Capped at MAX_ITEMS per run; if
the file would exceed MAX_FILE_LINES, we append a single line saying
consolidation is needed instead of growing it further. Never blocks (this
event can't block anyway) and never raises past main(). Env CAPTURE_OUT
overrides the output path (used by tests).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

MIN_LEN = 8
MAX_LEN = 600
MAX_ITEMS = 15
MAX_FILE_LINES = 400
TRIM_MESSAGE = 300
TRIM_CONTEXT = 200

CORRECTION_RE = re.compile(
    r"\b(no|nope|wrong|still (not|doesn't|broken)|doesn't match|not what I|"
    r"instead|actually|stop|don't|revert|undo|why did you)\b",
    re.IGNORECASE,
)

SKIP_PREFIXES = ("<", "[SYSTEM NOTIFICATION")

FILE_HEADER = (
    "# Pending Corrections (raw capture — NOT memory)\n\n"
    "This file is raw input for the weekly `consolidate-memory` run. It is\n"
    "appended to automatically at the end of every session by\n"
    "`session-end-capture.py` and is **not** itself a source of memory — do\n"
    "not read it as fact, and do not hand-edit it expecting it to affect\n"
    "behavior. Consolidation reviews these entries and promotes anything\n"
    "worth keeping into the real memory files.\n"
)

SECRET_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[opsu]_[A-Za-z0-9]+"),
    re.compile(r"ATBB[A-Za-z0-9]+"),
    re.compile(r"xox[bp]-[A-Za-z0-9-]+"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"figd_[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"(?i)\b(password|token|secret)\b\s*[:=]\s*\S+"),
]


# ---------------------------------------------------------------- redaction
def redact(text):
    out = text or ""
    for pat in SECRET_PATTERNS:
        out = pat.sub("<REDACTED>", out)
    return out


# ---------------------------------------------------------------- transcript parsing
def user_text(message):
    """Return the plain text of a user turn, or None if it's not a real
    user-typed string (e.g. a tool_result list)."""
    content = message.get("content")
    if not isinstance(content, str):
        return None
    return content


def assistant_text(message):
    """Best-effort plain text out of an assistant turn's content, which may
    be a string or a list of content blocks (text/tool_use/...)."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def should_skip(text):
    stripped = text.strip()
    if not stripped:
        return True
    return any(stripped.startswith(p) for p in SKIP_PREFIXES)


def is_correction(text):
    if not (MIN_LEN <= len(text) <= MAX_LEN):
        return False
    return bool(CORRECTION_RE.search(text))


def iter_transcript_entries(transcript_path):
    with open(transcript_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def extract_corrections(transcript_path, max_items=MAX_ITEMS):
    """Walk the transcript in order, pairing each correction-shaped user
    message with the preceding assistant text (trimmed). Returns a list of
    dicts: {"message": ..., "context": ...}."""
    results = []
    last_assistant_text = ""
    for entry in iter_transcript_entries(transcript_path):
        if entry.get("isSidechain"):
            continue
        message = entry.get("message") or {}
        role = message.get("role") or entry.get("type")

        if role == "assistant":
            text = assistant_text(message)
            if text:
                last_assistant_text = text
            continue

        if role != "user":
            continue

        text = user_text(message)
        if text is None or should_skip(text):
            continue

        if is_correction(text):
            trimmed_msg = redact(text.strip())[:TRIM_MESSAGE]
            context = redact(last_assistant_text.strip())[-TRIM_CONTEXT:]
            results.append({"message": trimmed_msg, "context": context})
            if len(results) >= max_items:
                break

    return results


# ---------------------------------------------------------------- output
def slug_for_cwd(cwd):
    return cwd.replace("/", "-")


def memory_dir_for_cwd(cwd, home=None):
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".claude", "projects", slug_for_cwd(cwd), "memory")


def render_section(entries, when=None):
    when = when or datetime.now(timezone.utc)
    lines = [f"## {when.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for e in entries:
        lines.append(f"- **User:** {e['message']}")
        if e["context"]:
            lines.append(f"  - _preceding assistant context:_ {e['context']}")
    lines.append("")
    return "\n".join(lines)


def count_lines(path):
    try:
        with open(path, "r") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def append_corrections(out_path, entries):
    """Append a dated section for `entries` to out_path, creating the file
    (with header) if needed. If the file is already too long, appends a
    single consolidation-needed note instead. No-op if entries is empty."""
    if not entries:
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    existing_lines = count_lines(out_path)
    if existing_lines > MAX_FILE_LINES:
        with open(out_path, "a") as f:
            f.write("\n_(consolidation needed — file exceeds size cap, not appending further)_\n")
        return

    is_new = not os.path.exists(out_path)
    section = render_section(entries)
    with open(out_path, "a") as f:
        if is_new:
            f.write(FILE_HEADER + "\n")
        f.write(section)


# ---------------------------------------------------------------- main
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    transcript_path = data.get("transcript_path") or ""
    cwd = data.get("cwd") or os.getcwd()

    if not transcript_path or not os.path.isfile(transcript_path):
        sys.exit(0)

    try:
        entries = extract_corrections(transcript_path)
    except Exception:
        sys.exit(0)

    if not entries:
        sys.exit(0)

    out_path = os.environ.get("CAPTURE_OUT") or os.path.join(
        memory_dir_for_cwd(cwd), "_pending-corrections.md"
    )

    try:
        append_corrections(out_path, entries)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
