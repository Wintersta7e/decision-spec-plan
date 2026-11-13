# SPDX-License-Identifier: MIT
"""The monitor's event log: one JSON line per hook event of a routed session.

`record()` builds the line from the payload, the session's registry entry and the
call's decision, and appends it to `EVENTS/<session>.jsonl` under an `flock`; `sweep()`
removes logs and heartbeat stamps past `RETENTION_DAYS`. No prompt, message, tool
input beyond the named fields, error text, working directory or tool output is ever
stored. Both raise what they meet: the hook calls them through `common.checked`, so a
failure costs one line, never the call.
"""

import contextlib
import json
import os
import re
import stat
import time
from collections.abc import Callable, Mapping

from .common import REGISTRY, as_dict, as_list, is_return

try:
    import fcntl
except ImportError:  # Windows: the log is written unlocked
    fcntl = None

SCHEMA = 1
EVENTS = REGISTRY / "events"
# bytes, the newline included
LINE_MAX = 4096
CAP_BYTES = 32 * 1024 * 1024
HEARTBEAT_S = 60
RETENTION_DAYS = 14
SWEEP_S = 86400
# about 23 ms of waiting at most, then the line is dropped: the hook never waits longer.
# Many short tries: a lock is held well under a millisecond, and 10 tries 2 ms apart
# could all land on holds and lose a line under 40 parallel writers
LOCK_TRIES = 50
LOCK_WAIT_S = 0.0004
KINDS = (
    "dispatch",
    "launch",
    "return",
    "failed",
    "start",
    "stop",
    "idle",
    "pre",
    "post",
    "prompt",
    "turn-end",
    "api-error",
    "notify",
    "compact",
    "session",
    "session-end",
    "cap",
)
AGENT_STATES = (
    "dispatched",
    "held",
    "launched",
    "active",
    "idle",
    "returned",
    "stopped",
    "failed",
    "interrupted",
    "ended-with-session",
    "lost",
)
AGENT_MODES = ("foreground", "background", "teammate")
SESSION = re.compile(r"[A-Za-z0-9_-]{1,128}")

