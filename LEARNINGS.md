# Learnings

## Tooling
- Git guardrails hook (`.claude/hooks/block-dangerous-git.py`) shlex-parses the Bash command and checks only real `git` argv, so mentioning blocked patterns in commit messages / `gh --body` is fine. Don't switch to regex over the raw command: it blocks any text that merely mentions a pattern.
- The hook fails closed: `settings.json` runs it as `python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/… || exit 2`, so a crash, missing `python3`, or a wrong/unset `CLAUDE_PROJECT_DIR` blocks every Bash call. If all Bash calls suddenly fail with a hook error, check those.
- Tests for the hook: `tests/test_git_guardrails.py` (add a case to BLOCKED/ALLOWED when changing rules).
- `.gitignore` ignores `.claude/*` except `settings.json` and `hooks/`; add a `!` rule to track anything else under `.claude/`.
- Bare `git push` on `main` is blocked; create the branch first (`git push -u origin <branch>` is allowed).
- `git push origin HEAD` / `@` on `main` is blocked too (HEAD resolves to the current branch). Known gaps: `cd <repo> && git push` judges the project dir's branch, and an unreadable branch (detached HEAD) allows the push.
- `git push`'s first positional is always the remote, so `git push HEAD:main` is not a bypass (git fails: "does not appear to be a git repository"). Check git's own parsing before "fixing" a reported hook bypass.

## Reviews
- `/code-review` sub-agents repeatedly claimed the `Co-Authored-By` trailer should name a different model. They were wrong every time; use the attribution the session's system reminder gives, not a sub-agent's.
