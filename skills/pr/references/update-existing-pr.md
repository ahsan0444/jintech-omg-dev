# /pr — Update Existing PR

Loaded on demand when Step 2 finds an existing PR. BB_WORKSPACE, REPO_ROOT, REPO_NAME, PR_URL_EXISTING come from Steps 1–2.

---

# § Update existing PR (rebase + description)

### If PR_EXISTS = yes

First extract the PR ID and destination branch from the existing PR URL and API response:

```bash
PR_ID=$(echo "$PR_URL_EXISTING" | grep -o '[0-9]*$')
PR_DEST_BRANCH=$(printf 'user = "%s:%s"\n' "$BITBUCKET_USER" "$BITBUCKET_TOKEN" | curl -s -K - \
  "https://api.bitbucket.org/2.0/repositories/${BB_WORKSPACE}/${REPO_NAME}/pullrequests/${PR_ID}" \
  | grep -o '"destination":{[^}]*"name":"[^"]*"' | grep -o '"name":"[^"]*"' | tail -1 | sed 's/"name":"//;s/"//')
```

**Check if rebase is needed:**

```bash
git -C "$REPO_ROOT" fetch origin
git -C "$REPO_ROOT" merge-base --is-ancestor origin/<PR_DEST_BRANCH> HEAD
echo "REBASE_NEEDED=$?"
```

`REBASE_NEEDED=0` → already up to date — skip rebase, go straight to description update.
`REBASE_NEEDED=1` → destination has moved ahead — rebase required.

**If rebase required:**

```bash
git -C "$REPO_ROOT" rebase origin/<PR_DEST_BRANCH>
```

If rebase fails:
```bash
git -C "$REPO_ROOT" diff --name-only --diff-filter=U
```
Output:
```
Rebase conflict in the following files:
  <conflicting files>

Resolve conflicts, then:
  git add <file>
  git rebase --continue
  git push --force-with-lease

Re-run /pr after pushing to update the PR description.
```
Stop.

If rebase succeeds:
```bash
git -C "$REPO_ROOT" push --force-with-lease
```

**Update PR description** — use the **Write tool** to write `/tmp/pr_update.json`:
```json
{"description": "<PR_BODY>"}
```

Then:
```bash
printf 'user = "%s:%s"\n' "$BITBUCKET_USER" "$BITBUCKET_TOKEN" | curl -s -K - -X PUT \
  -H "Content-Type: application/json" \
  -d @/tmp/pr_update.json \
  "https://api.bitbucket.org/2.0/repositories/${BB_WORKSPACE}/<REPO_NAME>/pullrequests/<PR_ID>" \
  -o /tmp/pr_update_response.json -w "HTTP_STATUS:%{http_code}\n"
```

Output:
```
PR already exists: <PR_URL>
<if rebase ran>  Rebased onto origin/<PR_DEST_BRANCH> and pushed.
<if skipped>     Branch already up to date — no rebase needed.
PR description updated.
```

---
