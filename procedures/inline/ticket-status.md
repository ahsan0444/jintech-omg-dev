# Procedure: Fetch Ticket Status

## Step 1 — Get Ticket ID

Extract from current branch or use ticket ID from user message:
```bash
TICKET_ID=$(git branch --show-current | grep -oiE 'OMGXI-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
echo "TICKET_ID=${TICKET_ID:-none}"
```

If TICKET_ID = none: ask the user to provide the ticket ID.

## Step 2 — Fetch via Atlassian MCP

```
1. Call mcp__claude_ai_Atlassian__getAccessibleAtlassianResources → get cloudId
2. Call mcp__claude_ai_Atlassian__getJiraIssue with cloudId and issueIdOrKey=<TICKET_ID>
```

## Step 3 — Display

Show in this format:
- **Ticket:** OMGXI-XXXX — <title>
- **Status:** <status>
- **Assignee:** <name>
- **Summary:** <2-3 sentence description>
- **Acceptance Criteria:** (if present)
