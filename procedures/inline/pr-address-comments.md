# Procedure: Address PR Review Comments

## Step 1 — Identify PR and Fetch Unresolved Comments (grouped by file)

One Bash call. Credentials read from env inside Python (never in argv); pagination follows `next` links so PRs with >10 comments are fully covered.

```bash
REPO=$(basename "$(git rev-parse --show-toplevel)") BRANCH=$(git branch --show-current) python3 - <<'EOF'
import json, os, sys, urllib.request, base64
from itertools import groupby

repo, branch = os.environ["REPO"], os.environ["BRANCH"]
ws = os.environ.get("OMG_BITBUCKET_WORKSPACE", "zlalani")
user, token = os.environ.get("BITBUCKET_USER", ""), os.environ.get("BITBUCKET_TOKEN", "")
if not user or not token:
    sys.exit("ERROR: BITBUCKET_USER / BITBUCKET_TOKEN not set")
auth = base64.b64encode(f"{user}:{token}".encode()).decode()

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

base = f"https://api.bitbucket.org/2.0/repositories/{ws}/{repo}"
prs = get(f"{base}/pullrequests?q=source.branch.name%3D%22{branch}%22").get("values", [])
if not prs:
    sys.exit(f"NO_OPEN_PR for branch {branch}")
pr_id = prs[0]["id"]
print(f"PR_ID={pr_id}")

comments, url = [], f"{base}/pullrequests/{pr_id}/comments?pagelen=100"
while url:
    page = get(url)
    comments += page.get("values", [])
    url = page.get("next")  # follow pagination — never truncate

cs = [c for c in comments
      if not c.get("deleted") and not c.get("resolved") and c.get("content", {}).get("raw")]
key = lambda c: c.get("inline", {}).get("path", "general")
for f, g in groupby(sorted(cs, key=key), key=key):
    print(f"=== {f}")
    for c in g:
        print(f"  ID:{c['id']} L:{c.get('inline', {}).get('to', '?')} {c['content']['raw'][:200]}")
EOF
```

If output is `NO_OPEN_PR`: stop, tell user no open PR found.

## Step 2 — Address Each Comment

For each open comment: Read the file at the indicated line, apply minimal edit with Edit tool.

## Step 3 — Report

List: comment ID, file, line, what changed. Do not mark resolved unless user asks.
