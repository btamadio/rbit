#!/bin/bash

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command')

DANGEROUS_PATTERNS=(
  "git push.*(--force|--mirror| -f( |$)| \+[^ ])"
  "git push.*[ :]main( |$)"
  "git reset --hard"
  "git clean -fd"
  "git clean -f"
  "git branch -D"
  "git checkout \."
  "git restore \."
  "push --force"
  "reset --hard"
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern"; then
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented you from doing this." >&2
    exit 2
  fi
done

# Bare `git push [origin]` (no refspec) while on main would push main.
if echo "$COMMAND" | grep -qE "git push( -u| --set-upstream)*( origin)? *($|[;&|])" && [ "$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null)" = "main" ]; then
  echo "BLOCKED: '$COMMAND' would push from main. Push from a feature branch." >&2
  exit 2
fi

exit 0
