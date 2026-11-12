# SPDX-License-Identifier: MIT
"""Show every dsp route on this machine, live, in one browser page.

dsp_monitor.py serves a page and a JSON API on 127.0.0.1 and prints the page's URL. It
finds the routes the registry under ~/.claude/dsp-routes names, reads their planning
dirs and repositories, and reads the agent events the recording switch writes (see
INSTALL.md). It starts only by hand; Ctrl-C stops it.

Options:
  --port N  listen on the first free port of N to N+9 (default 47961). A port of the
            range that a dsp monitor holds already is the answer: its URL is
            printed and this launch exits. On WSL, a port where Windows' curl.exe
            reaches another process is passed over. 0 binds one ephemeral port,
            with no scan and no check.
  --open    also open the page in a browser tab, on every launch.

It writes nothing anywhere: no lock, PID, cache or log file. It listens on 127.0.0.1
only, and answers only a request whose Host is 127.0.0.1:<port> or localhost:<port>.
No authentication: every local process that can reach the loopback can read it.

Exit codes: 0 stopped by Ctrl-C or SIGTERM, or a dsp monitor already serves; 1 no
port of the range can be served; 2 a bad argument, or its page (dsp_monitor.html
beside it) is missing or malformed.
"""

import argparse
import base64
import concurrent.futures
import contextlib
import dataclasses
import datetime as dt
import errno
import hashlib
import http.client
import http.server
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, NamedTuple, TypeVar

from dsp_route import common

if TYPE_CHECKING:
    from typing_extensions import override

    from dsp_route.report import State
else:
    _F = TypeVar("_F", bound=Callable[..., object])

    def override(method: _F) -> _F:
        """Return method unchanged: `typing.override`, which Python 3.11 lacks."""
        return method


API_VERSION = 1
PORT = 47961
PORT_SPAN = 10
PING_TIMEOUT_S = 2
IDLE_S = 7200
STUCK_S = 720
NICE = 10
WORKERS = 2
SCAN_S = 2
FREE_TTL_S = 15
FREE_IDLE_S = 600
GIT_TTL_S = 120
GIT_FLOOR_S = 30
GIT_IDLE_S = 1800
DEADLINE_S = 20
DEADLINE_MAX_S = 120
# a line's identity key is kept this long after the session's newest line: a plugin
# loaded twice writes its duplicates within milliseconds
_DEDUPE_S = 600
PAGE = pathlib.Path(__file__).with_name("dsp_monitor.html")

RUN_STATES = ("live", "ended")
ROUTE_STATUS = ("active", "idle")
RECORDING = ("seen", "none", "reduced", "expired")
ATTENTION = (
    "asked",
    "input",
    "blind",
    "dir-missing",
    "stuck",
    "reduced",
    "git-slow",
    "unreadable",
    "flag",
)
GIT_STATES = ("pending", "fresh", "slow", "not_tracked")
BOARD_COLUMNS = ("queued", "running", "ready", "merged", "blocked", "failed")
ATTENTION_FLAGS = (
    "gate-red",
    "base-drift",
    "main-missing",
    "lane-moved-past-merge",
    "sha-unknown",
    "manifest-invalid",
)
WAIT_NOTIFY = ("permission_prompt", "elicitation_dialog", "idle_prompt")

# each report lane state: its board column and whether it is gating; a queued lane
# whose dependencies are not all merged shows as blocked instead
BOARD = {
    "queued": ("queued", False),
    "running": ("running", False),
    "gating": ("running", True),
    "ready": ("ready", False),
    "red": ("failed", False),
    "merged": ("merged", False),
}


def check_owners() -> None:
    """Stop the launch when a constant here disagrees with the module that owns it.

    Raises:
        RuntimeError: Named after the constant that disagrees.
    """
    # the hook path imports these lazily too; a module-level import would slow it
    from dsp_route import record, report

    if set(BOARD) != set(report.LANE_STATES):
        msg = f"BOARD: maps {sorted(BOARD)}, report.LANE_STATES is {report.LANE_STATES}"
        raise RuntimeError(msg)
    if STUCK_S <= record.HEARTBEAT_S:
        beat = record.HEARTBEAT_S
        msg = f"STUCK_S: {STUCK_S} s is not above record.HEARTBEAT_S ({beat} s)"
        raise RuntimeError(msg)
    unknown = sorted(set(ATTENTION_FLAGS) - set(report.FLAG_KINDS))
    if unknown:
        msg = f"ATTENTION_FLAGS: {unknown} not in report.FLAG_KINDS"
        raise RuntimeError(msg)


class Page(NamedTuple):
    """The page as served: its bytes, its CSP and the id the API reports."""

    body: bytes
    csp: str
    digest: str


