# Procedure: Address PR Review Comments

## Step 1 — Identify PR
```bash
REPO=$(basename "$(git rev-parse --show-toplevel)")
BRANCH=$(git branch --show-current)
PR_ID=$(curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO}/pullrequests?q=source.branch.name%3D%22${BRANCH}%22" \
  | python3 -c "import sys,json; v=json.load(sys.stdin).get('values',[]); print(v[0]['id'] if v else 'none')")
echo "PR_ID=$PR_ID"
```
If PR_ID = none: stop, tell user no open PR found.

## Step 2 — Fetch Unresolved Comments (grouped by file)
```bash
curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO}/pullrequests/${PR_ID}/comments" \
  | python3 -c "
import sys,json; from itertools import groupby
cs=[c for c in json.load(sys.stdin).get('values',[]) if not c.get('deleted') and not c.get('resolved') and c.get('content',{}).get('raw')]
key=lambda c:c.get('inline',{}).get('path','general')
[print(f'=== {f}') or [print(f'  ID:{c[\"id\"]} L:{c.get(\"inline\",{}).get(\"to\",\"?\")} {c[\"content\"][\"raw\"][:200]}') for c in g] for f,g in groupby(sorted(cs,key=key),key=key)]
"
```

## Step 3 — Address Each Comment
For each open comment: Read the file at the indicated line, apply minimal edit with Edit tool.

## Step 4 — Report
List: comment ID, file, line, what changed. Do not mark resolved unless user asks.
