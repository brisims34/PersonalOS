#!/bin/bash
# .claude/hooks/log-bash-trends.sh

# Ensure the log directory exists
LOG_DIR=".claude/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/bash-usage-trends.jsonl"

# CLAUDE_TOOL_CALL contains the full payload (e.g., "Bash(npm test)")
# Extract just the raw command payload inside the parentheses
RAW_COMMAND=$(echo "$CLAUDE_TOOL_CALL" | sed -E 's/^Bash\((.*)\)$/\1/')

# Capture system environment metadata
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
USER_ID=${USER:-"unknown"}
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")

# Escape quotes and backslashes for safe JSON structural output
SAFE_COMMAND=$(echo "$RAW_COMMAND" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')

# Format the payload as a single JSON line for analytics aggregation
cat <<EOF >> "$LOG_FILE"
{"timestamp": "$TIMESTAMP", "user": "$USER_ID", "branch": "$CURRENT_BRANCH", "command": "$SAFE_COMMAND"}
EOF

# Always exit 0 so Claude isn't blocked from executing the actual command
exit 0
