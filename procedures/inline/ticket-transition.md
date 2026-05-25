# Procedure: Transition Ticket Status

## Step 1 — Get Ticket ID
```bash
TICKET_ID=$(git branch --show-current | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
echo "TICKET_ID=${TICKET_ID:-none}"
```
If none: ask user for ticket ID.

## Step 2 — Fetch Transitions
```
1. mcp__claude_ai_Atlassian__getAccessibleAtlassianResources → cloudId
2. mcp__claude_ai_Atlassian__getTransitionsForJiraIssue cloudId + issueIdOrKey=<TICKET_ID>
   → [{id, name}]
```

## Step 3 — Apply
Match user's target status to nearest transition name (case-insensitive).
```
mcp__claude_ai_Atlassian__transitionJiraIssue:
  cloudId, issueIdOrKey=<TICKET_ID>, transitionId=<matched id>
```
If no match: list available transition names and ask user to choose.

## Step 4 — Confirm
Report: "<TICKET_ID> transitioned to <new status>."