# a FIFO at the log's path fails instead of blocking; a symlink there is refused
_OPEN = (
    os.O_WRONLY
    | os.O_APPEND
    | os.O_CREAT
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_HOLD = re.compile(r"\(F(\d+)\)")
_GAP_VALUE = 40
# the launch statuses of an Agent call and the mode each starts
_LAUNCHED = {"async_launched": "background", "teammate_spawned": "teammate"}
_USAGE = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
# (kind, field): the field's length limit
_LIMITS = {("post", "target"): 128}
# what goes, in turn, while a line is over LINE_MAX; then only _JOIN stays
_DROPS = (("planning_dir", "marker"),)
_JOIN = ("v", "ts", "session", "run", "hook", "ev")

Fields = dict[str, object]
Built = tuple[str, Fields, list[str]]


def _typed(value: object, kind: type[object]) -> bool:
    """Return whether value has JSON type kind: a bool is no int."""
    return isinstance(value, kind) and (kind is bool or not isinstance(value, bool))


def _copy(
    out: Fields, src: Mapping[str, object], *keys: tuple[str, str, type[object]]
) -> None:
    """Copy each (key, field, type) of src into out as key, when it has that type."""
    for key, field, kind in keys:
        value = src.get(field)
        if _typed(value, kind):
            out[key] = value


def _sub(event: Mapping[str, object], key: str) -> Fields:
    """Return the payload's object at key, empty when it is none."""
    return as_dict(event.get(key)) or {}


def _tool(event: Mapping[str, object], fields: Fields) -> list[str]:
    """Put a tool hook's `tuid` into fields; return the gaps of its tool fields."""
    _copy(fields, event, ("tuid", "tool_use_id", str))
    return [f for f in ("tool_name", "tool_use_id") if not _typed(event.get(f), str)]


def _pre(event: Mapping[str, object]) -> Built:
    """PreToolUse: an Agent call is a `dispatch`, any other tool a `pre`."""
    fields: Fields = {}
    gaps = _tool(event, fields)
    given = _sub(event, "tool_input")
    tool = event.get("tool_name")
    if tool == "Agent":
        _copy(
            fields,
            given,
            ("name", "name", str),
            ("subagent_type", "subagent_type", str),
        )
        bg = given.get("run_in_background")
        fields["bg"] = bg is True or bg == "true"
        return "dispatch", fields, gaps
    _copy(fields, event, ("tool", "tool_name", str))
    return "pre", fields, gaps


def _agent_post(event: Mapping[str, object], fields: Fields, gaps: list[str]) -> Built:
    """PostToolUse of an Agent call that launched (`launch`) or returned (`return`)."""
    given, got = _sub(event, "tool_input"), _sub(event, "tool_response")
    _copy(fields, got, ("child", "agentId", str))
    if "child" not in fields:
        gaps.append("tool_response.agentId")
    # the response names a teammate; a returned agent's name is the dispatch's
    _copy(fields, {**given, **got}, ("name", "name", str))
    _copy(fields, got, ("model", "resolvedModel", str))
    mode = _LAUNCHED.get(str(got.get("status")))
    if mode is None:
        _copy(
            fields,
            got,
            ("ms", "totalDurationMs", int),
            ("tools", "totalToolUseCount", int),
            ("final_tokens", "totalTokens", int),
        )
        usage: Fields = {}
        _copy(usage, _sub(got, "usage"), *((k, k, int) for k in _USAGE))
        if usage:
            fields["usage"] = usage
        return "return", fields, gaps
    fields["mode"] = mode
    _copy(
        fields,
        {**given, **got},
        ("team", "team_name", str),
    )
    _copy(fields, got, ("child_type", "agent_type", str))
    return "launch", fields, gaps


def _post(event: Mapping[str, object]) -> Built:
    """PostToolUse: an Agent call's launch or return, else a `post`."""
    fields: Fields = {}
    gaps = _tool(event, fields)
    if event.get("tool_name") == "Agent":
        status = _sub(event, "tool_response").get("status")
        if isinstance(status, str) and (status == "completed" or status in _LAUNCHED):
            return _agent_post(event, fields, gaps)
        unknown = "" if status is None else f"={str(status)[:_GAP_VALUE]}"
        gaps.append(f"tool_response.status{unknown}")
    _copy(fields, event, ("tool", "tool_name", str), ("ms", "duration_ms", int))
    if event.get("tool_name") == "TaskStop":
        # the agent's name when the lead stopped it by name, else a task id: a stopped
        # agent fires no SubagentStop, so this is the only trace of its end
        _copy(fields, _sub(event, "tool_input"), ("target", "task_id", str))
    return "post", fields, gaps


def _failed(event: Mapping[str, object]) -> Built:
    """PostToolUseFailure: an Agent call that failed, never its error text."""
    fields: Fields = {}
    gaps = _tool(event, fields)
    _copy(fields, _sub(event, "tool_input"), ("name", "name", str))
    _copy(
        fields, event, ("interrupt", "is_interrupt", bool), ("ms", "duration_ms", int)
    )
    return "failed", fields, gaps


def _prompt(event: Mapping[str, object]) -> Built:
    """UserPromptSubmit: whether an agent's return or the user wrote it, never what."""
    return (
        "prompt",
        {"from": "return" if is_return(event.get("prompt")) else "user"},
        [],
    )


def _turn_end(event: Mapping[str, object]) -> Built:
    """Stop: the count of background tasks not known to have stopped."""
    tasks = as_list(event.get("background_tasks"))
    if tasks is None:
        return "turn-end", {}, []
    running = [
        t for t in tasks if (as_dict(t) or {}).get("status", "running") == "running"
    ]
    return "turn-end", {"bg_tasks": len(running)}, []


# hook: (kind, (key, field) copied as str, the fields whose absence is a gap)
_PLAIN: dict[str, tuple[str, tuple[tuple[str, str], ...], tuple[str, ...]]] = {
    "SubagentStart": ("start", (), ("agent_id", "agent_type")),
    "SubagentStop": ("stop", (), ("agent_id", "agent_type")),
    "TeammateIdle": (
        "idle",
        (("teammate", "teammate_name"), ("team", "team_name")),
        ("teammate_name",),
    ),
    "Notification": ("notify", (("type", "notification_type"),), ()),
    "PostCompact": ("compact", (("trigger", "trigger"),), ()),
    "SessionStart": ("session", (("source", "source"),), ()),
    "SessionEnd": ("session-end", (("reason", "reason"),), ()),
    "StopFailure": ("api-error", (), ()),
}
_BUILDERS: dict[str, Callable[[Mapping[str, object]], Built]] = {
    "PreToolUse": _pre,
    "PostToolUse": _post,
    "PostToolUseFailure": _failed,
    "UserPromptSubmit": _prompt,
    "Stop": _turn_end,
}


def _build(name: str, event: Mapping[str, object]) -> Built | None:
    """Return the kind, fields and gaps of an event of hook name; None: not recorded."""
    if name in _PLAIN:
        kind, keys, expected = _PLAIN[name]
        fields: Fields = {}
        _copy(fields, event, *((key, field, str) for key, field in keys))
        gaps = [f for f in expected if not _typed(event.get(f), str)]
        return kind, fields, gaps
    build = _BUILDERS.get(name)
    return None if build is None else build(event)


def _dump(obj: Mapping[str, object]) -> bytes:
    """Return obj as one ASCII line, so its length in bytes is its length in chars."""
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


def _fit(obj: Fields) -> bytes | None:
    """Return obj as a line within LINE_MAX, dropping the least needed fields first.

    The last resort keeps only the keys a reader joins on; None when even those are
    too long.
    """
    line = _dump(obj)
    for drop in _DROPS:
        if len(line) <= LINE_MAX:
            return line
        obj = {k: v for k, v in obj.items() if k not in drop} | {"trunc": True}
        line = _dump(obj)
    if len(line) > LINE_MAX:
        line = _dump({k: obj[k] for k in _JOIN} | {"trunc": True})
    return line if len(line) <= LINE_MAX else None


def _cut(kind: str, obj: Fields) -> bool:
    """Cut each field of obj with a length limit to it; return whether any was cut."""
    cut = False
    for key in list(obj):
        limit = _LIMITS.get((kind, key))
        value = obj[key]
        if limit is not None and isinstance(value, str) and len(value) > limit:
            obj[key] = value[:limit]
            cut = True
    return cut


def record(
    event: Mapping[str, object],
    entry: Mapping[str, object],
    t0: float,
    decision: tuple[str, str] | None,
) -> None:
    """Append the line of one hook event to its session's log.

    Args:
        event: The hook's payload.
        entry: The session's registry entry, the source of `run` and the paths.
        t0: When the hook started, epoch seconds.
        decision: The call's `(decision, reason)` when it was not allowed, else None.
    """
    session, name = event.get("session_id"), event.get("hook_event_name")
    if not (
        isinstance(session, str)
        and isinstance(name, str)
        and SESSION.fullmatch(session)
    ):
        return
    built = _build(name, event)
    if built is None:
        return
    kind, fields, gaps = built
    run = entry.get("run")
    common: Fields = {
        "v": SCHEMA,
        "ts": round(t0, 3),
        "session": session,
        "run": run if isinstance(run, str) else None,
    }
    _copy(
        common, entry, ("planning_dir", "planning_dir", str), ("marker", "marker", str)
    )
    common |= {"hook": name, "ev": kind}
    _copy(common, event, ("agent", "agent_id", str), ("atype", "agent_type", str))
    obj = common | fields
    if decision is not None and kind in ("dispatch", "pre"):
        obj["decision"] = decision[0]
        if holds := _HOLD.findall(decision[1]):
            obj["hold"] = f"F{holds[-1]}"
    if gaps:
        obj["gap"] = gaps
    if _cut(kind, obj):
        obj["trunc"] = True
    line = _fit(obj)
    if line is not None:
        agent = common.get("agent")
        _append(common, session, agent if isinstance(agent, str) else None, line)


def _locked(fd: int) -> bool:
    """Take fd's flock in at most LOCK_TRIES tries; whether it was taken."""
    if fcntl is None:
        return True
    for attempt in range(LOCK_TRIES):
        if attempt:
            time.sleep(LOCK_WAIT_S)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            continue
        return True
    return False


def _beat(session: str, agent: str | None) -> bool:
    """Whether a pre/post of agent past the cap is written; its stamp is renewed then.

    One per agent per HEARTBEAT_S, so a stuck agent still shows its last tool call.
    """
    who = agent or "lead"
    if not SESSION.fullmatch(who):
        return False
    stamp = EVENTS / f"{session}.{who}.hb"
    with contextlib.suppress(FileNotFoundError):
        if time.time() - stamp.stat().st_mtime < HEARTBEAT_S:
            return False
    stamp.touch(mode=0o600)  # an existing stamp's mtime is set to now
    return True


def _write(fd: int, line: bytes) -> None:
    """One write of line; a short one is ended, so the next line starts whole."""
    if os.write(fd, line) < len(line):
        _ = os.write(fd, b"\n")


def _append(
    common: Mapping[str, object], session: str, agent: str | None, line: bytes
) -> None:
    """Append line to session's log under its lock, as the cap rule allows.

    Below CAP_BYTES every line is written, and the write that reaches it adds one `cap`
    line; past it a pre/post is written only on the agent's heartbeat.
    """
    EVENTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(EVENTS / f"{session}.jsonl", _OPEN, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or not _locked(fd):
            return
        size = os.fstat(fd).st_size
        past = size >= CAP_BYTES and common["ev"] in ("pre", "post")
        if past and not _beat(session, agent):
            return
        _write(fd, line)
        if size < CAP_BYTES <= size + len(line):
            cap = _fit({**common, "ev": "cap", "bytes": os.fstat(fd).st_size})
            if cap is not None:
                _write(fd, cap)
    finally:
        os.close(fd)


def sweep() -> None:
    """Remove the logs and heartbeat stamps older than RETENTION_DAYS, once a day.

    `EVENTS/.swept` claims the day's sweep; nothing outside EVENTS, nothing below it
    and nothing but a regular `*.jsonl` or `*.hb` file is removed.
    """
    claim = EVENTS / ".swept"
    now = time.time()
    with contextlib.suppress(FileNotFoundError):
        if now - claim.stat().st_mtime < SWEEP_S:
            return
    claim.touch(mode=0o600)
    expired = now - RETENTION_DAYS * 86400
    for p in EVENTS.iterdir():
        if not p.name.endswith((".jsonl", ".hb")):
            continue
        with contextlib.suppress(FileNotFoundError):
            st = p.lstat()
            if stat.S_ISREG(st.st_mode) and st.st_mtime < expired:
                p.unlink()
