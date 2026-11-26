# SPDX-License-Identifier: MIT
"""Commands the lead hands the user in its last message, read as its turn ends (F107).

Each fenced block is one paste, and each inline `` `! cmd` `` span a block of one line.
Six shapes failed for users: a block that ends every WSL session among other lines
(pasted whole, PowerShell ran it at once), a program that opens its own prompt followed
by the lines meant for that prompt, a `cd` or `git -C` to a directory this machine does
not have, a relative one written from off the repository root (the user's shell starts
elsewhere), a Windows drive program in a block a WSL shell runs, and a `git push` to a
remote whose push URL is disabled.
"""

import pathlib
import re
from collections.abc import Mapping

from .common import git

FENCE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)
# an inline span the user runs in the session's own shell: a `!` line of its own
SPAN = re.compile(r"`(!\s*[^`\n]+)`")
KILL = re.compile(
    r"\bwsl(?:\.exe)?\s+(?:--terminate|-t|--shutdown|--unregister)\b", re.IGNORECASE
)
# a program that, run with no arguments, reads its own commands from the terminal
PROMPTS = re.compile(
    r"^\s*(diskpart|ftp|sftp|telnet|sqlplus|mysql|psql|python3?|node|irb|ghci)"
    r"(?:\.exe)?\s*$",
    re.IGNORECASE,
)
DIRS = re.compile(r"(?:^|[;&|]\s*)(cd|git\s+-C)\s+(['\"]?)((?:/|~/)[^\s'\";&|]*)\2")
# a path that is no absolute, home, computed, drive or `cd -` one
RELATIVE = re.compile(
    r"(?:^|[;&|]\s*)(cd|git\s+-C)\s+(['\"]?)((?![/~$%\\-])(?![A-Za-z]:)[^\s'\";&|]+)\2"
)
# a line that starts a program by its Windows drive path, quoted or not
DRIVE = re.compile(
    r"""^\s*(?:!\s*)?(?:&\s*)?(?:(['"])([A-Za-z]:\\[^'"]*)\1|([A-Za-z]:\\\S*))"""
)
# a POSIX path of two parts or a home one: the block runs in a WSL shell
POSIX = re.compile(r"(?:^|[\s'\"=])(?:~|/[\w.-]+)/[\w.-]")
PUSH = re.compile(r"\bgit\s+push\b[^;&|]*")
# git push's options that take the next word as their value
PUSH_VALUED = {"-o", "--push-option", "--receive-pack", "--exec"}


def _lines(block: str) -> list[str]:
    """Return a block's lines that run: no blank line or comment."""
    return [
        ln
        for ln in block.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "//", "REM ", "rem "))
    ]


def _off_root(cwd: str) -> bool:
    """Return whether cwd is not the root of a git repository."""
    code, top = git(cwd, "rev-parse", "--show-toplevel")
    return code != 0 or pathlib.Path(top).resolve() != pathlib.Path(cwd).resolve()


def _remote(push: str, cwd: str) -> str:
    """Return the remote a `git push …` command names, or the one git pushes to.

    With no remote word, the branch's push remote, the default push remote, the
    branch's remote, then `origin`, as git picks it.
    """
    words = push.split()[2:]
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--repo" and i + 1 < len(words):
            return words[i + 1]
        if w.startswith("--repo="):
            return w.removeprefix("--repo=")
        if not w.startswith("-"):
            return w.strip("'\"")
        i += 2 if w in PUSH_VALUED else 1
    _, branch = git(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    for key in (
        f"branch.{branch}.pushRemote",
        "remote.pushDefault",
        f"branch.{branch}.remote",
    ):
        code, name = git(cwd, "config", "--get", key)
        if code == 0 and name:
            return name
    return "origin"


def _disabled(push: str, cwd: str) -> str | None:
    """Return why a `git push …` fails on a disabled push URL, or None."""
    name = _remote(push, cwd)
    code, url = git(cwd, "remote", "get-url", "--push", name)
    if code != 0 or not (url == "no-push" or url.startswith("DISABLE")):
        return None
    return (
        f"`{push}`: remote `{name}`'s push URL is disabled (`{url}`), so the push "
        "fails — name a remote that pushes, or say plainly that none does"
    )


def _places(lines: list[str], cwd: str | None) -> list[str]:
    """Return the directories and remotes in a block's lines that fail from cwd."""
    out = [
        f"`{d[1]} {d[3]}`: no such directory on this machine"
        for ln in lines
        for d in DIRS.finditer(ln)
        if not pathlib.Path(d[3]).expanduser().exists()
    ]
    if cwd is None:
        return out
    relative = [d for ln in lines for d in RELATIVE.finditer(ln)]
    if relative and _off_root(cwd):
        out.extend(
            f"`{d[1]} {d[3]}`: a relative path, written from `{cwd}`, which is not "
            "the repository root: the user's shell may start anywhere — give the "
            "full path"
            for d in relative
        )
    out.extend(
        why
        for ln in lines
        for p in PUSH.finditer(ln)
        if (why := _disabled(p[0].strip(), cwd))
    )
    return out


def _block(block: str, cwd: str | None = None) -> list[str]:
    """Return what fails in one fenced block when the user pastes it from cwd."""
    raw = _lines(block)
    # a `!` line runs in the session's own shell: read its command after the `!`
    lines = [re.sub(r"^\s*!\s*", "", ln) for ln in raw]
    out: list[str] = []
    if len(lines) > 1 and any(KILL.search(ln) for ln in lines):
        out.append(
            "a block holds `wsl --terminate`/`--shutdown` among other lines: pasted "
            "whole, it runs with them and ends every WSL session, this one and its "
            "agents too — give it a block of its own, after the steps that must come "
            "first, with what it ends said above it"
        )
    if m := next((m for ln in lines[:-1] if (m := PROMPTS.match(ln))), None):
        out.append(
            f"`{m[1]}` opens its own prompt, so the lines after it in the block run in "
            "the shell instead: hand its commands as a script file (`diskpart /s "
            "<file>`, `psql -f <file>`) or as one block per step"
        )
    if any(ln.lstrip().startswith("!") or POSIX.search(ln) for ln in raw):
        out.extend(
            f"`{d[2] or d[3]}`: a Windows program in a block a WSL shell runs (a `!` "
            "line or a POSIX path beside it) — bash reads its `\\` as escapes: hand "
            "it in a PowerShell block of its own"
            for ln in raw
            if (d := DRIVE.match(ln))
        )
    return out + _places(lines, cwd)


def handed_hold(event: Mapping[str, object]) -> str | None:
    """Return why the commands in the lead's last message fail when pasted, if any.

    Each fenced block and each inline `! cmd` span outside them is read from the
    event's cwd.
    """
    text = str(event.get("last_assistant_message") or "")
    cwd = event.get("cwd")
    here = cwd if isinstance(cwd, str) and cwd else None
    blocks = [m[1] for m in FENCE.finditer(text)]
    blocks += [m[1] for m in SPAN.finditer(FENCE.sub("", text))]
    found = [p for b in blocks for p in _block(b, here)]
    if not found:
        return None
    return (
        "the commands you just handed the user fail when pasted — fix them, or say "
        "plainly why they stand (F107):\n- " + "\n- ".join(found)
    )
