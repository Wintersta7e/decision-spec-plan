# SPDX-License-Identifier: MIT
"""The user's messages to a route's lead, each owed a line in the ask list (F105).

UserPromptSubmit numbers each message of the user's (an agent's return is none) in
`REGISTRY/<session>.asks` and tells the lead to list it in `<planning-dir>/asks.md`:
`Msg<n> | <the ask, and where it goes>` or `Msg<n> | not an ask`. Until every message of
the route has its line, the lead's `exec-` dispatch is held, the end of its turn is
sent back once, and a compaction is told to keep the unlisted ones verbatim.
"""

import json
import pathlib
import re
import time
from collections.abc import Mapping

from .common import REGISTRY, RegistryEntry, as_dict, is_return, parse_json

LISTED = re.compile(r"^\W*Msg(\d+)\b", re.MULTILINE)
SHOWN = 300  # characters of a message a hold quotes
KEEP = 9000  # PreCompact's stdout is cut at 10,000 characters


def _log(session: str) -> pathlib.Path:
    return REGISTRY / f"{session}.asks"


def _list(entry: RegistryEntry) -> pathlib.Path:
    return pathlib.Path(entry["planning_dir"]) / "asks.md"


def record_ask(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> str | None:
    """Number a user message of the route and return the line that asks for its row."""
    prompt = str(event.get("prompt") or "").strip()
    if not prompt or is_return(prompt):
        return None
    log = _log(session)
    n = len(log.read_text().splitlines()) + 1 if log.exists() else 1
    row = {"at": time.time(), "route": entry["marker"], "text": prompt}
    with log.open("a") as f:
        _ = f.write(json.dumps(row) + "\n")
    return (
        f"This is user message Msg{n}. Give it a line in `{_list(entry)}` before your "
        f"next `exec-` dispatch or the end of this turn: `Msg{n} | <the ask, and the "
        f"task or row that carries it>`, or `Msg{n} | not an ask`. Each request in it "
        "is an ask, all of it — users came back with 'I asked you to fix all of the "
        "issues' (F105)."
    )


def unlisted(session: str, entry: RegistryEntry) -> list[tuple[int, str]]:
    """Return the route's user messages with no line in the ask list: (number, text)."""
    try:
        rows = _log(session).read_text().splitlines()
    except FileNotFoundError:
        return []
    try:
        text = _list(entry).read_text()
        listed = {int(m[1]) for m in LISTED.finditer(text)}
    except OSError:
        listed = set[int]()
    out: list[tuple[int, str]] = []
    for n, line in enumerate(rows, 1):
        row = as_dict(parse_json(line)) or {}
        if row.get("route") == entry["marker"] and n not in listed:
            out.append((n, str(row.get("text") or "")))
    return out


def _quoted(rows: list[tuple[int, str]], width: int) -> str:
    return "\n".join(
        f"Msg{n}: {t[:width]}{'…' if len(t) > width else ''}" for n, t in rows
    )


def asks_hold(session: str, entry: RegistryEntry) -> str | None:
    """Return why an `exec-` dispatch or the end of a turn waits on the ask list."""
    if not (rows := unlisted(session, entry)):
        return None
    return (
        f"user messages with no line in `{_list(entry)}` — list each as `Msg<n> | <the "
        "ask, and the task or row that carries it>` or `Msg<n> | not an ask`, then go "
        f"on (F105):\n{_quoted(rows, SHOWN)}"
    )


def stop_hold(event: Mapping[str, object], session: str, entry: RegistryEntry) -> int:
    """Send the lead's turn back once while a user message has no line; 0."""
    if event.get("stop_hook_active") or not (why := asks_hold(session, entry)):
        return 0
    print(json.dumps({"decision": "block", "reason": why}))
    return 0


def keep(session: str, entry: RegistryEntry) -> str | None:
    """Return the compaction's instruction to keep the unlisted messages verbatim."""
    if not (rows := unlisted(session, entry)):
        return None
    head = (
        "Keep these user messages verbatim in the summary, each with its Msg-number: "
        f"the route's ask list `{_list(entry)}` has no line for them yet (F105).\n"
    )
    return (head + _quoted(rows, KEEP))[:KEEP]