def read_page(path: pathlib.Path) -> Page:
    """Read the page and build the CSP from its one script and one style.

    Args:
        path: The page file.

    Returns:
        The page, its Content-Security-Policy and the first 12 hex of its sha256.

    Raises:
        ValueError: Why the page cannot be served.
    """
    try:
        body = path.read_bytes()
    except OSError as e:
        msg = e.strerror or type(e).__name__
        raise ValueError(msg) from e
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        msg = "not UTF-8"
        raise ValueError(msg) from e
    # a browser hashes the text after the HTML parser turned CR LF and CR into LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    hashes: dict[str, str] = {}
    for tag in ("script", "style"):
        n = len(re.findall(rf"<{tag}\b", text, re.IGNORECASE))
        m = re.search(
            rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", text, re.IGNORECASE | re.DOTALL
        )
        if n != 1 or m is None:
            msg = f"wants exactly one closed <{tag}> element, has {n} <{tag} tags"
            raise ValueError(msg)
        digest = hashlib.sha256(m.group(1).encode()).digest()
        hashes[tag] = base64.b64encode(digest).decode()
    csp = (
        f"default-src 'none'; script-src 'sha256-{hashes['script']}'; "
        f"style-src 'sha256-{hashes['style']}'; connect-src 'self'; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return Page(body, csp, hashlib.sha256(body).hexdigest()[:12])


def now_iso() -> str:
    """Return the current UTC time as ISO 8601 with `Z`."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def as_json(obj: object) -> bytes:
    """Return obj as compact UTF-8 JSON, HOME written as `~` in every string.

    A HOME of one character (`/`) is left as it is.
    """
    top = str(pathlib.Path.home())
    if len(top) > 1:
        # HOME as a whole path component, wherever a string holds it
        obj = _tilde(obj, re.compile(rf"(?<![\w.-]){re.escape(top)}(?![\w.-])"))
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


def _tilde(value: object, top: re.Pattern[str]) -> object:
    """Return value with each match of top in its strings and keys replaced by `~`."""
    if isinstance(value, str):
        return top.sub("~", value)
    if (d := common.as_dict(value)) is not None:
        return {top.sub("~", k): _tilde(v, top) for k, v in d.items()}
    if (items := common.as_list(value)) is not None:
        return [_tilde(v, top) for v in items]
    return value


def iso(t: float | None) -> str | None:
    """Return epoch seconds as UTC ISO 8601 with `Z`; None stays None."""
    if t is None:
        return None
    return dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- what the scan reads: markers, the registry and the event logs


class MarkerRead(NamedTuple):
    """A marker as read: `ok` with its fields, `absent` after a retry, or `torn`."""

    status: Literal["ok", "absent", "torn"]
    data: dict[str, object]


def _read_bytes(path: pathlib.Path) -> bytes:
    """Return path's bytes: the marker reader's one I/O call."""
    return path.read_bytes()


def read_marker(path: pathlib.Path) -> MarkerRead:
    """Read a route marker the way its writers allow.

    A read that fails is tried once more after ABSENT_RETRY_S: on drvfs a reader saw an
    os.replace'd file as briefly missing. A marker that does not parse is torn at once:
    an older skill rewrites it in place, and a retry would not tell more.

    Args:
        path: The marker file.

    Returns:
        ok and its fields; absent when both reads failed; torn when it does not parse.
    """
    try:
        body = _read_bytes(path)
    except OSError:
        time.sleep(common.ABSENT_RETRY_S)
        try:
            body = _read_bytes(path)
        except OSError:
            return MarkerRead("absent", {})
    try:
        data = common.as_dict(common.parse_json(body))
    except ValueError:
        data = None
    return MarkerRead("torn", {}) if data is None else MarkerRead("ok", data)


class OpenCall(NamedTuple):
    """A tool call with a `pre` and no `post` yet: its tool, its ts and any hold.

    group: the lines its `pre` joined, which tie the call to a run.
    """

    tool: str | None
    since: float
    decision: str | None
    group: "Group | None" = None

    @property
    def waits_on_user(self) -> bool:
        """An AskUserQuestion or a held call waits on the user: it is not stuck."""
        return self.tool == "AskUserQuestion" or self.decision is not None


@dataclasses.dataclass
class Calls:
    """The open tool calls of one subject, an agent or the lead (§3.6.4)."""

    open: dict[str, OpenCall] = dataclasses.field(default_factory=dict)
    last_post: float = 0.0

    def pre(self, line: dict[str, object], t: float, group: "Group | None") -> None:
        """Open a call; one older than the subject's newest `post` has ended.

        The model issues a new call only once every call of its previous message
        returned, and a failed call fires no `post`.
        """
        for k, call in list(self.open.items()):
            if call.since < self.last_post:
                del self.open[k]
        tuid, tool, decision = line.get("tuid"), line.get("tool"), line.get("decision")
        self.open[tuid if isinstance(tuid, str) else f"@{t}"] = OpenCall(
            tool if isinstance(tool, str) else None,
            t,
            decision if isinstance(decision, str) else None,
            group,
        )

    def stuck(self, now: float) -> OpenCall | None:
        """The oldest call open past STUCK_S that does not wait on the user."""
        calls = [c for c in self.open.values() if not c.waits_on_user]
        call = min(calls, key=lambda c: c.since, default=None)
        return call if call is not None and now - call.since > STUCK_S else None

    def post(self, line: dict[str, object], t: float) -> None:
        """Close the call of the line's `tuid`."""
        tuid = line.get("tuid")
        if isinstance(tuid, str):
            _ = self.open.pop(tuid, None)
        self.last_post = max(self.last_post, t)

    def oldest(self) -> OpenCall | None:
        """The call open longest, None when none is open."""
        return min(self.open.values(), key=lambda c: c.since, default=None)


# the states no later line of that agent leaves, and those `agents_running` counts
_OVER = ("returned", "stopped", "failed", "interrupted", "ended-with-session")
_RUNNING = ("dispatched", "launched", "active")


@dataclasses.dataclass(eq=False)
class Agent:
    """One agent of a session as its lines fold (§3.6.4); never a line's free text.

    final: no later event changes its state (a denied dispatch, a `return`, a
    `failed`, a TaskStop). group: the lines of the run it was first seen in.
    """

    session: str
    group: "Group"
    tuid: str | None = None
    child: str | None = None
    name: str = ""
    team: str | None = None
    state: str = "active"
    final: bool = False
    mode: str | None = None
    model: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    duration_s: float | None = None
    tools: int | None = None
    final_tokens: int | None = None
    last_tool: str | None = None
    last_tool_at: float | None = None
    compactions: int = 0
    calls: Calls = dataclasses.field(default_factory=Calls)

    @property
    def over(self) -> bool:
        """Whether the agent has ended."""
        return self.final or self.state in _OVER

    def end(self, state: str, t: float, ms: object = None) -> None:
        """End it in state at t; its duration from ms, else from its start."""
        self.state, self.ended_at = state, t
        if isinstance(ms, int) and not isinstance(ms, bool):
            self.duration_s = ms / 1000
        elif self.started_at is not None:
            self.duration_s = round(t - self.started_at, 3)
        self.calls.open.clear()


@dataclasses.dataclass
class Group:
    """The retained event lines of one session for one (run, planning dir, marker).

    gap_at: the ts of its first line with `gap`, gap: that line's gap fields;
    agents: those first seen here.
    """

    first_ts: float
    last_ts: float
    lines: int = 0
    gap_at: float | None = None
    gap: list[str] = dataclasses.field(default_factory=list)
    agents: list[Agent] = dataclasses.field(default_factory=list)


class Lead(NamedTuple):
    """A session's newest lead event (§4.5 "Waiting on you"): what it says, and when.

    group: the lines it joined, which tie it to a run.
    """

    ev: str
    t: float
    group: Group
    tool: str | None
    decision: str | None
    type: str | None
    idle_bg: bool


GroupKey = tuple[str | None, str | None, str | None]


class Sighting(NamedTuple):
    """One mention of a route: a registry entry, a `previous` item or event lines.

    at: an entry's `activated` (for a `previous` item, its entry's); the newest line's
    ts for events. args: an entry's marker arguments.
    """

    planning_dir: str | None
    marker: str | None
    run: str | None
    session: str
    kind: Literal["entry", "previous", "events"]
    at: float
    args: tuple[str, ...] | None = None
    group: Group | None = None


class MarkerFile(NamedTuple):
    """A route's current marker: its path, what reading it gave, and its mtime."""

    path: str
    read: MarkerRead
    mtime: float | None


@dataclasses.dataclass
class SessionLog:
    """What the tail of one session's event log has folded so far.

    skipped, versions: lines skipped and the unknown `v` among them; seen: each
    folded line's identity key and ts, within _DEDUPE_S of the newest; unjoined:
    agent lines that name no agent; calls: the lead's open calls; lead: its newest
    lead event; cap_at: the ts of its first `cap` line.
    """

    ident: tuple[int, int]
    session: str
    offset: int = 0
    groups: dict[GroupKey, Group] = dataclasses.field(default_factory=dict)
    agents: list[Agent] = dataclasses.field(default_factory=list)
    calls: Calls = dataclasses.field(default_factory=Calls)
    skipped: int = 0
    versions: set[int] = dataclasses.field(default_factory=set)
    seen: dict[tuple[object, ...], float] = dataclasses.field(default_factory=dict)
    unjoined: int = 0
    lead: Lead | None = None
    cap_at: float | None = None
    ended: bool = False

    @property
    def cap(self) -> bool:
        """Whether the log passed its size cap: activity since is sampled."""
        return self.cap_at is not None


@dataclasses.dataclass
class Scan:
    """One scan's reading of the registry, the event logs and the hook files.

    found: (marker, planning dir) as a sighting names them -> the effective marker and
    whether it exists. current: planning dir -> its current marker (R64). mtimes: each
    hook `.last` file that exists. dirs: planning dir -> whether it exists.
    """

    sightings: list[Sighting]
    errors: list[dict[str, str]]
    found: dict[tuple[str, str], tuple[str, bool]]
    current: dict[str, MarkerFile]
    mtimes: dict[str, float]
    dirs: dict[str, bool]
    logs: dict[str, SessionLog]


def _mtime(path: str) -> float | None:
    """Return path's mtime, None when it cannot be stat'ed."""
    try:
        return pathlib.Path(path).stat().st_mtime
    except OSError:
        return None


def _effective(marker: str, planning_dir: str) -> tuple[str, bool]:
    """Return a sighting's effective marker and whether it exists.

    A missing legacy per-repository marker was moved to its route's own file.
    """
    path = pathlib.Path(marker)
    if path.exists():
        return marker, True
    if path.name == common.MARKER:
        moved = path.with_name(f"dsp-route-{common.route_slug(planning_dir)}.json")
        return str(moved), moved.exists()
    return marker, False


def _entry(name: str, data: dict[str, object]) -> list[Sighting] | str:
    """Return a registry entry's sightings, or why it is not one."""
    planning, marker = data.get("planning_dir"), data.get("marker")
    if not isinstance(planning, str) or not isinstance(marker, str):
        return "no planning_dir or marker string"
    at = data.get("activated")
    at = float(at) if isinstance(at, int | float) else 0.0
    run = data.get("run")
    args = common.as_list(data.get("args"))
    stem = name.removesuffix(".json")
    return [
        Sighting(
            planning,
            marker,
            run if isinstance(run, str) else None,
            stem,
            "entry",
            at,
            None if args is None else tuple(map(str, args)),
        )
    ]


def _previous(name: str, data: dict[str, object], at: float) -> list[Sighting | str]:
    """Return a registry entry's `previous` items as sightings, or each one's fault."""
    out: list[Sighting | str] = []
    for i, item in enumerate(common.as_list(data.get("previous")) or []):
        d = common.as_dict(item) or {}
        planning, marker, run = d.get("planning_dir"), d.get("marker"), d.get("run")
        if isinstance(planning, str) and isinstance(marker, str):
            run = run if isinstance(run, str) else None
            stem = name.removesuffix(".json")
            out.append(Sighting(planning, marker, run, stem, "previous", at))
        else:
            out.append(f"previous item {i} has no planning_dir or marker string")
    return out


def current_marker(sightings: list[Sighting]) -> Sighting:
    """Return the sighting whose marker is the route's current one (R64).

    The newest entry that carries a run; with none, the newest entry; with no entry,
    the newest sighting.
    """
    entries = [s for s in sightings if s.kind == "entry"]
    pool = [s for s in entries if s.run is not None] or entries or sightings
    return max(pool, key=lambda s: s.at)


class Scanner:
    """Reads the registry and tails the event logs, keeping only folded state."""

    def __init__(self, registry: pathlib.Path, events: pathlib.Path) -> None:
        """Scan registry's entries and the logs under events.

        Args:
            registry: The session registry directory.
            events: The event-log directory.
        """
        self.registry: pathlib.Path = registry
        self.events: pathlib.Path = events
        self.logs: dict[str, SessionLog] = {}

    def _registry(self) -> tuple[list[Sighting], list[dict[str, str]]]:
        """Return the sightings of every registry entry, and the files that failed."""
        sightings: list[Sighting] = []
        errors: list[dict[str, str]] = []
        for f in sorted(self.registry.glob("*.json")):
            if f.name.endswith(".waits.json"):
                continue
            try:
                data = common.as_dict(common.parse_json(f.read_bytes()))
            except (OSError, ValueError) as e:
                errors.append({"source": f.name, "reason": type(e).__name__})
                continue
            got = "not a JSON object" if data is None else _entry(f.name, data)
            if isinstance(got, str):
                errors.append({"source": f.name, "reason": got})
                continue
            sightings.extend(got)
            for p in _previous(f.name, data or {}, got[0].at):
                if isinstance(p, str):
                    errors.append({"source": f.name, "reason": p})
                else:
                    sightings.append(p)
        return sightings, errors

    def _tail(self) -> None:
        """Fold each log's new complete lines; a replaced or shrunk log from 0."""
        seen: set[str] = set()
        for path in sorted(self.events.glob("*.jsonl")):
            try:
                st = path.stat()
            except OSError:
                continue
            seen.add(path.stem)
            ident = (st.st_dev, st.st_ino)
            log = self.logs.get(path.stem)
            if log is None or log.ident != ident or st.st_size < log.offset:
                log = self.logs[path.stem] = SessionLog(ident, path.stem)
            if st.st_size > log.offset:
                self._read(path, log)
        for gone in set(self.logs) - seen:
            del self.logs[gone]

    def _read(self, path: pathlib.Path, log: SessionLog) -> None:
        """Fold the complete lines of path past log's offset; a partial one waits."""
        try:
            with path.open("rb") as f:
                _ = f.seek(log.offset)
                data = f.read()
        except OSError:
            return
        from dsp_route import record

        end = data.rfind(b"\n") + 1
        log.offset += end
        lines: list[tuple[float, dict[str, object]]] = []
        for raw in data[:end].splitlines():
            try:
                line = common.as_dict(common.parse_json(raw))
            except ValueError:
                line = None
            v = None if line is None else line.get("v")
            t = None if line is None else line.get("ts")
            if line is None or type(v) is not int or not isinstance(t, int | float):
                log.skipped += 1
            elif v > record.SCHEMA:
                log.skipped += 1
                log.versions.add(v)
            elif line.get("ev") in record.KINDS:
                lines.append((float(t), line))
        # ts is taken at hook start, so lines land out of order
        lines.sort(key=lambda x: x[0])
        for t, line in lines:
            fold_line(log, line, t)
        newest = max(log.seen.values(), default=0.0)
        log.seen = {k: t for k, t in log.seen.items() if t >= newest - _DEDUPE_S}

    def scan(self, now: float) -> Scan:
        """Read the registry, tail the logs and stat the markers and hook files.

        Args:
            now: The scan's time.

        Returns:
            What this scan read; the logs' folded state carries over to the next.
        """
        del now
        sightings, errors = self._registry()
        self._tail()
        for session, log in self.logs.items():
            for (run, planning, marker), g in log.groups.items():
                sightings.append(
                    Sighting(
                        planning, marker, run, session, "events", g.last_ts, None, g
                    )
                )
        found: dict[tuple[str, str], tuple[str, bool]] = {}
        routes: dict[str, list[Sighting]] = {}
        mtimes: dict[str, float] = {}
        for s in sightings:
            if s.planning_dir is None or s.marker is None:
                continue
            routes.setdefault(s.planning_dir, []).append(s)
            key = (s.marker, s.planning_dir)
            if key not in found:
                found[key] = _effective(*key)
            stem = str(pathlib.Path(found[key][0]).with_suffix(""))
            for hook_file in (f"{stem}.{s.session}.last", f"{stem}.last"):
                t = _mtime(hook_file)
                if t is not None:
                    mtimes[hook_file] = t
        current: dict[str, MarkerFile] = {}
        for planning, mine in routes.items():
            s = current_marker(mine)
            path = found[(str(s.marker), planning)][0]
            read = read_marker(pathlib.Path(path))
            current[planning] = MarkerFile(path, read, _mtime(path))
        dirs = {p: pathlib.Path(p).is_dir() for p in routes}
        return Scan(sightings, errors, found, current, mtimes, dirs, self.logs)


def fold_line(log: SessionLog, line: dict[str, object], t: float) -> None:
    """Fold one event line into its session's state; a duplicate changes nothing.

    Args:
        log: The session's folded state.
        line: The line, parsed, with a known `v` and `ev`.
        t: Its ts.
    """
    hook, tuid = line.get("hook"), line.get("tuid")
    ident = (hook, tuid) if isinstance(tuid, str) else (hook, line.get("agent"), t)
    if ident in log.seen:
        return
    log.seen[ident] = t
    run, planning, marker = (line.get(k) for k in ("run", "planning_dir", "marker"))
    # a line cut to fit keeps neither; without both it joins by run alone
    named = isinstance(planning, str) and isinstance(marker, str)
    key: GroupKey = (
        run if isinstance(run, str) else None,
        str(planning) if named else None,
        str(marker) if named else None,
    )
    g = log.groups.setdefault(key, Group(t, t))
    g.first_ts, g.last_ts = min(g.first_ts, t), max(g.last_ts, t)
    g.lines += 1
    if "gap" in line and (g.gap_at is None or t < g.gap_at):
        g.gap_at = t
        g.gap = [str(f) for f in common.as_list(line.get("gap")) or []]
    ev, kind = str(line.get("ev")), line.get("type")
    # a lead line; a notify only of a type that waits on the user
    lead = line.get("agent") is None and (ev != "notify" or kind in WAIT_NOTIFY)
    if lead and (log.lead is None or t >= log.lead.t):
        tool, decision, bg = (line.get(k) for k in ("tool", "decision", "bg_tasks"))
        log.lead = Lead(
            ev,
            t,
            g,
            tool if isinstance(tool, str) else None,
            decision if isinstance(decision, str) else None,
            kind if isinstance(kind, str) else None,
            type(bg) is int and bg == 0,
        )
    fold = _FOLD.get(ev)
    if fold is not None:
        fold(Ev(log, g, line, t))


class Ev(NamedTuple):
    """One line being folded: its session, its group, the line and its ts."""

    log: SessionLog
    group: Group
    line: dict[str, object]
    t: float

    def text(self, key: str) -> str | None:
        """The line's string at key, None when it has none."""
        value = self.line.get(key)
        return value if isinstance(value, str) else None


def _new(e: Ev, **fields: str | float | None) -> Agent:
    """A new agent record of e's session and group, first seen at e."""
    a = Agent(e.log.session, e.group, started_at=e.t)
    for k, v in fields.items():
        setattr(a, k, v)
    e.log.agents.append(a)
    e.group.agents.append(a)
    return a


def _join(e: Ev, *, create: bool) -> Agent | None:
    """The record of e's `agent`: by id, else the oldest unjoined dispatch of its name.

    With neither, a new record when create, else the line counts as unjoined: a
    SubagentStop also fires for helper agents that never started.
    """
    x = e.text("agent") or ""
    a = next((a for a in e.log.agents if a.child == x), None)
    if a is None:
        name = common.id_name(x)
        a = next(
            (
                d
                for d in e.log.agents
                if d.child is None and d.tuid and not d.over and d.name == name
            ),
            None,
        )
        if a is not None:
            a.child = x
    if a is None and create:
        a = _new(e, child=x, name=common.id_name(x))
    if a is None:
        e.log.unjoined += 1
    return a


def _merge(log: SessionLog, into: Agent, src: Agent) -> None:
    """Fold src, opened by its own lines before its launch was seen, into into."""
    starts = [t for t in (into.started_at, src.started_at) if t is not None]
    into.started_at = min(starts, default=None)
    into.state, into.final, into.calls = src.state, src.final, src.calls
    into.ended_at, into.duration_s = src.ended_at, src.duration_s
    into.last_tool, into.last_tool_at = src.last_tool, src.last_tool_at
    into.compactions += src.compactions
    log.agents.remove(src)
    src.group.agents.remove(src)


def _called(e: Ev) -> Agent:
    """The record of a `launch`, `return` or `failed`: by its `tuid`, with its child.

    A record its child opened before (SubagentStart can precede the launch) is merged
    into the dispatch's.
    """
    tuid, child = e.text("tuid"), e.text("child")
    a = next((d for d in e.log.agents if tuid and d.tuid == tuid), None)
    if child is not None:
        c = next((d for d in e.log.agents if d.child == child), None)
        if a is None:
            a = c
        elif c is not None and c is not a:
            _merge(e.log, a, c)
    if a is None:
        a = _new(e, tuid=tuid)
    a.tuid, a.child = a.tuid or tuid, child or a.child
    a.name = e.text("name") or a.name or (common.id_name(a.child) if a.child else "")
    a.model = e.text("model") or a.model
    return a


def _dispatch(e: Ev) -> None:
    decision = e.text("decision")
    a = _new(
        e,
        tuid=e.text("tuid"),
        name=e.text("name") or "",
        state="dispatched" if decision is None else "held",
    )
    # a denied dispatch is held for good; an asked one waits for its launch
    a.final = decision == "deny"


def _launch(e: Ev) -> None:
    a = _called(e)
    a.mode, a.team = e.text("mode") or a.mode, e.text("team") or a.team
    # a start seen first made it active; a launch never lowers that
    if not a.final and a.state in {"dispatched", "held", "interrupted"}:
        a.state = "launched"


def _return(e: Ev) -> None:
    a = _called(e)
    a.mode = a.mode or "foreground"
    tools, tokens = e.line.get("tools"), e.line.get("final_tokens")
    a.tools = tools if type(tools) is int else None
    a.final_tokens = tokens if type(tokens) is int else None
    a.end("returned", e.t, e.line.get("ms"))
    a.final = True


def _failed(e: Ev) -> None:
    a = _called(e)
    a.end("failed", e.t, e.line.get("ms"))
    a.final = True


def _active(e: Ev) -> Agent | None:
    """The record of e's agent, made active unless it ended for good."""
    if e.text("agent") is None:
        return None
    a = _join(e, create=True)
    if a is not None and not a.final:
        if a.over:
            a.ended_at = a.duration_s = None
        a.state = "active"
    return a


def _start(e: Ev) -> None:
    _ = _active(e)


def _pre(e: Ev) -> None:
    a = _active(e)
    calls = e.log.calls if a is None else a.calls
    calls.pre(e.line, e.t, e.group)
    if a is not None:
        a.last_tool, a.last_tool_at = e.text("tool") or a.last_tool, e.t


def _post(e: Ev) -> None:
    a = _active(e)
    calls = e.log.calls if a is None else a.calls
    calls.post(e.line, e.t)
    if a is not None:
        a.last_tool, a.last_tool_at = e.text("tool") or a.last_tool, e.t
    elif e.text("tool") == "TaskStop" and (target := e.text("target")) is not None:
        # the lead stopped an agent by name; by a task id it joins none
        named = [d for d in e.log.agents if d.name == target and not d.over]
        if named:
            named[-1].end("stopped", e.t)
            named[-1].final = True
        else:
            e.log.unjoined += 1


def _stop(e: Ev) -> None:
    a = None if e.text("agent") is None else _join(e, create=False)
    if a is not None and not a.final:
        a.end("stopped" if a.mode == "teammate" else "returned", e.t)


def _idle(e: Ev) -> None:
    if e.text("agent") is not None:
        a = _join(e, create=False)
    else:
        mate, team = e.text("teammate"), e.text("team")
        mates = [d for d in e.log.agents if d.name == mate and d.team == team]
        a = mates[-1] if mates else None
        if a is None:
            e.log.unjoined += 1
    if a is not None and not a.final:
        a.state = "idle"
        a.calls.open.clear()


def _api_error(e: Ev) -> None:
    a = None if e.text("agent") is None else _join(e, create=False)
    if a is not None and not a.final:
        a.state = "failed"


def _compact(e: Ev) -> None:
    a = None if e.text("agent") is None else _join(e, create=False)
    if a is not None:
        a.compactions += 1


def _interrupted(e: Ev) -> None:
    """A lead turn-end or user prompt: a dispatch with no launch never ran."""
    for a in e.log.agents:
        if not a.final and a.state in {"dispatched", "held"}:
            a.state = "interrupted"


def _turn_end(e: Ev) -> None:
    if e.text("agent") is None:
        e.log.calls.open.clear()
        _interrupted(e)


def _prompt(e: Ev) -> None:
    if e.text("agent") is None and e.text("from") == "user":
        _interrupted(e)


def _session_start(e: Ev) -> None:
    if e.text("source") == "resume":
        for a in e.log.agents:
            if not a.over:
                a.state = "lost"


def _session_end(e: Ev) -> None:
    e.log.ended = True
    e.log.calls.open.clear()
    for a in e.log.agents:
        if not a.over:
            a.end("ended-with-session", e.t)


def _cap(e: Ev) -> None:
    if e.log.cap_at is None or e.t < e.log.cap_at:
        e.log.cap_at = e.t


# each event kind's fold (§3.6.4); `prompt`'s and `notify`'s other uses are §4.5's
_FOLD: dict[str, Callable[[Ev], None]] = {
    "dispatch": _dispatch,
    "launch": _launch,
    "return": _return,
    "failed": _failed,
    "start": _start,
    "stop": _stop,
    "idle": _idle,
    "pre": _pre,
    "post": _post,
    "prompt": _prompt,
    "turn-end": _turn_end,
    "api-error": _api_error,
    "compact": _compact,
    "session": _session_start,
    "session-end": _session_end,
    "cap": _cap,
}


# --- the model: routes and runs, derived from one scan and the previous model


class Claim(NamedTuple):
    """What a route's current marker says, when it counts: its run and upgrade."""

    run: str | None
    upgraded: bool


@dataclasses.dataclass
class Run:
    """One run of a route, from the sightings that joined it."""

    key: str
    run: str | None
    live: bool = False
    sightings: list[Sighting] = dataclasses.field(default_factory=list)
    first_seen_at: float | None = None
    last_activity_at: float = 0.0
    recording: str = "none"
    logs: dict[str, SessionLog] = dataclasses.field(default_factory=dict)

    @property
    def agents(self) -> list[Agent]:
        """The agents first seen in the run's lines, oldest first."""
        groups = [s.group for s in self.sightings if s.group is not None]
        found = [a for g in groups for a in g.agents]
        return sorted(found, key=lambda a: a.started_at or 0.0)

    @property
    def sessions(self) -> list[str]:
        """The run's sessions, sorted."""
        return sorted({s.session for s in self.sightings})

    @property
    def args(self) -> tuple[str, ...] | None:
        """The marker arguments of the run's newest entry that has some."""
        entries = [s for s in self.sightings if s.args is not None]
        return max(entries, key=lambda s: s.at).args if entries else None


@dataclasses.dataclass
class Route:
    """A route: its planning dir, current marker and runs.

    claim: what its current marker says, None when it does not count; torn: the
    marker did not parse this scan; runs: listed runs, newest activity first; now:
    the scan's time; errors: the registry faults of its sessions' entries.
    """

    key: str
    planning_dir: str
    marker: str
    claim: Claim | None
    torn: bool
    runs: list[Run]
    now: float
    repo: str | None = None
    dir_missing: bool = False
    status: Literal["active", "idle"] | None = None
    errors: list[dict[str, str]] = dataclasses.field(default_factory=list)
    args: common.RouteArgs | None = None
    marker_data: dict[str, object] = dataclasses.field(default_factory=dict)

    @property
    def reported(self) -> Run | None:
        """The run a report is kept for: the live one, else the newest ended one."""
        return self.live or (self.runs[0] if self.runs else None)

    @property
    def live(self) -> Run | None:
        """The live run, if the route has one."""
        return next((r for r in self.runs if r.live), None)

    @property
    def name(self) -> str:
        """`<repo dir name> · <planning dir name>`, the repo's for a `.git` marker."""
        marker = pathlib.Path(self.marker)
        plan = pathlib.PurePath(self.planning_dir).name
        if marker.parent.name == ".git":
            return f"{marker.parent.parent.name} · {plan}"
        return plan


# a marker's `rung` as the route's arguments type it
_RUNGS: dict[object, Literal["S", "M", "L"]] = {"S": "S", "M": "M", "L": "L"}


def _marker_args(data: dict[str, object]) -> common.RouteArgs | None:
    """A marker's route arguments, its `rung` among them; None when it has none."""
    args = common.checked(common.route_args, data)
    if args is not None:
        args.rung = args.rung or _RUNGS.get(data.get("rung"))
    return args


@dataclasses.dataclass
class Model:
    """Every listed route, the registry files that failed, and unjoined event lines."""

    routes: dict[str, Route]
    errors: list[dict[str, str]]
    events_unjoined: int = 0


def _claim(
    mf: MarkerFile, planning: str, prev: Route | None, mine: list[Sighting]
) -> tuple[Claim | None, bool]:
    """Return what the route's current marker says and whether it was torn.

    A torn marker keeps the previous scan's claim; with none, the run of the route's
    newest registry sighting is taken as live.
    """
    if mf.read.status == "ok":
        data = mf.read.data
        if data.get("planning_dir") != planning:
            return None, False
        run = data.get("run")
        run = run if isinstance(run, str) else None
        return Claim(run, data.get("run_upgraded") is True), False
    if mf.read.status == "absent":
        return None, False
    if prev is not None:
        return prev.claim, True
    registry = [s for s in mine if s.kind != "events"] or mine
    return Claim(max(registry, key=lambda s: s.at).run, upgraded=False), True


def _activity(run: Run, scan: Scan, mf: MarkerFile) -> float:
    """Return a run's newest activity: lines, hook files, the marker or its entries."""
    times = [s.at for s in run.sightings if s.kind == "events"]
    for s in run.sightings:
        if s.marker is None or s.planning_dir is None:
            continue
        stem = str(
            pathlib.Path(scan.found[(s.marker, s.planning_dir)][0]).with_suffix("")
        )
        times += [
            scan.mtimes.get(f"{stem}.{s.session}.last", 0.0),
            scan.mtimes.get(f"{stem}.last", 0.0),
        ]
    if run.live and mf.mtime is not None:
        times.append(mf.mtime)
    if not run.live:
        times += [s.at for s in run.sightings if s.kind != "events"]
    return max(times, default=0.0)


def _recording(run: Run, scan: Scan, now: float) -> None:
    """Set the run's session logs and its recording state (§4.5); never the switch."""
    from dsp_route import record

    run.logs = {s: scan.logs[s] for s in run.sessions if s in scan.logs}
    retention = record.RETENTION_DAYS * 86400
    if any(log.cap for log in run.logs.values()):
        run.recording = "reduced"
    elif any(s.group is not None for s in run.sightings):
        run.recording = "seen"
    elif not run.live and now - run.last_activity_at > retention:
        run.recording = "expired"
    else:
        run.recording = "none"


def _route(
    planning: str, mine: list[Sighting], scan: Scan, prev: Route | None, now: float
) -> Route | None:
    """Return the route of one planning dir, None when none of its runs is listed."""
    key = common.route_slug(planning)
    mf = scan.current[planning]
    claim, torn = _claim(mf, planning, prev, mine)
    runs: dict[str | None, Run] = {}
    for s in mine:
        run = s.run
        if run is None and claim is not None and claim.run and claim.upgraded:
            named = s.marker is not None and s.planning_dir is not None
            if named and scan.found[(str(s.marker), planning)][0] == mf.path:
                run = claim.run
        if run not in runs:
            runs[run] = Run(f"{key}-{run or 'pre'}", run)
        runs[run].sightings.append(s)
    if claim is not None and claim.run in runs:
        runs[claim.run].live = True
    listed: list[Run] = []
    for r in runs.values():
        markers = {
            scan.found[(str(s.marker), planning)] for s in r.sightings if s.marker
        }
        if not (r.live or scan.dirs[planning] or any(e for _, e in markers)):
            continue
        events = [s.group.first_ts for s in r.sightings if s.group is not None]
        entries = [s.at for s in r.sightings if s.kind == "entry"]
        r.first_seen_at = min(events or entries, default=None)
        r.last_activity_at = _activity(r, scan, mf)
        _recording(r, scan, now)
        listed.append(r)
    if not listed:
        return None
    # at equal activity, a run with a registry entry of its own is the newer: a run
    # seen only in another entry's `previous` takes that entry's time
    listed.sort(
        key=lambda r: (r.last_activity_at, any(s.kind == "entry" for s in r.sightings)),
        reverse=True,
    )
    out = Route(key, planning, mf.path, claim, torn, listed, now)
    sessions = {s.session for s in mine}
    out.errors = [
        e for e in scan.errors if e["source"].removesuffix(".json") in sessions
    ]
    if out.live is not None:
        out.dir_missing = not scan.dirs[planning]
        out.marker_data = mf.read.data
        args = out.args = _marker_args(mf.read.data)
        out.repo = args.repo if args is not None and claim is not None else None
        quiet = now - out.live.last_activity_at
        out.status = "active" if quiet < IDLE_S else "idle"
    return out


def discover(scan: Scan, prev: Model | None, now: float) -> Model:
    """Derive the routes and runs of one scan.

    Args:
        scan: What this scan read.
        prev: The previous scan's model, whose claim a torn marker keeps.
        now: The scan's time.

    Returns:
        Every listed route by key, the registry errors, and the count of event lines
        that join no route.
    """
    routes: dict[str, list[Sighting]] = {}
    by_run: dict[str, str] = {}
    for s in scan.sightings:
        if s.planning_dir is not None:
            routes.setdefault(s.planning_dir, []).append(s)
            if s.run is not None:
                by_run[s.run] = s.planning_dir
    # agent lines that join no agent, then lines that join no route
    model = Model({}, scan.errors, sum(log.unjoined for log in scan.logs.values()))
    for s in scan.sightings:
        if s.planning_dir is not None:
            continue
        planning = by_run.get(str(s.run))
        if planning is None:
            model.events_unjoined += s.group.lines if s.group else 1
        else:
            routes[planning].append(s._replace(planning_dir=planning))
    for planning, mine in routes.items():
        key = common.route_slug(planning)
        old = prev.routes.get(key) if prev is not None else None
        route = _route(planning, mine, scan, old, now)
        if route is not None:
            model.routes[key] = route
    return model


# --- the API: what a model serialises to

# the item texts Python composes (each the user's to reword)
COPY = {
    "waiting": "{route} · {kind} · since {at}",
    "reduced": (
        "Recording reduced: this session's log passed its size cap, so activity is "
        "sampled"
    ),
    "qualified": "{text} — {reduced}",
    "blind": "Agent tracking blind since {at} — {fields}",
    "git-slow": "git slow — git facts as of {at}",
    "git-slow-none": "git slow — no git facts yet",
    "stuck": "may be stuck — {tool} open for {ago}",
    "dir-missing": "planning dir gone — its hooks still hold pushes",
    "unreadable": "unreadable: {name}",
    "recording_none": (
        "No events recorded for this run (tracking may be off in its sessions: {name})"
    ),
    "no-args": "no report: no marker or registry entry of this run records its args",
}
# each attention kind's severity; the waiting kinds have none
SEVERITY = {
    "blind": "red",
    "dir-missing": "red",
    "stuck": "amber",
    "reduced": "amber",
    "git-slow": "amber",
    "unreadable": "amber",
    "flag": "amber",
}

Item = dict[str, str | None]


def hhmm(t: float) -> str:
    """Return epoch seconds as HH:MM in the server's local time."""
    return time.strftime("%H:%M", time.localtime(t))


def _item(
    kind: str,
    of: tuple[Route, Run],
    subject: str | None,
    since: float | None,
    text: str,
) -> Item:
    """Return one waiting or attention item of a live run, of its (route, run)."""
    route, run = of
    return {
        "kind": kind,
        "severity": SEVERITY.get(kind),
        "route": route.key,
        "run": run.key,
        "subject": subject,
        "since": iso(since),
        "text": text,
    }


def _oldest(item: Item) -> tuple[bool, str]:
    """Sort key: oldest `since` first, none last (ISO strings sort as times)."""
    since = item["since"]
    return since is None, since or ""


def _urgent(item: Item) -> tuple[bool, bool, str]:
    """Sort key: red before amber, then oldest first."""
    return (item["severity"] != "red", *_oldest(item))


def _qualified(text: str, log: SessionLog | None) -> str:
    """Return text with the reduced-recording qualifier when log passed its cap."""
    if log is None or not log.cap:
        return text
    return COPY["qualified"].format(text=text, reduced=COPY["reduced"])


def _groups(run: Run) -> list[Group]:
    """Return the run's line groups."""
    return [s.group for s in run.sightings if s.group is not None]


def _in(group: Group | None, groups: list[Group]) -> bool:
    """Whether group is one of groups (by identity: groups compare by value)."""
    return any(g is group for g in groups)


def waiting(route: Route, run: Run) -> list[Item]:
    """Return a live run's items that wait on the user (§4.5), oldest first.

    Each from a session's newest lead event, while the session has not ended.

    Args:
        route: The run's route.
        run: The run; an ended one has none.

    Returns:
        Its `asked` and `input` items.
    """
    if not run.live:
        return []
    groups, out = _groups(run), list[Item]()
    for sid, log in sorted(run.logs.items()):
        lead = log.lead
        if log.ended or lead is None or not _in(lead.group, groups):
            continue
        asked = (
            (lead.ev in {"pre", "dispatch"} and lead.decision == "ask")
            or (lead.ev == "pre" and lead.tool == "AskUserQuestion")
            or (
                lead.ev == "notify"
                and lead.type in {"permission_prompt", "elicitation_dialog"}
            )
        )
        idle = (lead.ev == "turn-end" and lead.idle_bg) or (
            lead.ev == "notify" and lead.type == "idle_prompt"
        )
        if asked:
            kind = "asked"
        elif idle and not any(a.state in _RUNNING for a in log.agents):
            kind = "input"
        else:
            continue
        text = COPY["waiting"].format(route=route.name, kind=kind, at=hhmm(lead.t))
        text = _qualified(text, log) if asked else text
        out.append(_item(kind, (route, run), sid, lead.t, text))
    return sorted(out, key=_oldest)


def stuck_call(route: Route, run: Run, a: Agent) -> OpenCall | None:
    """Return the agent's call that makes it likely stuck (§4.5), else None.

    Args:
        route: The run's route; only an active one's agents can be stuck.
        run: The agent's run; only a live one's agents can be stuck.
        a: The agent; only a launched or active one can be stuck.

    Returns:
        Its oldest call open past STUCK_S that does not wait on the user.
    """
    if not run.live or route.status != "active" or a.state not in _RUNNING[1:]:
        return None
    return a.calls.stuck(route.now)


def _stuck(route: Route, run: Run) -> list[Item]:
    """Return the `stuck` items of a live run: its agents', then each lead's."""
    found: list[tuple[str, OpenCall, SessionLog | None]] = []
    for a in run.agents:
        call = stuck_call(route, run, a)
        if call is not None:
            found.append((a.name or "agent", call, run.logs.get(a.session)))
    if route.status == "active":
        groups = _groups(run)
        for log in run.logs.values():
            call = None if log.ended else log.calls.stuck(route.now)
            if call is not None and _in(call.group, groups):
                found.append(("lead", call, log))
    out: list[Item] = []
    for subject, call, log in found:
        ago = common.ago(route.now - call.since)
        text = COPY["stuck"].format(tool=call.tool or "a tool", ago=ago)
        out.append(
            _item("stuck", (route, run), subject, call.since, _qualified(text, log))
        )
    return out


def attention(route: Route, run: Run, reports: "Reports | None" = None) -> list[Item]:
    """Return a live run's attention items (§4.5), red before amber, oldest first.

    Args:
        route: The run's route.
        run: The run; an ended one has none.
        reports: The route's report refreshes, None before its first.

    Returns:
        Its items of every kind but the waiting ones.
    """
    if not run.live:
        return []
    out: list[Item] = []
    if route.dir_missing:
        out.append(_item("dir-missing", (route, run), None, None, COPY["dir-missing"]))
    blind = _blind(run)
    if blind is not None:
        at, fields = blind
        text = COPY["blind"].format(at=hhmm(at), fields=", ".join(fields))
        out.append(_item("blind", (route, run), None, at, text))
    caps = [log.cap_at for log in run.logs.values() if log.cap_at is not None]
    if caps:
        out.append(_item("reduced", (route, run), None, min(caps), COPY["reduced"]))
    names = [pathlib.PurePath(route.marker).name] if route.torn else []
    names += [e["source"] for e in route.errors]
    names += [f"{s}.jsonl" for s, log in sorted(run.logs.items()) if log.skipped]
    for name in names:
        text = COPY["unreadable"].format(name=name)
        out.append(_item("unreadable", (route, run), name, None, text))
    if reports is not None and route.repo is not None and reports.git_state == "slow":
        at = _git_as_of(reports)
        text = (
            COPY["git-slow-none"]
            if at is None
            else COPY["git-slow"].format(at=hhmm(at))
        )
        out.append(_item("git-slow", (route, run), None, at, text))
    rep = None if reports is None else reports.report()
    for flag in [] if rep is None else rep["flags"]:
        # the flag's own line, before the API copy drops it from the report
        if flag["kind"] in ATTENTION_FLAGS:
            item = _item("flag", (route, run), flag["subject"], None, flag["line"])
            out.append(item)
    out += _stuck(route, run)
    return sorted(out, key=_urgent)


def _git_as_of(reports: "Reports") -> float | None:
    """The as_of of the route's last good git facts, None without any."""
    git = None if reports.git is None else reports.git["git"]
    return None if git is None else git["as_of"]


def _git_json(route: Route, run: Run, reports: "Reports | None") -> dict[str, object]:
    """A run's `git`: not tracked when ended or without --repo; pending before."""
    if not run.live or route.repo is None:
        return {"state": "not_tracked", "as_of": None, "ms": None}
    if reports is None:
        return {"state": "pending", "as_of": None, "ms": None}
    at = _git_as_of(reports)
    return {"state": reports.git_state, "as_of": iso(at), "ms": reports.git_ms}


def _gaps(run: Run, sid: str) -> tuple[float, list[str]] | None:
    """Return the ts and gap fields of the session's first gap line in the run."""
    gaps = [
        (s.group.gap_at, s.group.gap)
        for s in run.sightings
        if s.session == sid and s.group is not None and s.group.gap_at is not None
    ]
    return min(gaps, default=None, key=lambda g: g[0])


def _blind_since(run: Run, sid: str) -> float | None:
    """Return the ts of the session's first line in the run that has a `gap`."""
    gap = _gaps(run, sid)
    return None if gap is None else gap[0]


def _blind(run: Run) -> tuple[float, list[str]] | None:
    """Return the run's first gap: over its open sessions, else over all of them."""
    gaps = {s: _gaps(run, s) for s in run.sessions}
    # the sessions still running decide; with every one ended, all of them
    open_ = [g for s, g in gaps.items() if not (s in run.logs and run.logs[s].ended)]
    found = [g for g in open_ or gaps.values() if g is not None]
    return min(found, default=None, key=lambda g: g[0])


def _session(run: Run, sid: str) -> dict[str, object]:
    """Return one session of a run as the API sends it."""
    mine = [s for s in run.sightings if s.session == sid]
    entries = [s.at for s in mine if s.kind == "entry"]
    lines = [s.at for s in mine if s.kind == "events"]
    log = run.logs.get(sid)
    if log is not None and log.cap:
        recording = "reduced"
    elif lines:
        recording = "seen"
    else:
        recording = "expired" if run.recording == "expired" else "none"
    return {
        "id": sid,
        "activated_at": iso(max(entries, default=None)),
        "last_activity_at": iso(max(lines, default=None)),
        "recording": recording,
        "blind_since": iso(_blind_since(run, sid)),
        "ended": log is not None and log.ended,
        "events_skipped": 0 if log is None else log.skipped,
        "unknown_versions": [] if log is None else sorted(log.versions),
    }


def _agent_json(a: Agent, *, stuck: bool) -> dict[str, object]:
    """Return one agent as the API sends it: no line's free text."""
    call = a.calls.oldest()
    return {
        "key": f"{a.session}-{a.child or a.tuid or 'unknown'}",
        "session": a.session,
        "name": a.name,
        "mode": a.mode,
        "state": a.state,
        "model": a.model,
        "started_at": iso(a.started_at),
        "ended_at": iso(a.ended_at),
        "duration_s": a.duration_s,
        "tools": a.tools,
        "last_tool": a.last_tool,
        "last_tool_at": iso(a.last_tool_at),
        "open_tool": None if call is None else call.tool,
        "open_since": None if call is None else iso(call.since),
        "final_tokens": a.final_tokens,
        "compactions": a.compactions,
        "likely_stuck": stuck,
    }


def reduced(state: "State") -> dict[str, object]:
    """Return the report as the API sends it: no planning file's text.

    `extra`, each file's `last_line` and each flag's `line` are dropped; every other
    field, `decisions` and `lane_files` among them, passes through.
    """
    out: dict[str, object] = {k: v for k, v in state.items() if k != "extra"}
    out["files"] = [
        {k: v for k, v in f.items() if k != "last_line"} for f in state["files"]
    ]
    out["flags"] = [{k: v for k, v in f.items() if k != "line"} for f in state["flags"]]
    return out


def board(state: "State") -> dict[str, dict[str, object]]:
    """Return each lane's board column and gating badge, by lane id (BOARD).

    A queued lane is blocked until every plan it waits for has a merged lane.
    """
    merged = {lane["plan"] for lane in state["lanes"] if lane["state"] == "merged"}
    out: dict[str, dict[str, object]] = {}
    for lane in state["lanes"]:
        column, gating = BOARD[lane["state"]]
        wave = state["waves"].get(lane["plan"])
        needs: set[str] = set() if wave is None else set(wave["waits_for"])
        if lane["state"] == "queued" and not needs <= merged:
            column = "blocked"
        out[lane["id"]] = {"column": column, "gating": gating}
    return out


def summary(state: "State | None", running: int | None) -> dict[str, object]:
    """Return a run's stage and its waves and lanes merged, and its running agents.

    Args:
        state: The run's report, None without one.
        running: The run's running agents, None when its recording knows none.

    Returns:
        The RunDetail `summary` object.
    """
    out: dict[str, object] = {
        "stage": None,
        "waves_merged": None,
        "waves_total": None,
        "lanes_merged": 0,
        "lanes_total": 0,
        "agents_running": running,
    }
    if state is None:
        return out
    stages = state["stages"]
    current = [s["name"] for s in stages if s["state"] == "current"]
    # with no current stage the route is past its last one
    out["stage"] = current[0] if current else (stages[-1]["name"] if stages else None)
    numbers = {
        w["wave_no"] for w in state["waves"].values() if w["wave_no"] is not None
    }
    lanes: dict[int, list[str]] = {}
    for lane in state["lanes"]:
        wave = state["waves"].get(lane["plan"])
        if wave is not None and wave["wave_no"] is not None:
            lanes.setdefault(wave["wave_no"], []).append(lane["state"])
    out["waves_total"] = len(numbers)
    out["waves_merged"] = sum(
        1 for n in numbers if lanes.get(n) and set(lanes[n]) == {"merged"}
    )
    out["lanes_total"] = len(state["lanes"])
    out["lanes_merged"] = sum(lane["state"] == "merged" for lane in state["lanes"])
    return out


def budget(route: Route, run: Run) -> dict[str, object] | None:
    """Return the last budget recorded for the route's newest run, None without one.

    The phase is the marker's for a live run, else the run's registry entry's.
    """
    args = _run_args(route, run)
    if run is not route.reported or args is None:
        return None
    marker = route.marker_data if run.live else {}
    found = common.budgets(route.planning_dir, marker, args.phase)
    if not found:
        return None
    last = found[-1]
    return {
        "label": last["label"],
        "estimate": last["estimate"],
        "groups": last.get("groups"),
        "at": last["at"],
    }


def _report_of(route: Route, run: Run, reports: "Reports | None") -> "State | None":
    """The run's report: only the run its route keeps one for, when it has args."""
    if reports is None or run is not route.reported or _run_args(route, run) is None:
        return None
    return reports.report()


def _files_as_of(state: "State | None") -> float | None:
    """The newest mtime of the files a report lists, None without any."""
    return (
        None
        if state is None
        else max((f["mtime"] for f in state["files"]), default=None)
    )


def rev(run: Run, files_as_of: float | None) -> str:
    """Return the id that changes with a run's files, retained lines or recording."""
    lines = sum(g.lines for g in _groups(run))
    text = f"{int(files_as_of or 0)}|{lines}|{run.recording}"
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:12]


