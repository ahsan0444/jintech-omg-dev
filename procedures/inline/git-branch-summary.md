# Procedure: Show Branch Changes

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
BASE=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@' || echo "master")

echo "=== Branch: $(git branch --show-current) vs origin/$BASE ==="
echo ""
echo "--- Commits ---"
git log origin/${BASE}...HEAD --oneline

echo ""
echo "--- Files changed ---"
git diff origin/${BASE}...HEAD --stat

echo ""
echo "--- File list ---"
git diff origin/${BASE}...HEAD --name-status
```
