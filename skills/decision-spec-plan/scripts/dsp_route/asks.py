# SPDX-License-Identifier: MIT
"""The user's messages to a route's lead, each owed a line in the ask list (F105).

UserPromptSubmit numbers each message of the user's (an agent's or a peer's return, and
the usage-limit prompt, are none) in `REGISTRY/<marker stem>.asks`, one log a planning
dir whichever lead session the user typed in, and tells the lead to list it in
`<planning-dir>/asks.md`: `Msg<n> | <the ask, and where it goes>` or `Msg<n> | not an
ask`. A message's number is one past the highest logged or listed, so a `Msg` line the
lead wrote never shares one. Until every message of the route has its line, the lead's
`exec-` dispatch is held, the end of its turn is sent back once, and a compaction is
told to keep the unlisted ones verbatim.

The log once lived per session (`REGISTRY/<session>.asks`): while the route's log does
not exist, the first call copies the current session's old rows of this route into it,
each under its old line number; nothing else is migrated.
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

Row = dict[str, object]


def _log(entry: RegistryEntry) -> pathlib.Path:
    return REGISTRY / f"{pathlib.Path(entry['marker']).stem}.asks"


def _list(entry: RegistryEntry) -> pathlib.Path:
    return pathlib.Path(entry["planning_dir"]) / "asks.md"


def _n(row: Row) -> int:
    """Return a logged row's message number, 0 without one."""
    n = row.get("n")
    return n if isinstance(n, int) else 0


def _parsed(text: str) -> list[Row]:
    """Return the rows of a log's text, a line that is no JSON object skipped."""
    return [r for line in text.splitlines() if (r := as_dict(parse_json(line)))]


def _rows(session: str, entry: RegistryEntry) -> list[Row]:
    """Return the route's logged messages, the session's old rows copied in first."""
    log = _log(entry)
    try:
        return _parsed(log.read_text())
    except FileNotFoundError:
        pass
    try:
        old = _parsed((REGISTRY / f"{session}.asks").read_text())
    except OSError:
        return []
    rows = [
        {**r, "n": n} for n, r in enumerate(old, 1) if r.get("route") == entry["marker"]
    ]
    if rows:
        _ = log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return rows


def _listed(entry: RegistryEntry) -> set[int]:
    """Return the numbers of the ask list's `Msg<n>` lines."""
    try:
        return {int(m[1]) for m in LISTED.finditer(_list(entry).read_text())}
    except OSError:
        return set[int]()


def record_ask(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> str | None:
    """Number a user message of the route and return the line that asks for its row."""
    prompt = str(event.get("prompt") or "").strip()
    if not prompt or is_return(prompt):
        return None
    rows = _rows(session, entry)
    # one past the highest logged or listed: one list held 39 duplicate numbers when
    # each session counted its own, and a lead's own Msg4 collided (F105)
    n = 1 + max([0, *map(_n, rows), *_listed(entry)])
    row = {
        "at": time.time(),
        "route": entry["marker"],
        "session": session,
        "n": n,
        "text": prompt,
    }
    with _log(entry).open("a") as f:
        _ = f.write(json.dumps(row) + "\n")
    return (
        f"This is user message Msg{n}. Give it a line in `{_list(entry)}` before your "
        f"next `exec-` dispatch or the end of this turn: `Msg{n} | <the ask, and the "
        f"task or row that carries it>`, or `Msg{n} | not an ask`. Each request in it "
        "is an ask, all of it — users came back with 'I asked you to fix all of the "
        "issues' (F105). Use exactly this number; never write a `Msg` line for "
        "anything but a user message the hook numbered — an AskUserQuestion answer is "
        "a `U<n>` line."
    )


def unlisted(session: str, entry: RegistryEntry) -> list[tuple[int, str]]:
    """Return the route's user messages with no line in the ask list: (number, text)."""
    listed = _listed(entry)
    return [
        (_n(r), str(r.get("text") or ""))
        for r in _rows(session, entry)
        if _n(r) not in listed
    ]


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


def keep(session: str, entry: RegistryEntry) -> str | None:
    """Return the compaction's instruction to keep the unlisted messages verbatim."""
    if not (rows := unlisted(session, entry)):
        return None
    head = (
        "Keep these user messages verbatim in the summary, each with its Msg-number: "
        f"the route's ask list `{_list(entry)}` has no line for them yet (F105).\n"
    )
    return (head + _quoted(rows, KEEP))[:KEEP]