def run_detail(
    route: Route, run: Run, reports: "Reports | None" = None
) -> dict[str, object]:
    """Return a run's detail as `/api/state` and `/api/run` send it.

    Args:
        route: The run's route.
        run: The run.
        reports: The route's report refreshes, None before its first.

    Returns:
        The RunDetail object.
    """
    from dsp_route import switch

    agents = run.agents
    blind = _blind(run)
    unknown = run.recording in {"none", "expired"}
    running = sum(a.state in _RUNNING for a in agents)
    hint = COPY["recording_none"].format(name=switch.NAME)
    mine = reports if run is route.reported else None
    rep = _report_of(route, run, reports)
    # only an ended run's report is of the current files, not of the run
    kept = rep is not None and not run.live
    if _run_args(route, run) is None:
        error = COPY["no-args"]
    else:
        error = None if mine is None else mine.error
    return {
        "key": run.key,
        "run": run.run,
        "state": "live" if run.live else "ended",
        "first_seen_at": iso(run.first_seen_at),
        "last_activity_at": iso(run.last_activity_at),
        "ended_at": None,
        "sessions": [_session(run, s) for s in run.sessions],
        "recording": run.recording,
        "recording_hint": hint if run.recording == "none" else None,
        "blind_since": None if blind is None else iso(blind[0]),
        "report": None if rep is None else reduced(rep),
        "report_as_of": None if rep is None else iso(rep["generated_at"]),
        "report_error": error,
        "current_files": kept,
        "files_as_of": iso(_files_as_of(rep)) if kept else None,
        "git": _git_json(route, run, mine),
        "lanes": {} if rep is None else board(rep),
        "summary": summary(rep, None if unknown else running),
        "budget": budget(route, run),
        "agents": [
            _agent_json(a, stuck=stuck_call(route, run, a) is not None) for a in agents
        ],
        "waiting": waiting(route, run),
        "attention": attention(route, run, mine),
    }


