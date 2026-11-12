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
    """Return obj as compact UTF-8 JSON."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


def iso(t: float | None) -> str | None:
    """Return epoch seconds as UTC ISO 8601 with `Z`; None stays None."""
    if t is None:
        return None
    return dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def home(path: str | None) -> str | None:
    """Return path with the HOME prefix replaced by `~`."""
    top = str(pathlib.Path.home())
    if path is not None and (path == top or path.startswith(top + os.sep)):
        return "~" + path[len(top) :]
    return path


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


@dataclasses.dataclass
class Group:
    """The retained event lines of one session for one (run, planning dir, marker)."""

    first_ts: float
    last_ts: float
    lines: int = 0


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
    """What the tail of one session's event log has folded so far."""

    ident: tuple[int, int]
    offset: int = 0
    groups: dict[GroupKey, Group] = dataclasses.field(default_factory=dict)


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
                log = self.logs[path.stem] = SessionLog(ident)
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
        end = data.rfind(b"\n") + 1
        log.offset += end
        for raw in data[:end].splitlines():
            try:
                line = common.as_dict(common.parse_json(raw))
            except ValueError:
                continue
            if line is not None:
                fold_line(log, line)

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


def fold_line(log: SessionLog, line: dict[str, object]) -> None:
    """Fold one parsed event line into its session's state.

    Args:
        log: The session's folded state.
        line: The line, parsed.
    """
    t = line.get("ts")
    if not isinstance(t, int | float):
        return
    t = float(t)
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
    marker did not parse this scan; runs: listed runs, newest activity first.
    """

    key: str
    planning_dir: str
    marker: str
    claim: Claim | None
    torn: bool
    runs: list[Run]
    repo: str | None = None
    dir_missing: bool = False
    status: Literal["active", "idle"] | None = None

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
        listed.append(r)
    if not listed:
        return None
    listed.sort(key=lambda r: r.last_activity_at, reverse=True)
    out = Route(key, planning, mf.path, claim, torn, listed)
    if out.live is not None:
        out.dir_missing = not scan.dirs[planning]
        args = common.checked(common.route_args, mf.read.data)
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
    model = Model({}, scan.errors)
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
    "dir-missing": "planning dir gone — its hooks still hold pushes",
    "unreadable": "unreadable: {name}",
}

Item = dict[str, str | None]


def _item(
    kind: str, severity: str | None, route: Route, subject: str | None, text: str
) -> Item:
    """Return one waiting or attention item of route's live run."""
    live = route.live
    return {
        "kind": kind,
        "severity": severity,
        "route": route.key,
        "run": None if live is None else live.key,
        "subject": subject,
        "since": None,
        "text": text,
    }


def _items(route: Route) -> list[Item]:
    """Return the attention items of a route's live run."""
    out: list[Item] = []
    if route.dir_missing:
        out.append(_item("dir-missing", "red", route, None, COPY["dir-missing"]))
    if route.torn:
        name = pathlib.PurePath(route.marker).name
        text = COPY["unreadable"].format(name=name)
        out.append(_item("unreadable", "amber", route, name, text))
    return out


def _session(run: Run, sid: str) -> dict[str, object]:
    """Return one session of a run as the API sends it."""
    mine = [s for s in run.sightings if s.session == sid]
    entries = [s.at for s in mine if s.kind == "entry"]
    lines = [s.at for s in mine if s.kind == "events"]
    return {
        "id": sid,
        "activated_at": iso(max(entries, default=None)),
        "last_activity_at": iso(max(lines, default=None)),
        "ended": False,
    }


def run_detail(route: Route, run: Run) -> dict[str, object]:
    """Return a run's detail as `/api/state` and `/api/run` send it.

    Args:
        route: The run's route.
        run: The run.

    Returns:
        The RunDetail object.
    """
    return {
        "key": run.key,
        "run": run.run,
        "state": "live" if run.live else "ended",
        "first_seen_at": iso(run.first_seen_at),
        "last_activity_at": iso(run.last_activity_at),
        "ended_at": None,
        "sessions": [_session(run, s) for s in run.sessions],
        "attention": _items(route) if run.live else [],
    }


def _route_json(route: Route) -> dict[str, object]:
    """Return a route with a live run as `routes` and `idle` list it."""
    live = route.live or route.runs[0]
    return {
        "key": route.key,
        "name": route.name,
        "planning_dir": home(route.planning_dir),
        "repo": home(route.repo),
        "status": route.status,
        "last_activity_at": iso(live.last_activity_at),
        "planning_dir_missing": route.dir_missing,
        "runs": len(route.runs),
        "run": run_detail(route, live),
    }


def _ended_json(route: Route) -> dict[str, object]:
    """Return a route's ended runs as `ended` lists them."""
    return {
        "key": route.key,
        "name": route.name,
        "planning_dir": home(route.planning_dir),
        "runs": [
            {
                "key": run.key,
                "run": run.run,
                "first_seen_at": iso(run.first_seen_at),
                "last_activity_at": iso(run.last_activity_at),
                "sessions": len(run.sessions),
            }
            for run in route.runs
            if not run.live
        ],
    }


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
        routes = [] if model is None else list(model.routes.values())
        live = sorted(
            (r for r in routes if r.live is not None),
            key=lambda r: r.runs[0].last_activity_at,
            reverse=True,
        )
        idle = [_route_json(r) for r in live if r.status == "idle"]
        ended = sorted(
            (r for r in routes if any(not run.live for run in r.runs)),
            key=lambda r: max(run.last_activity_at for run in r.runs if not run.live),
            reverse=True,
        )
        attention = [i for r in live for i in _items(r)]
        attention.sort(key=lambda i: i["severity"] != "red")
        self.state = as_json(
            {
                "version": API_VERSION,
                "page": self.page.digest,
                "generated_at": now_iso(),
                "ready": model is not None,
                "monitor": {"pid": self.pid, "port": self.port},
                "waiting": [],
                "attention": attention,
                "routes": [_route_json(r) for r in live if r.status == "active"],
                "idle": idle,
                "ended": [_ended_json(r) for r in ended],
                "counts": {"waiting": 0, "idle": len(idle), "ended": len(ended)},
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
                        "planning_dir": home(r.planning_dir),
                        "repo": home(r.repo),
                    },
                    "run": run_detail(r, run),
                }
            )
            for r in routes
            for run in r.runs
        }


def scan_forever(live: Live, scanner: Scanner) -> None:
    """Scan when a poll asks, at most once per SCAN_S, and publish each model.

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
    threading.Thread(target=scan_forever, args=(live, scanner), daemon=True).start()
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
