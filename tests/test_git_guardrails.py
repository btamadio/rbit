import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block-dangerous-git.py"

BLOCKED = [
    "git push --force origin feat",
    "git push -f origin feat",
    "git push origin feat --force",
    "git push origin feat -f",
    "git push origin -fu feat",
    "git push --force-with-lease origin feat",
    "git -C . push -f origin feat",
    "git -c core.x=1 push --force origin feat",
    "git push --mirror origin",
    "git push --all origin",
    "git push origin +feat:feat",
    "git push origin main",
    "git push origin main;echo",
    "git push origin 'main'",
    'git push origin HEAD:"main"',
    "git push origin feat:main",
    "git push origin HEAD:main",
    "git push origin +HEAD",
    "git push origin HEAD:refs/heads/main",
    "git push origin refs/heads/main",
    "git push origin :main",
    "git push origin --delete main",
    "git checkout -b x && git push -f origin x",
    "bash -c 'git push -f origin feat'",
    "FOO=1 git reset --hard",
    "git reset --hard HEAD~1",
    "git reset HEAD~1 --hard",
    "git clean -f",
    "git clean -fd",
    "git clean -xfd",
    "git clean -x -f",
    "git clean --force",
    "git branch -D feat",
    "git branch -df feat",
    "git branch --delete --force feat",
    "git checkout .",
    "git checkout -- .",
    "git checkout HEAD -- .",
    "git restore .",
    "git restore -- .",
    "git restore --staged --worktree .",
]

ALLOWED = [
    "git status",
    "git push -u origin feat",
    "git push origin feat --no-verify",
    "git push origin main-fix",
    "git push origin HEAD:feat",
    "git push origin feat/main-thing",
    "git checkout -b maintenance && git push -u origin maintenance",
    "git push origin --delete feat",
    "git checkout main",
    "git checkout .gitignore",
    "git restore .github/workflows/ci.yml",
    "git restore --staged .",
    "git reset --keep HEAD~1",
    "git clean -n",
    "git branch -d feat",
    'git commit -m "docs: never git reset --hard or git push -f"',
    'gh pr create --body "Blocks git push --force to main"',
    "echo git push -f",
]


def run(command, project_dir):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)},
    )


@pytest.fixture(scope="module")
def repo_on(tmp_path_factory):
    def make(branch):
        path = tmp_path_factory.mktemp(branch)
        subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
        return path
    return make


@pytest.mark.parametrize("command", BLOCKED)
def test_blocked(command, repo_on):
    out = run(command, repo_on("feat"))
    assert out.returncode == 2, out.stderr
    assert "BLOCKED" in out.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command, repo_on):
    out = run(command, repo_on("feat"))
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("command", [
    "git push", "git push origin", "git push -u origin",
    "git push origin HEAD", "git push -u origin HEAD", "git push origin @",
    "git push origin HEAD:HEAD", "git push origin refs/heads/HEAD", "git -C . push origin HEAD",
])
def test_push_of_current_branch_blocked_on_main_only(command, repo_on):
    assert run(command, repo_on("main")).returncode == 2
    assert run(command, repo_on("feat")).returncode == 0


def test_malformed_input_fails_closed():
    out = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    assert out.returncode != 0