def _route_json(route: Route, reports: "Reports | None") -> dict[str, object]:
    """Return a route with a live run as `routes` and `idle` list it."""
    live = route.live or route.runs[0]
    return {
        "key": route.key,
        "name": route.name,
        "planning_dir": route.planning_dir,
        "repo": route.repo,
        "status": route.status,
        "last_activity_at": iso(live.last_activity_at),
        "planning_dir_missing": route.dir_missing,
        "runs": len(route.runs),
        "run": run_detail(route, live, reports),
    }


def _run_summary(
    route: Route, run: Run, reports: "Reports | None"
) -> dict[str, object]:
    """Return an ended run as `ended` lists it."""
    rep = _report_of(route, run, reports)
    unknown = run.recording in {"none", "expired"}
    return {
        "key": run.key,
        "run": run.run,
        "first_seen_at": iso(run.first_seen_at),
        "last_activity_at": iso(run.last_activity_at),
        "sessions": len(run.sessions),
        "agents": None if unknown else len(run.agents),
        "recording": run.recording,
        "has_report": rep is not None,
        "rev": rev(run, _files_as_of(rep)),
    }


def _ended_json(route: Route, reports: "Reports | None") -> dict[str, object]:
    """Return a route's ended runs as `ended` lists them."""
    return {
        "key": route.key,
        "name": route.name,
        "planning_dir": route.planning_dir,
        "runs": [
            _run_summary(route, run, reports) for run in route.runs if not run.live
        ],
    }


