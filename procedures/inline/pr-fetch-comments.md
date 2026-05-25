# Procedure: Fetch PR Review Comments

## Step 1 — Identify PR
```bash
REPO=$(basename "$(git rev-parse --show-toplevel)")
BRANCH=$(git branch --show-current)
PR_ID=$(curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO}/pullrequests?q=source.branch.name%3D%22${BRANCH}%22" \
  | python3 -c "import sys,json; v=json.load(sys.stdin).get('values',[]); print(v[0]['id'] if v else 'none')")
```
If PR_ID = none: tell user no open PR for this branch.

## Step 2 — List Comments
```bash
curl -s -u "$BITBUCKET_USER:$BITBUCKET_TOKEN" \
  "https://api.bitbucket.org/2.0/repositories/zlalani/${REPO}/pullrequests/${PR_ID}/comments" \
  | python3 -c "
import sys,json
cs=[c for c in json.load(sys.stdin).get('values',[])
    if not c.get('deleted') and c.get('content',{}).get('raw','').strip()]
open_c=[c for c in cs if not c.get('resolved')]
print(f'Open: {len(open_c)}  Resolved: {len(cs)-len(open_c)}')
for c in open_c:
  f=c.get('inline',{}).get('path','general'); l=c.get('inline',{}).get('to','')
  print(f'[OPEN] {f}:{l} — {c[\"author\"][\"display_name\"]}')
  print(f'  {c[\"content\"][\"raw\"][:300]}')
"
```
