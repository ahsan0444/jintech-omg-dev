---
description: Show skill-router match statistics from ~/.claude/logs/intent-router-*.jsonl and prune logs older than 30 days. Use to spot misrouting intents and dead patterns before tuning skill-routing-manifest.json.
argument-hint: "[days to analyse (default 30)]"
allowed-tools: Bash(python3 *)
---

# /router-stats

Analyse the skill-router's match log, then prune old log files. Run directly in main context — one Bash call.

```bash
DAYS="${ARGUMENTS_DAYS:-30}" python3 - <<'EOF'
import glob, json, os, sys, time
from collections import Counter
from datetime import datetime, timedelta, timezone

days = int(os.environ.get("DAYS", "30") or 30)
log_dir = os.path.expanduser("~/.claude/logs")
files = sorted(glob.glob(os.path.join(log_dir, "intent-router-*.jsonl")))
if not files:
    sys.exit("NO_LOGS — router has not matched anything yet (or logging is disabled).")

cutoff = datetime.now(timezone.utc) - timedelta(days=days)
intents, actions, total, parse_errors = Counter(), Counter(), 0, 0
first_ts = last_ts = None

for path in files:
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(e["ts"])
            except Exception:
                parse_errors += 1
                continue
            if ts < cutoff:
                continue
            total += 1
            first_ts = min(first_ts or ts, ts)
            last_ts = max(last_ts or ts, ts)
            intents[e.get("matched_intent", "?")] += 1
            actions[e.get("action_type", "?")] += 1

print(f"Router matches, last {days} days: {total}"
      + (f"  ({first_ts:%Y-%m-%d} → {last_ts:%Y-%m-%d})" if total else ""))
print(f"By action type: {dict(actions)}")
print("Top intents:")
for intent, n in intents.most_common(15):
    print(f"  {n:>4}  {intent}")
if parse_errors:
    print(f"(skipped {parse_errors} unparseable lines)")

# Prune: delete daily log files older than 30 days (file date is in the name)
pruned = 0
for path in files:
    name = os.path.basename(path)  # intent-router-YYYY-MM-DD.jsonl
    try:
        d = datetime.strptime(name[len("intent-router-"):-len(".jsonl")], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        continue
    if d < datetime.now(timezone.utc) - timedelta(days=30):
        os.remove(path)
        pruned += 1
print(f"Pruned {pruned} log file(s) older than 30 days.")
EOF
```

If `$ARGUMENTS` contains a number, export it as `ARGUMENTS_DAYS` in the command above (e.g. `/router-stats 7` → `ARGUMENTS_DAYS=7`).

## Interpreting the output

- **An intent with a high count you don't recognise triggering** → its pattern is too loose. Tighten it in `skill-routing-manifest.json` (plugin copy, or your `~/.claude/skill-routing-manifest.json` override).
- **An intent that never appears** → dead pattern; consider removing it, or its phrasing doesn't match how you actually type.
- **`menu` action entries** → prompts that matched 2+ low-confidence intents; refine those patterns to separate them.