# --- the refresher: reports of each route, in worker threads, under limits


def git_signature(marker: str) -> tuple[tuple[str, int, int], ...]:
    """Return the stat signature of the refs and worktrees a marker's `.git` holds.

    Args:
        marker: The route's marker; its parent is the git-common-dir.

    Returns:
        (path, mtime ns, size) of packed-refs, refs/heads/** and each worktree's HEAD
        and index that exist, sorted.
    """
    top = pathlib.Path(marker).parent
    paths = [
        top / "packed-refs",
        *(top / "refs" / "heads").rglob("*"),
        *top.glob("worktrees/*/HEAD"),
        *top.glob("worktrees/*/index"),
    ]
    out: list[tuple[str, int, int]] = []
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        out.append((str(p), st.st_mtime_ns, st.st_size))
    return tuple(sorted(out))


@dataclasses.dataclass
class Reports:
    """One route's report refreshes (§4.8): each tier's newest object, its limits.

    files: the newest object of either tier; git: the newest good git-tier object;
    deadline, interval: the git tier's current deadline and interval; *_at: when
    each tier was last submitted; *_sig: what it last saw.
    """

    deadline: float
    interval: float
    files: "State | None" = None
    git: "State | None" = None
    git_state: str = "pending"
    git_ms: int | None = None
    error: str | None = None
    busy: bool = False
    free_at: float | None = None
    git_at: float | None = None
    free_sig: tuple[object, ...] = ()
    git_sig: tuple[tuple[str, int, int], ...] = ()

    def report(self) -> "State | None":
        """The run's report: the newest file facts with the newest good git facts."""
        from dsp_route import report

        if self.files is None or self.git is None:
            return self.files or self.git
        merged: State = {**self.files, "git": self.git["git"]}
        return report.derive(merged)


