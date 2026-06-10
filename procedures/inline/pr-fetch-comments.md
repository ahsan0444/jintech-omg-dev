# Procedure: Fetch PR Review Comments

## Step 1 — Identify PR and List Comments

One Bash call. Credentials read from env inside Python (never in argv); pagination follows `next` links so PRs with >10 comments are fully covered.

```bash
REPO=$(basename "$(git rev-parse --show-toplevel)") BRANCH=$(git branch --show-current) python3 - <<'EOF'
import json, os, sys, urllib.request, base64

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

comments, url = [], f"{base}/pullrequests/{pr_id}/comments?pagelen=100"
while url:
    page = get(url)
    comments += page.get("values", [])
    url = page.get("next")  # follow pagination — never truncate

live = [c for c in comments if not c.get("deleted") and c.get("content", {}).get("raw", "").strip()]
open_c = [c for c in live if not c.get("resolved")]
print(f"PR_ID={pr_id}  Open: {len(open_c)}  Resolved: {len(live) - len(open_c)}")
for c in open_c:
    f = c.get("inline", {}).get("path", "general")
    l = c.get("inline", {}).get("to", "")
    print(f"[OPEN] {f}:{l} — {c['author']['display_name']}")
    print(f"  {c['content']['raw'][:300]}")
EOF
```

If output is `NO_OPEN_PR`: tell user no open PR for this branch.
If output is `ERROR: BITBUCKET_...`: tell user to set the env vars and restart the shell.
