#!/usr/bin/env python3
"""PreToolUse hook: block destructive git commands. Exit 2 blocks; any crash blocks via `|| exit 2` in settings."""
import json
import os
import shlex
import subprocess
import sys

SHELLS = {"bash", "sh", "zsh"}
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def segments(cmd):
    """Split a shell command into word lists at ; && || | & and newlines."""
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:  # unbalanced quotes: fall back to plain words
        tokens = cmd.split()
    seg = []
    for tok in tokens:
        if tok and set(tok) <= set(";&|()"):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def git_calls(cmd):
    """Yield (cwd, subcommand, args) for each git invocation, recursing into `sh -c` / `eval`."""
    for seg in segments(cmd):
        while seg and "=" in seg[0] and not seg[0].startswith("-"):  # VAR=val prefixes
            seg = seg[1:]
        while seg and seg[0] in {"sudo", "command", "exec", "nohup", "time"}:
            seg = seg[1:]
        if not seg:
            continue
        prog = os.path.basename(seg[0])
        if prog in SHELLS and "-c" in seg[1:-1]:
            yield from git_calls(seg[seg.index("-c") + 1])
        elif prog == "eval":
            yield from git_calls(" ".join(seg[1:]))
        elif prog == "git":
            cwd, i = None, 1
            while i < len(seg) and seg[i].startswith("-"):
                if seg[i] in GIT_OPTS_WITH_VALUE:
                    if seg[i] == "-C" and i + 1 < len(seg):
                        cwd = seg[i + 1]
                    i += 1
                i += 1
            if i < len(seg):
                yield cwd, seg[i], seg[i + 1:]


def short_flags(args):
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def is_main(ref, cwd):
    dst = ref.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
    if dst in {"HEAD", "@"}:  # `push origin HEAD` pushes the current branch
        dst = current_branch(cwd)
    return dst == "main"


def current_branch(cwd):
    base = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    path = os.path.join(base, cwd) if cwd else base
    out = subprocess.run(["git", "-C", path, "branch", "--show-current"], capture_output=True, text=True)
    return out.stdout.strip()


def reason(cwd, sub, args):
    flags = short_flags(args)
    positional = [a for a in args if not a.startswith("-")]
    if sub == "push":
        if "f" in flags or any(a.startswith(("--force", "--mirror", "--all")) for a in args):
            return "force/mirror/all push"
        refspecs = positional[1:]
        if any(r.startswith("+") for r in refspecs):
            return "force push (+refspec)"
        if any(is_main(r, cwd) for r in refspecs):
            return "push to main"
        if not refspecs and current_branch(cwd) == "main":
            return "bare push from main"
    if sub == "reset" and "--hard" in args:
        return "reset --hard"
    if sub == "clean" and ("f" in flags or "--force" in args):
        return "clean -f"
    if sub == "branch":
        delete = "d" in flags or "--delete" in args
        force = "f" in flags or "--force" in args
        if "D" in flags or (delete and force):
            return "force branch delete"
    if sub in {"checkout", "restore"} and "." in positional:
        if sub == "restore" and "--staged" in args and not ({"--worktree", "-W"} & set(args)):
            return None  # unstaging only; worktree untouched
        return f"{sub} ."
    return None


def main():
    command = json.load(sys.stdin)["tool_input"]["command"]
    for cwd, sub, args in git_calls(command):
        why = reason(cwd, sub, args)
        if why:
            print(f"BLOCKED ({why}): '{command}'. The user has prevented you from doing this.", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