@dataclasses.dataclass
class Job:
    """One refresh in a worker: its route, its tier, its deadline and its time."""

    key: str
    args: common.RouteArgs
    git: bool
    deadline: float
    elapsed: float = 0.0

    def __call__(self) -> "State | None":
        """Collect the report; the git tier under the route's deadline."""
        from dsp_route import report

        t0 = time.monotonic()
        try:
            if not self.git:
                return report.collect(self.args, use_git=False, write_cache=False)
            with common.git_deadline(self.deadline):
                return report.collect(self.args, use_git=True, write_cache=False)
        finally:
            self.elapsed = time.monotonic() - t0


def _run_args(route: Route, run: Run) -> common.RouteArgs | None:
    """The arguments a run's report is collected with: marker's, else entry's."""
    if run.live:
        return route.args
    if run.args is None:
        return None
    return common.checked(common.route_args, {"args": list(run.args)})


class Refresher:
    """Runs due report refreshes in WORKERS threads, at most one per route."""

    def __init__(self, done: Callable[[], None]) -> None:
        """Start no thread until a refresh is due; call done after each one.

        Args:
            done: Called in the worker after each refresh, to publish it.
        """
        self.done: Callable[[], None] = done
        self.lock: threading.Lock = threading.Lock()
        self.routes: dict[str, Reports] = {}
        self.pool: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(
                WORKERS, thread_name_prefix="dsp-worker"
            )
        )

    def due(self, model: Model, now: float) -> None:
        """Submit each route's refresh that has come due (§4.8's tier table).

        Args:
            model: The newest model.
            now: The scan's time.
        """
        for route in model.routes.values():
            run = route.reported
            args = None if run is None else _run_args(route, run)
            if run is None or args is None:
                continue
            with self.lock:
                r = self.routes.setdefault(route.key, Reports(DEADLINE_S, GIT_TTL_S))
                job = None if r.busy else self._job(route, run, args, r, now)
                if job is not None:
                    r.busy = True
            if job is not None:
                fut = self.pool.submit(job)
                fut.add_done_callback(lambda f, job=job: self._done(job, f))

    @staticmethod
    def _job(
        route: Route, run: Run, args: common.RouteArgs, r: Reports, now: float
    ) -> Job | None:
        """The refresh due for route, None when neither tier is."""
        quiet = route.status != "active"
        if run.live and route.repo is not None:
            sig = git_signature(route.marker)
            since = None if r.git_at is None else now - r.git_at
            interval = GIT_IDLE_S if quiet else r.interval
            moved = sig != r.git_sig and (since is None or since >= GIT_FLOOR_S)
            if since is None or since >= interval or moved:
                r.git_at, r.git_sig = now, sig
                r.free_at = now
                return Job(route.key, args, git=True, deadline=r.deadline)
        mtime = _mtime(route.marker)
        sig = (sum(g.lines for g in _groups(run)), mtime if run.live else None)
        since = None if r.free_at is None else now - r.free_at
        ttl = FREE_IDLE_S if quiet else FREE_TTL_S
        if since is None or since >= ttl or sig != r.free_sig:
            r.free_at, r.free_sig = now, sig
            return Job(route.key, args, git=False, deadline=r.deadline)
        return None

    def _done(self, job: Job, fut: "concurrent.futures.Future[State | None]") -> None:
        """Keep a finished refresh's object, or the last good one and why not."""
        from dsp_route import report

        exc = fut.exception()
        state = None if exc is not None else fut.result()
        with self.lock:
            r = self.routes[job.key]
            r.busy = False
            # a git that ran out of time, or a report that came back past it; a
            # None report (no planning dir) is not slow
            late = isinstance(exc, common.GitDeadlineError) or (
                state is not None and job.elapsed > job.deadline
            )
            if job.git and late:
                r.git_state = "slow"
                r.deadline = min(2 * r.deadline, DEADLINE_MAX_S)
                r.interval = min(2 * r.interval, GIT_IDLE_S)
            elif exc is not None:
                first = (str(exc).splitlines() or [""])[0]
                r.error = f"{type(exc).__name__}: {first}"
            elif state is None:
                r.error = "no planning dir"
            elif state["version"] != report.VERSION:
                r.files = r.git = None
                r.error = f"report version {state['version']} is not {report.VERSION}"
            else:
                r.error = None
                r.files = state
                if job.git:
                    r.git, r.git_state = state, "fresh"
                    r.git_ms = round(job.elapsed * 1000)
                    r.interval = GIT_TTL_S
                    if job.elapsed <= r.deadline / 2:
                        r.deadline = max(r.deadline / 2, DEADLINE_S)
        self.done()

    def of(self, route: Route) -> Reports | None:
        """The route's refreshes so far, None before its first."""
        with self.lock:
            return self.routes.get(route.key)


