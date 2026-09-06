#!/bin/bash
# .claude/hooks/log-bash-trends.sh
# Appends one JSON line per Bash tool call for usage analytics.

INPUT=$(cat)

# Logging is best-effort: never block the command the user asked for.
command -v jq >/dev/null 2>&1 || exit 0

LOG_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || exit 0
LOG_FILE="$LOG_DIR/bash-usage-trends.jsonl"

COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
[ -n "$COMMAND" ] || exit 0

CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)
[ -n "$CURRENT_BRANCH" ] || CURRENT_BRANCH="detached"

# jq -n builds the JSON so quotes/backslashes/newlines escape correctly.
jq -n -c \
  --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  --arg user "${USER:-unknown}" \
  --arg branch "$CURRENT_BRANCH" \
  --arg command "$COMMAND" \
  '{timestamp: $timestamp, user: $user, branch: $branch, command: $command}' \
  >> "$LOG_FILE" 2>/dev/null

exit 0
