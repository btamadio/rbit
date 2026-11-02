# Learnings

## Tooling
- Git guardrails hook (`.claude/hooks/block-dangerous-git.py`) shlex-parses the Bash command and checks only real `git` argv, so mentioning blocked patterns in commit messages / `gh --body` is fine. The first version regex-matched raw text and blocked its own PR body; don't go back to text matching.
- The hook fails closed: `settings.json` runs it as `python3 … || exit 2`, so a crash or missing `python3` blocks every Bash call. If all Bash calls suddenly fail with a hook error, check `python3` on PATH first.
- Tests for the hook: `tests/test_git_guardrails.py` (add a case to BLOCKED/ALLOWED when changing rules).
- `.gitignore` ignores `.claude/*` except `settings.json` and `hooks/`; add a `!` rule to track anything else under `.claude/`.
- Bare `git push` on `main` is blocked; create the branch first (`git push -u origin <branch>` is allowed).