class Live:
    """What the request handlers serve: bytes built once, read by every thread."""

    def __init__(self, page: Page, nonce: str) -> None:
        """Hold the page and this process's nonce; nothing is bound yet.

        Args:
            page: The page read at start-up.
            nonce: This process's ping nonce.
        """
        self.page: Page = page
        self.nonce: str = nonce
        self.pid: int = os.getpid()
        self.port: int = 0
        self.ping: bytes = b""
        self.state: bytes = b""
        self.runs: dict[str, bytes] = {}
        # set by a poll; the scan thread waits on it
        self.due: threading.Event = threading.Event()
        self.refresher: Refresher | None = None
        self.model: Model | None = None
        # the scan thread and each worker publish
        self.lock: threading.Lock = threading.Lock()

    def bound(self, port: int) -> None:
        """Take the port a server bound and build the answers that name it.

        Args:
            port: The bound port.
        """
        self.port = port
        self.ping = as_json(
            {
                "monitor": "dsp",
                "version": API_VERSION,
                "pid": self.pid,
                "nonce": self.nonce,
            }
        )
        self.publish(None)

    def publish(self, model: Model | None) -> None:
        """Build the answers of a model, None before the first scan finished.

        Args:
            model: The newest model.
        """
        with self.lock:
            self.model = model
            self._build(model)

    def _build(self, model: Model | None) -> None:
        """Build the answers of a model, with each route's newest reports."""
        routes = [] if model is None else list(model.routes.values())
        refresher = self.refresher
        reports = {r.key: refresher.of(r) if refresher else None for r in routes}
        live = sorted(
            (r for r in routes if r.live is not None),
            key=lambda r: r.runs[0].last_activity_at,
            reverse=True,
        )
        idle = [_route_json(r, reports[r.key]) for r in live if r.status == "idle"]
        ended = sorted(
            (r for r in routes if any(not run.live for run in r.runs)),
            key=lambda r: max(run.last_activity_at for run in r.runs if not run.live),
            reverse=True,
        )
        runs = [(r, run) for r in live if (run := r.live) is not None]
        waits = sorted((i for r, run in runs for i in waiting(r, run)), key=_oldest)
        items = sorted(
            (i for r, run in runs for i in attention(r, run, reports[r.key])),
            key=_urgent,
        )
        self.state = as_json(
            {
                "version": API_VERSION,
                "page": self.page.digest,
                "generated_at": now_iso(),
                "ready": model is not None,
                "monitor": {"pid": self.pid, "port": self.port},
                "waiting": waits,
                "attention": items,
                "routes": [
                    _route_json(r, reports[r.key]) for r in live if r.status == "active"
                ],
                "idle": idle,
                "ended": [_ended_json(r, reports[r.key]) for r in ended],
                "counts": {
                    "waiting": len(waits),
                    "idle": len(idle),
                    "ended": len(ended),
                },
                "errors": [] if model is None else model.errors,
                "events_unjoined": 0 if model is None else model.events_unjoined,
            }
        )
        self.runs = {
            run.key: as_json(
                {
                    "version": API_VERSION,
                    "generated_at": now_iso(),
                    "route": {
                        "key": r.key,
                        "name": r.name,
                        "planning_dir": r.planning_dir,
                        "repo": r.repo,
                    },
                    "run": run_detail(r, run, reports[r.key]),
                }
            )
            for r in routes
            for run in r.runs
        }


