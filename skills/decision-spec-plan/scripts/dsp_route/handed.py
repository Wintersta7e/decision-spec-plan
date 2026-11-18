# SPDX-License-Identifier: MIT
"""Commands the lead hands the user in its last message, read as its turn ends (F107).

Each fenced block is one paste. Three shapes failed for users: a block that ends every
WSL session among other lines (pasted whole, PowerShell ran it at once), a program that
opens its own prompt followed by the lines meant for that prompt, and a `cd` or
`git -C` to a directory this machine does not have.
"""

import pathlib
import re
from collections.abc import Mapping

FENCE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)
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


def _lines(block: str) -> list[str]:
    """Return a block's lines that run: no blank line or comment."""
    return [
        ln
        for ln in block.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "//", "REM ", "rem "))
    ]


def _block(block: str) -> list[str]:
    """Return what fails in one fenced block when the user pastes it."""
    lines = _lines(block)
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
    out.extend(
        f"`{d[1]} {d[3]}`: no such directory on this machine"
        for ln in lines
        for d in DIRS.finditer(ln)
        if not pathlib.Path(d[3]).expanduser().exists()
    )
    return out


def handed_hold(event: Mapping[str, object]) -> str | None:
    """Return why the commands in the lead's last message fail when pasted, if any."""
    text = str(event.get("last_assistant_message") or "")
    found = [p for m in FENCE.finditer(text) for p in _block(m[1])]
    if not found:
        return None
    return (
        "the commands you just handed the user fail when pasted — fix them, or say "
        "plainly why they stand (F107):\n- " + "\n- ".join(found)
    )