def scan_forever(live: Live, scanner: Scanner) -> None:
    """Scan when a poll asks, at most once per SCAN_S; submit what came due; publish.

    Args:
        live: The answers to rebuild; its `due` event wakes the scan.
        scanner: The scanner, whose tail state carries over.
    """
    model: Model | None = None
    while True:
        _ = live.due.wait()
        live.due.clear()
        now = time.time()
        model = discover(scanner.scan(now), model, now)
        if live.refresher is not None:
            live.refresher.due(model, now)
        live.publish(model)
        time.sleep(SCAN_S)


JSON = "application/json; charset=utf-8"


def handler(live: Live) -> type[http.server.BaseHTTPRequestHandler]:
    """Return the request handler class that serves live.

    Args:
        live: The answers to serve.

    Returns:
        A handler for GET only; any other method gets http.server's 501.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        """One request: the Host check first, then the page or an API answer."""

        @override
        def log_message(self, *_args: object, **_kwargs: object) -> None:
            """Log nothing: a page polling every 5 s would write a line each time."""

        @override
        def end_headers(self) -> None:
            """Add the headers every response carries, errors included."""
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

        def reply(
            self, code: int, body: bytes = b"", headers: dict[str, str] | None = None
        ) -> None:
            """Send code, headers and body."""
            self.send_response(code)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _ = self.wfile.write(body)

        def do_GET(self) -> None:
            """Answer a GET whose Host names this listener; else 421, empty."""
            hosts = self.headers.get_all("Host") or []
            mine = (f"127.0.0.1:{live.port}", f"localhost:{live.port}")
            if len(hosts) != 1 or hosts[0] not in mine:
                self.reply(421)
                return
            url = urllib.parse.urlsplit(self.path)
            if url.path in {"/api/state", "/api/run"}:
                live.due.set()
            if url.path == "/":
                self.reply(
                    200,
                    live.page.body,
                    {
                        "Content-Type": "text/html; charset=utf-8",
                        "Content-Security-Policy": live.page.csp,
                    },
                )
                return
            key = urllib.parse.parse_qs(url.query).get("key", [""])[0]
            body = {
                "/api/ping": live.ping,
                "/api/state": live.state,
                "/api/run": live.runs.get(key),
            }.get(url.path)
            if body is None:
                self.reply(404)
            else:
                self.reply(200, body, {"Content-Type": JSON})

    return Handler


class Server(http.server.ThreadingHTTPServer):
    """The listener: one thread per request, none outliving the process."""

    daemon_threads: bool = True
    # Windows' SO_REUSEADDR admits a second listener on the port; Linux's does not
    allow_reuse_address: bool = os.name != "nt"


def ping(port: int) -> bool:
    """Ask the listener on port for `/api/ping`: is it a dsp monitor?

    Args:
        port: A port on 127.0.0.1 that another process holds.

    Returns:
        True when it answered within PING_TIMEOUT_S with `monitor == "dsp"`.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=PING_TIMEOUT_S)
    try:
        conn.request("GET", "/api/ping")
        body = conn.getresponse().read()
        answer = common.as_dict(common.parse_json(body)) or {}
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        conn.close()
    return answer.get("monitor") == "dsp"


def self_check(port: int, nonce: str) -> Literal["ours", "foreign", "none"]:
    """Ask the port through Windows' curl.exe, where WSL interop has one.

    On WSL2, a Windows process listening on the port gets Windows' requests to
    localhost while the bind here still succeeds.

    Args:
        port: The port this process serves.
        nonce: This process's ping nonce.

    Returns:
        ours: the answer is this process's, or there is no curl.exe to ask; foreign:
        another process answered; none: no answer.
    """
    curl = shutil.which("curl.exe")
    if curl is None:
        return "ours"
    url = f"http://localhost:{port}/api/ping"
    try:
        r = subprocess.run(
            [curl, "-s", "-m", str(PING_TIMEOUT_S), url],
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT_S + 1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "none"
    if r.returncode != 0 or not r.stdout.strip():
        return "none"
    try:
        answer = common.as_dict(common.parse_json(r.stdout)) or {}
    except ValueError:
        return "foreign"
    return "ours" if answer.get("nonce") == nonce else "foreign"


def bind_scan(port: int, live: Live) -> Server | str | None:
    """Serve on the first port of port's range that no other process answers on.

    Args:
        port: The first port of the range; 0 binds one ephemeral port, with no scan,
            no ping and no self-check.
        live: The answers to serve; told the bound port.

    Returns:
        The serving server; or the URL of a dsp monitor that holds a port of the
        range; or None, after one stderr line, when no port could be served.
    """
    last = port + PORT_SPAN - 1
    for p in [port] if port == 0 else range(port, last + 1):
        try:
            server = Server(("127.0.0.1", p), handler(live))
        except OSError as e:
            if port != 0 and e.errno == errno.EADDRINUSE:
                if ping(p):
                    return f"http://localhost:{p}/"
                continue
            where = "an ephemeral port" if port == 0 else f"{p} in {port}–{last}"
            print(f"dsp_monitor: cannot bind {where}: {e.strerror}", file=sys.stderr)
            return None
        live.bound(server.server_address[1])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        verdict = "ours" if port == 0 else self_check(live.port, live.nonce)
        if verdict == "foreign":
            server.shutdown()
            server.server_close()
            continue
        if verdict == "none":
            print(
                f"dsp_monitor: curl.exe got no answer from localhost:{live.port}; "
                "the page may not open from Windows",
                file=sys.stderr,
            )
        return server
    print(f"dsp_monitor: ports {port}–{last} are all taken", file=sys.stderr)
    return None


def _interrupt(_signum: int, _frame: types.FrameType | None) -> None:
    """Turn SIGTERM (and SIGINT, even when ignored at launch) into a Ctrl-C."""
    raise KeyboardInterrupt


class _Args(argparse.Namespace):
    """The command line."""

    port: int = PORT
    open_tab: bool = False


def _port(text: str) -> int:
    """Return a --port value whose whole range fits under 65536."""
    n = int(text)
    top = 65536 - PORT_SPAN
    if not 0 <= n <= top:
        msg = f"{n} is not in 0 to {top}"
        raise argparse.ArgumentTypeError(msg)
    return n


def _args(argv: list[str] | None) -> _Args:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    _ = ap.add_argument("--port", type=_port, default=PORT)
    _ = ap.add_argument("--open", action="store_true", dest="open_tab")
    return ap.parse_args(argv, namespace=_Args())


def _show(url: str, *, open_tab: bool) -> None:
    """Print url, and open it in a browser tab with --open."""
    print(url, flush=True)
    if open_tab and not webbrowser.open(url):
        print(f"dsp_monitor: no browser opened {url}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Serve the monitor until Ctrl-C or SIGTERM.

    Args:
        argv: The arguments; None reads sys.argv.

    Returns:
        The exit code the module docstring lists.
    """
    check_owners()
    args = _args(argv)
    try:
        page = read_page(PAGE)
    except ValueError as e:
        print(f"dsp_monitor: page {PAGE.name}: {e}", file=sys.stderr)
        return 2
    if hasattr(os, "nice"):
        _ = os.nice(NICE)
    live = Live(page, secrets.token_hex(8))
    for sig in (signal.SIGINT, signal.SIGTERM):
        _ = signal.signal(sig, _interrupt)
    found = bind_scan(args.port, live)
    if found is None:
        return 1
    if isinstance(found, str):
        _show(found, open_tab=args.open_tab)
        return 0
    from dsp_route import record

    scanner = Scanner(common.REGISTRY, record.EVENTS)
    live.refresher = Refresher(lambda: live.publish(live.model))
    threading.Thread(
        target=scan_forever, args=(live, scanner), name="dsp-scan", daemon=True
    ).start()
    try:
        _show(f"http://localhost:{live.port}/", open_tab=args.open_tab)
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                time.sleep(3600)
    finally:
        found.shutdown()
        found.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
