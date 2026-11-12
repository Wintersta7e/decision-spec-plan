# SPDX-License-Identifier: MIT
"""Fixtures and helpers shared by the hook and checker tests.

Every test runs the scripts as the hooks run them: a subprocess, its environment built
from scratch (PATH, a throwaway HOME, no system git config), so no `CLAUDECODE`,
`CLAUDE_*` session or real registry reaches it unless a case sets it. Each check is a
subTest named by what it checks, so a failure names the check and the rest of the method
still runs.
"""

import dataclasses
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import resource
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import (
    IO,
    ClassVar,
    Final,
    Literal,
    Required,
    TypedDict,
    Unpack,
    cast,
    overload,
)

# typing.override is 3.12+; the tests need dev-only packages anyway (pytest)
from typing_extensions import override

import dsp_monitor
from dsp_route.common import RegistryEntry, route_slug

TESTS = Path(__file__).resolve().parent
PLUGIN = TESTS.parent
SCRIPTS = PLUGIN / "scripts"
RS = SCRIPTS / "route_state.py"
GUARD = SCRIPTS / "push_guard.py"
PY = sys.executable
sys.path.insert(0, str(SCRIPTS))  # the modules some tests import
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]

StrPath = str | os.PathLike[str]


class GrepFlags(TypedDict, total=False):
    """The grep options besides count: -E, -F and -x."""

    E: bool
    F: bool
    x: bool


class RunOptions(TypedDict, total=False):
    """The options of `Sandbox.run_`, which `py` and `git` pass through."""

    input: str | None
    env: Mapping[str, str] | None
    unset: Iterable[str]
    cwd: StrPath | None
    merge: bool
    memory: int | None
    timeout: float | None


class Marker(TypedDict, total=False):
    """A route marker as `route_state.py --activate` writes it."""

    args: Required[list[str]]
    planning_dir: Required[str]
    activated: Required[float]
    rung: str
    budgets: list[dict[str, object]]
    asks: list[object]
    ci_harness: str
    ci_none: bool
    sins: str
    ledger: Required[dict[str, bool | int]]
    run: str
    run_upgraded: bool


class _BudgetFile(TypedDict):
    """The planning dir's `route-budget.json`."""

    budgets: list[dict[str, object]]


def jline(obj: object) -> str:
    """One JSON record as `jq -nc` writes it."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def jstr(text: str) -> str:
    """A string as `jq -Rs . <<<"$text"` quotes it: the here-string adds a newline."""
    return json.dumps(text + "\n", ensure_ascii=False)


def ts(offset: float) -> str:
    """An ISO timestamp `offset` seconds from now, in the transcripts' UTC form."""
    t = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(offset))
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bracket(p: str, i: int) -> int:
    """The end of the bracket expression that opens at p[i]."""
    j = i + 1
    if p[j : j + 1] == "^":
        j += 1
    if p[j : j + 1] == "]":
        j += 1
    return p.index("]", j)


def _posix(p: str, *, basic: bool) -> str:
    """A grep pattern (basic or extended) as a Python regex."""
    out: list[str] = []
    i = 0
    while i < len(p):
        c = p[i]
        if c == "\\" and i + 1 < len(p):
            n = p[i + 1]
            if basic and n in "(){}|+?":
                out.append(n)
            elif n in "<>":
                out.append(r"\b")
            else:
                out.append("\\" + n)
            i += 2
            continue
        if c == "[":
            j = _bracket(p, i)
            out.append(p[i : j + 1].replace("\\", "\\\\"))
            i = j + 1
            continue
        out.append("\\" + c if basic and c in "(){}|+?" else c)
        i += 1
    return "".join(out)


@overload
def grep(
    text: str,
    pattern: str,
    *,
    count: Literal[False] = False,
    **flags: Unpack[GrepFlags],
) -> bool: ...


@overload
def grep(
    text: str,
    pattern: str,
    *,
    count: Literal[True],
    **flags: Unpack[GrepFlags],
) -> int: ...


def grep(
    text: str,
    pattern: str,
    *,
    count: bool = False,
    **flags: Unpack[GrepFlags],
) -> bool | int:
    """Whether `grep -q` finds pattern in text as `<<<"$text"` feeds it.

    With count, the number of matching lines instead. The pattern is a basic regex by
    default; flags E, F and x are grep's -E, -F and -x.
    """
    lines = text.split("\n")
    whole = flags.get("x", False)
    rx = (
        None
        if flags.get("F", False)
        else re.compile(_posix(pattern, basic=not flags.get("E", False)))
    )

    def hit(line: str) -> bool:
        if rx is None:
            return line == pattern if whole else pattern in line
        return bool(rx.fullmatch(line) if whole else rx.search(line))

    n = sum(1 for line in lines if hit(line))
    return n if count else n > 0


def grep_file(path: StrPath, pattern: str, **flags: Unpack[GrepFlags]) -> bool:
    """Grep over a file's lines."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return grep(text.removesuffix("\n"), pattern, **flags)


class Result:
    """A finished command: code, and out as `$( … )` captures it.

    out is stdout with its trailing newlines cut.
    """

    def __init__(self, proc: subprocess.CompletedProcess[str]) -> None:
        """Take the exit code and the captured stdout of proc."""
        self.code: int = proc.returncode
        self.out: str = proc.stdout.rstrip("\n")


def ev(event: str, session: str, extra: str = "") -> str:
    """A hook event as the bash suite spelled it, field for field."""
    tail = f",{extra}" if extra else ""
    return (
        f'{{"hook_event_name":"{event}","session_id":"{session}","cwd":"/tmp"{tail}}}'
    )


def _hook_spec(out: str) -> dict[str, object] | None:
    """The `hookSpecificOutput` object a hook printed, or None when out holds none."""
    try:
        data = cast("object", json.loads(out))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    spec = cast("dict[str, object]", data).get("hookSpecificOutput")
    return cast("dict[str, object]", spec) if isinstance(spec, dict) else None


def hook_matches(want: str, out: str) -> bool:
    """Whether the hook's output meets want.

    want is silent | report | delta | /regex/ | deny:regex | ask:regex, the regexes read
    against the context or the permission reason.
    """
    if want == "silent":
        return out == ""
    spec = _hook_spec(out)
    if spec is None:
        return False
    for kind in ("deny", "ask"):
        if want.startswith(kind + ":"):
            reason = spec.get("permissionDecisionReason")
            return (
                spec.get("permissionDecision") == kind
                and isinstance(reason, str)
                and re.search(want[len(kind) + 1 :], reason) is not None
            )
    ctx = spec.get("additionalContext")
    if not isinstance(ctx, str):
        return False
    rx = {"report": "route state ·", "delta": "changed between"}.get(want, want[1:-1])
    return re.search(rx, ctx) is not None


def bash_q(text: str) -> str:
    """`printf %q` of text, as bash quotes it."""
    bash = shutil.which("bash") or "bash"
    return subprocess.run(
        [bash, "-c", 'printf %q "$1"', "_", text],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _marker_path(repo: StrPath, plan: StrPath | None = None) -> Path:
    """The marker of the route whose planning dir is plan (default <repo>/.plan)."""
    real = os.path.realpath(plan or Path(repo) / ".plan")
    digest = hashlib.sha1(real.encode(), usedforsecurity=False).hexdigest()[:10]
    return Path(repo) / ".git" / f"dsp-route-{digest}.json"


class Sandbox(unittest.TestCase):
    """A throwaway directory T with HOME under it.

    With `no_hooks`, git's global core.hooksPath names a directory with no hooks:
    --activate then installs no pre-push hook, and the command guard's own checks are
    what the tests see.
    """

    no_hooks: ClassVar[bool] = True
    maxDiff: int | None = None

    _tmp: ClassVar[tempfile.TemporaryDirectory[str]]
    env: ClassVar[dict[str, str]]

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Create T and HOME, and the environment every run starts from."""
        cls._tmp = tempfile.TemporaryDirectory(prefix="dsp-test-")
        cls.T: Path = Path(cls._tmp.name).resolve()
        cls.HOME: Path = cls.T / "home"
        cls.HOME.mkdir()
        cls.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(cls.HOME),
            "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C.UTF-8",
            # coverage's subprocess patch reaches each script run through these
            **{k: v for k, v in os.environ.items() if k.startswith("COVERAGE_")},
        }
        if cls.no_hooks:
            _ = cls.git("config", "--global", "core.hooksPath", f"{cls.T}/no-hooks")

    @override
    @classmethod
    def tearDownClass(cls) -> None:
        """Remove T."""
        cls._tmp.cleanup()

    # --- running things

    @classmethod
    def run_(cls, argv: Iterable[object], **kw: Unpack[RunOptions]) -> Result:
        """Run argv in the sandbox's environment plus env, less unset.

        stderr is merged into out with merge, else left out; memory caps the address
        space in bytes.
        """
        full = {**cls.env, **(kw.get("env") or {})}
        for name in kw.get("unset", ()):
            _ = full.pop(name, None)
        memory = kw.get("memory")

        def cap() -> None:
            if memory:
                resource.setrlimit(resource.RLIMIT_AS, (memory, memory))

        proc = subprocess.run(
            [str(a) for a in argv],
            input=kw.get("input"),
            env=full,
            cwd=kw.get("cwd"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if kw.get("merge", False) else subprocess.DEVNULL,
            text=True,
            errors="replace",
            preexec_fn=cap if memory else None,
            timeout=kw.get("timeout"),
            check=False,
        )
        return Result(proc)

    @classmethod
    def py(
        cls,
        script: str | Path,
        *args: object,
        session: str | None = None,
        **kw: Unpack[RunOptions],
    ) -> Result:
        """A script of the plugin run with python3.

        session, when given, sets CLAUDE_CODE_SESSION_ID.
        """
        env = dict(kw.get("env") or {})
        if session is not None:
            env["CLAUDE_CODE_SESSION_ID"] = session
        kw["env"] = env
        path = script if isinstance(script, Path) else SCRIPTS / script
        return cls.run_([PY, path, *args], **kw)

    @overload
    @classmethod
    def git(
        cls, *args: object, check: Literal[True] = True, **kw: Unpack[RunOptions]
    ) -> str: ...

    @overload
    @classmethod
    def git(
        cls, *args: object, check: Literal[False], **kw: Unpack[RunOptions]
    ) -> Result: ...

    @classmethod
    def git(
        cls, *args: object, check: bool = True, **kw: Unpack[RunOptions]
    ) -> str | Result:
        """Git with the throwaway identity; its stdout, or the Result without check."""
        r = cls.run_([*GIT, *args], **kw)
        if check and r.code != 0:
            msg = f"git {' '.join(map(str, args))} failed: {r.out}"
            raise AssertionError(msg)
        return r.out if check else r

    @classmethod
    def rev(cls, repo: StrPath, ref: str = "HEAD") -> str:
        """The commit ref names in repo."""
        return cls.git("-C", repo, "rev-parse", ref)

    @classmethod
    def init_repo(
        cls, path: StrPath, branch: str = "main", commits: Iterable[str] = ("one",)
    ) -> Path:
        """A new repository at path on branch, with one empty commit per message."""
        _ = cls.git("init", "-q", "-b", branch, path)
        for m in commits:
            _ = cls.git("-C", path, "commit", "-q", "--allow-empty", "-m", m)
        return Path(path)

    @staticmethod
    def write(path: StrPath, text: str, mode: Literal["w", "a"] = "w") -> Path:
        """Text written (or appended, with mode "a") to path, its parents created."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode, encoding="utf-8", newline="") as f:
            _ = f.write(text)
        return path

    @staticmethod
    def write_bytes(path: StrPath, data: bytes) -> Path:
        """Bytes written to path, its parents created."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(data)
        return path

    @staticmethod
    def append(path: StrPath, *lines: str) -> None:
        """Records appended to a transcript, one per line."""
        with Path(path).open("a", encoding="utf-8") as f:
            _ = f.write("".join(line + "\n" for line in lines))

    @staticmethod
    def touch(path: StrPath, offset: float = 0) -> None:
        """A file's mtime set `offset` seconds from now (created when missing)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        t = dt.datetime.now(dt.UTC).timestamp() + offset
        os.utime(path, (t, t))

    @classmethod
    def index_state(cls, repo: StrPath) -> tuple[int, int, str, bool]:
        """The index of repo's worktree: inode, mtime_ns, SHA-1, and a lock's presence.

        A linked worktree has its own index under `worktrees/<name>/`, so the path comes
        from git. Any rewrite of the index changes the tuple.
        """
        index = Path(
            cls.git(
                "-C", repo, "rev-parse", "--path-format=absolute", "--git-path", "index"
            )
        )
        st = index.stat()
        digest = hashlib.sha1(index.read_bytes(), usedforsecurity=False).hexdigest()
        return (
            st.st_ino,
            st.st_mtime_ns,
            digest,
            Path(str(index) + ".lock").exists(),
        )

    @staticmethod
    def stat_dirty(path: StrPath) -> None:
        """A tracked file made stat-dirty: its stat data no longer matches the index.

        Its atime and mtime go one hour back and its content stays, so `git status`
        refreshes the index entry and rewrites the index when it may take the lock.
        """
        Sandbox.touch(path, -3600)

    @classmethod
    def git_shim(
        cls,
        root: Path,
        sleep: float = 0,
        *,
        ends: bool = False,
        slow: tuple[Path, Path] | None = None,
    ) -> tuple[dict[str, str], Path]:
        """A logging git at root/git: the env that puts it first on PATH, and its log.

        The scripts resolve git by `shutil.which`, so the shim sees every spawn they
        make. Before git runs it appends one line per spawn to root/git.log:
        `<epoch ns> <args>`, the first field `date +%s%N` and the rest `$*`. A count is
        the number of lines; a time stamp is `int(line.split(" ", 1)[0])`. With sleep,
        it waits that many seconds before running git.

        With ends, a spawn logs `start <pid> <epoch ns> <args>`, then, once git exits,
        `end <pid> <epoch ns>`. With slow (a repository, a flag file), a spawn whose
        `-C` names that repository first sleeps the seconds the flag file holds, while
        the file exists. Stdin passes through to git unread.
        """
        real = shutil.which("git", path=cls.env["PATH"])
        if real is None:
            msg = "git_shim: no git on PATH"
            raise AssertionError(msg)
        log = root / "git.log"
        wait = f"sleep {sleep}\n" if sleep else ""
        if slow is not None:
            repo, flag = slow
            wait += (
                'prev=\nfor a in "$@"; do\n'
                f"  if [ \"$prev\" = -C ] && [ \"$a\" = '{repo}' ] && [ -f '{flag}' ];"
                f" then sleep \"$(cat '{flag}')\"; fi\n"
                "  prev=$a\ndone\n"
            )
        stamp = '"$(date +%s%N)"'
        if ends:
            head = f"printf 'start %s %s %s\\n' \"$$\" {stamp} \"$*\" >> '{log}'\n"
            run = (
                f"'{real}' \"$@\"\nrc=$?\n"
                f"printf 'end %s %s\\n' \"$$\" {stamp} >> '{log}'\nexit $rc\n"
            )
        else:
            head = f"printf '%s %s\\n' {stamp} \"$*\" >> '{log}'\n"
            run = f"exec '{real}' \"$@\"\n"
        shim = cls.write(root / "git", f"#!/bin/sh\n{head}{wait}{run}")
        cls.chmod_x(shim)
        return {"PATH": f"{root}{os.pathsep}{cls.env['PATH']}"}, log

    @staticmethod
    def chmod_x(*paths: StrPath) -> None:
        """The execute bits added to each path's mode."""
        for p in paths:
            path = Path(p)
            path.chmod(path.stat().st_mode | 0o111)

    @staticmethod
    def rm(*paths: StrPath) -> None:
        """Each path removed: a directory with its tree, a missing one ignored."""
        for p in paths:
            path = Path(p)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)

    @classmethod
    def events(cls, session: str = "s1") -> list[dict[str, object]]:
        """The lines the recorder wrote to session's log, each parsed.

        An unparseable line fails the test: the recorder writes whole lines only.
        """
        path = cls.HOME / ".claude/dsp-routes/events" / f"{session}.jsonl"
        out: list[dict[str, object]] = []
        for n, line in enumerate(path.read_text().splitlines(), 1):
            try:
                out.append(cast("dict[str, object]", json.loads(line)))
            except ValueError as e:
                msg = f"{path.name}:{n} is no JSON line: {line[:200]}"
                raise AssertionError(msg) from e
        return out

    # --- checks

    def ok(self, msg: str, cond: object, detail: object = "") -> None:
        """One check of the suite: a subTest named msg that holds cond."""
        with self.subTest(msg):
            if not cond:
                self.fail(f"{msg}\n{detail}"[:4000])

    def guard(
        self,
        want: int | Literal["ask"],
        cwd: StrPath,
        command: str,
        agent: str | None = None,
    ) -> Result:
        """push_guard.py on a Bash call of command from cwd (by agent, if given).

        It exits want: an exit code, or "ask" for exit 0 asking the user. An exit 0 must
        print nothing.
        """
        event: dict[str, object] = {"tool_input": {"command": command}, "cwd": str(cwd)}
        if agent:
            event["agent_id"] = agent
        r = self.py(GUARD, input=json.dumps(event), merge=True)
        got: int | str = r.code
        if want == "ask":
            spec = _hook_spec(r.out)
            decision = spec.get("permissionDecision") if spec is not None else None
            if got == 0 and decision == "ask":
                got = "ask"
        elif got == 0 and r.out:
            got = "0 with output"
        self.ok(
            f"guard {want}  {command}" + (f"  (agent {agent})" if agent else ""),
            got == want,
            f"got {got}: {r.out[:600]}",
        )
        return r

    def gmsg(self, cwd: StrPath, command: str) -> str:
        """push_guard.py's output on command from cwd."""
        stdin = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
        return self.py(GUARD, input=stdin, merge=True).out

    last: str = ""

    def hook(self, want: str, event: str, rs: str | Path = RS) -> str:
        """`route_state.py --hook` on event meets want (see hook_matches)."""
        out = self.py(rs, "--hook", input=event + "\n", merge=True).out
        self.last = out
        self.ok(f"hook  {want}  {event}", hook_matches(want, out), out[:1500])
        return out

    def hook_out(self, event: str, rs: str | Path = RS) -> Result:
        """`route_state.py --hook` run on event."""
        return self.py(rs, "--hook", input=event + "\n", merge=True)

    def stophook(self, want: int, rx: str, event: str) -> None:
        """`route_state.py --hook` on a stop event exits want, rx found in its output.

        rx is read as `grep -E` reads it.
        """
        r = self.hook_out(event)
        self.ok(
            f"stop {want}  {event}",
            r.code == want and grep(r.out, rx, E=True),
            f"got {r.code}: {r.out[:600]}",
        )


class Route(Sandbox):
    """The suite's main fixture: repository R, its planning dir P, and a route on it.

    R has main at two commits and feature one behind, with worktree wt on feature; with
    `activate`, session s1 holds a route on it.
    """

    activate: ClassVar[bool] = True

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Create R, its worktree and planning dir, and activate the route."""
        super().setUpClass()
        cls.R: Path = cls.init_repo(cls.T / "repo", commits=("one", "two"))
        _ = cls.git("-C", cls.R, "branch", "feature", "HEAD~1")
        cls.WT: Path = cls.T / "wt"
        _ = cls.git("-C", cls.R, "worktree", "add", "-q", cls.WT, "feature")
        cls.P: Path = cls.R / ".plan"
        for d in ("lanes", "plans", "decisions/phase1", "spec"):
            (cls.P / d).mkdir(parents=True)
        cls.MAIN: str = cls.rev(cls.R, "main")
        cls.LEAD: Path = cls.HOME / ".claude/projects/p/s1.jsonl"
        if cls.activate:
            _ = cls.activate_route()

    @classmethod
    def activate_route(
        cls, *extra: object, session: str = "s1", phase: str = "1"
    ) -> Result:
        """`route_state.py --activate` of phase on R by session, plus extra."""
        return cls.py(
            RS,
            cls.P,
            "--phase",
            phase,
            "--repo",
            cls.R,
            "--sections",
            "1-",
            "--activate",
            *extra,
            session=session,
            merge=True,
        )

    MK: Final = staticmethod(_marker_path)

    @classmethod
    def marker(cls, repo: StrPath | None = None, plan: StrPath | None = None) -> Marker:
        """The route marker of repo (default R) and plan, as read from disk."""
        return cast("Marker", json.loads(cls.MK(repo or cls.R, plan).read_text()))

    @classmethod
    def entry(cls, session: str = "s1") -> RegistryEntry:
        """The registry entry of session, as read from disk."""
        path = cls.HOME / ".claude/dsp-routes" / f"{session}.json"
        return cast("RegistryEntry", json.loads(path.read_text()))

    @classmethod
    def budgets(cls, plan: StrPath | None = None) -> list[dict[str, object]]:
        """The budgets `route_state.py --budget` recorded in the planning dir."""
        path = Path(plan or cls.P) / "route-budget.json"
        if not path.exists():
            return []
        return cast("_BudgetFile", json.loads(path.read_text()))["budgets"]

    @classmethod
    def set_marker(
        cls, data: Marker, repo: StrPath | None = None, plan: StrPath | None = None
    ) -> None:
        """The route marker of repo (default R) and plan replaced by data."""
        _ = cls.MK(repo or cls.R, plan).write_text(json.dumps(data))

    @classmethod
    def edit_marker(
        cls, fn: Callable[[Marker], object], repo: StrPath | None = None
    ) -> None:
        """The route marker of repo (default R) changed in place by fn."""
        m = cls.marker(repo)
        _ = fn(m)
        cls.set_marker(m, repo)

    def unthrottle(self) -> None:
        """The hook's throttle stamps removed, so its next run checks again."""
        for f in (self.HOME / ".claude/dsp-routes").glob("*.checked"):
            f.unlink()


# --- the route monitor, scripts/dsp_monitor.py, run as a subprocess

# The monitor's test entry: `PY -c MONITOR_ENTRY <options as JSON>`. It sets the
# module's constants named in "set" (a name the module lacks exits 3), points PAGE at
# "page", deletes os.nice with "delete_nice", and with "probe" appends one JSON line
# per report.collect and subprocess.run call to that file: what ran, its thread and
# the thread's name, use_git and the planning dir (collect), whether no git deadline
# was set, its argv and timeout (run), and its start and end.
MONITOR_ENTRY: Final[str] = """
import json, os, pathlib, sys, threading, time
opts = json.loads(sys.argv[1])
sys.path.insert(0, opts["scripts"])
import dsp_monitor
for name, value in opts["set"].items():
    if not hasattr(dsp_monitor, name):
        sys.exit(3)
    setattr(dsp_monitor, name, tuple(value) if isinstance(value, list) else value)
if opts["page"] is not None:
    dsp_monitor.PAGE = pathlib.Path(opts["page"])
if opts["delete_nice"]:
    del os.nice
if opts["probe"] is not None:
    import subprocess
    from dsp_route import common, report
    lock = threading.Lock()
    def note(what, t0, **extra):
        line = {"what": what, "thread": threading.get_ident(),
                "thread_name": threading.current_thread().name,
                "deadline_unset": common.GIT_DEADLINE.get() is None,
                "t0": t0, "t1": time.time(), **extra}
        with lock, open(opts["probe"], "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\\n")
    collect, run = report.collect, subprocess.run
    def collect_probe(*a, **k):
        t0 = time.time()
        try:
            return collect(*a, **k)
        finally:
            note("collect", t0, use_git=k.get("use_git"),
                 planning_dir=a[0].planning_dir)
    def run_probe(*a, **k):
        t0 = time.time()
        try:
            return run(*a, **k)
        finally:
            argv = [str(x) for x in (a[0] if a else k["args"])]
            note("run", t0, use_git=None, argv=argv, timeout=k.get("timeout"))
    report.collect = collect_probe
    subprocess.run = run_probe
sys.exit(dsp_monitor.main(opts["argv"]))
"""


class MonitorOptions(TypedDict, total=False):
    """How `start_monitor` and `run_monitor` launch the monitor; see MONITOR_ENTRY."""

    consts: Mapping[str, object]
    page: StrPath
    delete_nice: bool
    probe: StrPath
    path_prefix: Iterable[StrPath]
    port: int


def monitor_cmd(*args: object, **kw: Unpack[MonitorOptions]) -> list[str]:
    """The command line of the monitor's test entry: `--port <port>` (0) then args."""
    page, probe = kw.get("page"), kw.get("probe")
    opts = {
        "scripts": str(SCRIPTS),
        "set": dict(kw.get("consts") or {}),
        "page": None if page is None else str(page),
        "delete_nice": kw.get("delete_nice", False),
        "probe": None if probe is None else str(probe),
        "argv": ["--port", str(kw.get("port", 0)), *map(str, args)],
    }
    return [PY, "-c", MONITOR_ENTRY, json.dumps(opts)]


def monitor_env(
    env: Mapping[str, str], path_prefix: Iterable[StrPath] = ()
) -> dict[str, str]:
    """Env with path_prefix first on PATH and no directory that holds a `curl.exe`.

    So the Windows curl.exe of WSL interop never answers the monitor's self-check
    unless a test puts a stub first.
    """
    dirs = [
        d
        for d in env.get("PATH", "").split(os.pathsep)
        if d and not (Path(d) / "curl.exe").exists()
    ]
    return {**env, "PATH": os.pathsep.join([*map(str, path_prefix), *dirs])}


class Monitor:
    """A running monitor: its process, its URL and port, and an HTTP client for it."""

    def __init__(self, proc: subprocess.Popen[str], url: str) -> None:
        """Wrap proc, which printed url."""
        self.proc: subprocess.Popen[str] = proc
        self.url: str = url
        self.port: int = int(url.rstrip("/").rsplit(":", 1)[1])
        self.code: int | None = None
        self.err: str = ""

    def get(
        self,
        path: str,
        host: str | Iterable[str] | None = None,
        method: str = "GET",
    ) -> tuple[int, dict[str, str], bytes]:
        """Request path; its status, its headers (names lower-cased) and its body.

        host None sends `Host: 127.0.0.1:<port>`; a string sends it; an iterable sends
        one Host header per item, none for an empty one.
        """
        hosts = (
            [f"127.0.0.1:{self.port}"]
            if host is None
            else [host]
            if isinstance(host, str)
            else list(host)
        )
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for h in hosts:
                conn.putheader("Host", h)
            conn.endheaders()
            r = conn.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            conn.close()

    def state(self) -> dict[str, object]:
        """GET /api/state, parsed; a status other than 200 fails the test."""
        code, _, body = self.get("/api/state")
        if code != http.client.OK:
            msg = f"/api/state answered {code}"
            raise AssertionError(msg)
        return cast("dict[str, object]", json.loads(body))

    def wait(
        self, pred: Callable[[dict[str, object]], object], timeout: float = 10
    ) -> dict[str, object]:
        """The first /api/state, polled every 0.2 s, for which pred holds."""
        end = time.monotonic() + timeout
        while True:
            s = self.state()
            if pred(s):
                return s
            if time.monotonic() > end:
                msg = (
                    f"no state met the condition in {timeout} s: {json.dumps(s)[:3000]}"
                )
                raise AssertionError(msg)
            time.sleep(0.2)

    def stop(self) -> int:
        """SIGTERM, wait up to 5 s (then kill); the exit code. Keeps stderr in err."""
        if self.code is None:
            if self.proc.poll() is None:
                self.proc.send_signal(signal.SIGTERM)
            try:
                _, err = self.proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                _, err = self.proc.communicate()
            self.err = str(err)
            code = self.proc.returncode
            self.code = code
            return code
        return self.code


def _first_line(proc: subprocess.Popen[str], timeout: float) -> str:
    """Proc's first stdout line within timeout; "" when it ends or the time runs out."""
    out: IO[str] | None = proc.stdout
    if out is None:
        return ""
    end = time.monotonic() + timeout
    with selectors.DefaultSelector() as sel:
        _ = sel.register(out, selectors.EVENT_READ)
        while (left := end - time.monotonic()) > 0:
            if sel.select(left):
                return out.readline()
    return ""


def start_monitor(
    env: Mapping[str, str], *args: object, **kw: Unpack[MonitorOptions]
) -> Monitor:
    """The monitor started with env (see `monitor_env`), once it printed its URL.

    It fails with the monitor's stderr when it exits, or prints nothing in 10 s, first.
    """
    proc = subprocess.Popen(
        monitor_cmd(*args, **kw),
        env=monitor_env(env, kw.get("path_prefix", ())),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = _first_line(proc, 10).strip()
    if not url:
        m = Monitor(proc, "http://localhost:0/")
        code = m.stop()
        msg = f"the monitor printed no URL (exit {code}): {m.err[-3000:]}"
        raise AssertionError(msg)
    return Monitor(proc, url)


def free_ports(n: int) -> int:
    """A port P with P … P+n-1 each bindable on 127.0.0.1 now."""

    def bindable(port: int) -> bool:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    for _ in range(100):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            first = cast("tuple[str, int]", s.getsockname())[1]
        if all(bindable(first + i) for i in range(1, n)):
            return first
    msg = f"no {n} free ports in a row"
    raise AssertionError(msg)


class MonitorSandbox(Route):
    """A sandbox for the monitor: Route's repository and HOME, no route activated."""

    activate: ClassVar[bool] = False

    def start_monitor(self, *args: object, **kw: Unpack[MonitorOptions]) -> Monitor:
        """The monitor started in this sandbox's env; stopped when the test ends."""
        m = start_monitor(self.env, *args, **kw)
        self.addCleanup(m.stop)
        return m

    def run_monitor(
        self, *args: object, **kw: Unpack[MonitorOptions]
    ) -> subprocess.CompletedProcess[str]:
        """The monitor run to its exit (30 s at most), its stdout and stderr kept."""
        return subprocess.run(
            monitor_cmd(*args, **kw),
            env=monitor_env(self.env, kw.get("path_prefix", ())),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def monitor_on(self, machine: "Machine", **kw: Unpack[MonitorOptions]) -> Monitor:
        """The monitor started on machine's HOME; stopped when the test ends."""
        m = start_monitor(machine.env, **kw)
        self.addCleanup(m.stop)
        return m

    @classmethod
    def build_machine(cls) -> "Machine":
        """The synthetic machine under T (see `build_machine`)."""
        return build_machine(cls.T)


# --- the synthetic machine the monitor tests read (AC-P1-4-33)

# the hook each event kind comes from; a `cap` line is written by the hook that passed
# the cap, any of them
FIXTURE_HOOKS: Final = {
    "dispatch": "PreToolUse",
    "launch": "PostToolUse",
    "return": "PostToolUse",
    "failed": "PostToolUseFailure",
    "start": "SubagentStart",
    "stop": "SubagentStop",
    "idle": "TeammateIdle",
    "pre": "PreToolUse",
    "post": "PostToolUse",
    "prompt": "UserPromptSubmit",
    "turn-end": "Stop",
    "api-error": "StopFailure",
    "notify": "Notification",
    "compact": "PostCompact",
    "session": "SessionStart",
    "session-end": "SessionEnd",
    "cap": "PostToolUse",
}
# a fixture agent's id, `a<name>-<16 hex>` as 2.1.322 writes them
WORKER: Final = "aworker-1-0123456789abcdef"
# a session's skill-file digest, as `inject.skill_changes` writes it (16 hex)
DIGEST: Final = "0123456789abcdef"


def run_id(n: int) -> str:
    """A synthetic run id in `--activate`'s format (`%Y%m%dT%H%M%S-<16 hex>`)."""
    return f"20260101T{n:06d}-{n:016x}"


def _git(env: Mapping[str, str], *args: object) -> str:
    """Git with the throwaway identity in env; its stdout, stripped."""
    return subprocess.run(
        [*GIT, *map(str, args)],
        env=dict(env),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@dataclasses.dataclass
class FixtureRoute:
    """A synthetic route: its directory, planning dir, marker, run and arguments.

    The directory is a repository's when built with repo; run is None for a marker
    without one.
    """

    name: str
    repo: Path
    plan: Path
    marker: Path
    run: str | None
    args: list[str]

    @property
    def key(self) -> str:
        """The monitor's route key."""
        return route_slug(str(self.plan))

    def run_key(self, run: str | None = None) -> str:
        """The monitor's key of run (default this route's run; None is `pre`)."""
        return f"{self.key}-{run or self.run or 'pre'}"


class Machine:
    """A synthetic machine under root: HOME, routes, registry entries and event logs.

    Every file the builder writes is in `written`; every name is `route-[a-f]`, a
    session `s<n>` or a fixture constant.
    """

    def __init__(self, root: Path) -> None:
        """An empty machine with HOME at root/home."""
        self.root: Path = root
        self.home: Path = root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.registry: Path = self.home / ".claude/dsp-routes"
        self.env: dict[str, str] = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C.UTF-8",
            **{k: v for k, v in os.environ.items() if k.startswith("COVERAGE_")},
        }
        self.routes: dict[str, FixtureRoute] = {}
        self.written: list[Path] = []
        self.live_route_key: str = ""
        self.idle_route_key: str = ""
        self.ended_run_key: str = ""

    def put(self, path: Path, text: str) -> Path:
        """Text written to path, which joins `written`."""
        if path not in self.written:
            self.written.append(path)
        return Sandbox.write(path, text)

    def fixture_route(
        self,
        name: str,
        *,
        repo: bool = True,
        run: str | None = "",
        upgraded: bool = False,
        under_home: bool = False,
    ) -> FixtureRoute:
        """A route at <root or HOME>/<name>, its planning dir `plan` and its marker.

        With repo it is a repository whose main has one commit, and the marker names
        it with `--repo`; else only its `.git` directory exists. run "" mints a new
        id; None writes a marker without one (3c70cb6's shape).
        """
        d = (self.home if under_home else self.root) / name
        plan = d / "plan"
        plan.mkdir(parents=True, exist_ok=True)
        if repo:
            _ = _git(self.env, "init", "-q", "-b", "main", d)
            _ = _git(self.env, "-C", d, "commit", "-q", "--allow-empty", "-m", "one")
        else:
            (d / ".git").mkdir(parents=True, exist_ok=True)
        args = [str(plan), "--phase", "1", "--main", "main"]
        if repo:
            args += ["--repo", str(d)]
        r = FixtureRoute(
            name,
            d,
            plan,
            d / ".git" / f"dsp-route-{route_slug(str(plan))}.json",
            run_id(len(self.routes) + 1) if run == "" else run,
            args,
        )
        self.routes[name] = r
        self.put_marker(r, upgraded=upgraded)
        return r

    def put_marker(self, route: FixtureRoute, *, upgraded: bool = False) -> None:
        """Route's marker written as `--activate` writes it, with its run if any."""
        data: dict[str, object] = {
            "args": route.args,
            "planning_dir": str(route.plan),
            "activated": time.time(),
            "ledger": {},
        }
        if route.run is not None:
            data["run"] = route.run
        if upgraded:
            data["run_upgraded"] = True
        _ = self.put(route.marker, json.dumps(data))

    @staticmethod
    def prev(route: FixtureRoute, run: str | None = None) -> dict[str, object]:
        """A `previous` item naming route (and run, default the route's)."""
        return {
            "marker": str(route.marker),
            "planning_dir": str(route.plan),
            "run": run or route.run,
        }

    def put_entry(
        self,
        session: str,
        route: FixtureRoute,
        *,
        previous: Iterable[dict[str, object]] = (),
        activated: float | None = None,
        legacy: bool = False,
    ) -> Path:
        """Session's registry entry for route; legacy writes 3c70cb6's four keys.

        A current entry also carries the route's run and arguments, `previous`,
        `skill_seen` and a one-key `skill_digests` map.
        """
        at = time.time() if activated is None else activated
        entry: dict[str, object] = {
            "marker": str(route.marker),
            "planning_dir": str(route.plan),
            "activated": at,
            "ledger": {},
        }
        if not legacy:
            entry |= {
                "run": route.run,
                "args": route.args,
                "previous": list(previous),
                "skill_seen": at,
                "skill_digests": {"SKILL.md": DIGEST},
            }
        return self.put(self.registry / f"{session}.json", json.dumps(entry) + "\n")

    def line(
        self,
        route: FixtureRoute,
        session: str,
        ev: str,
        at: float,
        **fields: object,
    ) -> dict[str, object]:
        """One §3.6 event line of route's run, as the recorder writes it."""
        from dsp_route import record

        if ev not in record.KINDS:
            msg = f"line: {ev} is no event kind"
            raise AssertionError(msg)
        return {
            "v": record.SCHEMA,
            "ts": round(at, 3),
            "session": session,
            "run": route.run,
            "planning_dir": str(route.plan),
            "marker": str(route.marker),
            "hook": FIXTURE_HOOKS[ev],
            "ev": ev,
            **fields,
        }

    def put_events(self, session: str, *lines: Mapping[str, object]) -> Path:
        """Lines appended to session's event log."""
        path = self.registry / "events" / f"{session}.jsonl"
        _ = self.put(path, path.read_text() if path.exists() else "")
        Sandbox.append(path, *map(jline, lines))
        return path

    def lane(self, route: FixtureRoute, plan_id: str, state: str) -> None:
        """A lane of route's repository in state (a `report.LANE_STATES` value).

        A queued lane has only its plan index row, which the caller writes.
        """
        if state == "queued":
            return
        r = route.repo
        sha = _git(
            self.env, "-C", r, "commit-tree", "-p", "main", "-m", plan_id, "main^{tree}"
        )
        _ = _git(self.env, "-C", r, "branch", plan_id, sha)
        lanes = route.plan / "lanes"
        _ = self.put(lanes / f"{plan_id}-checkpoint.md", f"Final SHA: {sha}\n")
        if state == "merged":
            _ = _git(self.env, "-C", r, "merge", "-q", "--no-ff", "-m", "m", plan_id)
        gates = {"red": "exit=1\n", "gating": "running\n", "ready": "exit=0\n"}
        if state in gates:
            text = f"sha={sha} dirty=0\n{gates[state]}"
            _ = self.put(lanes / f"{plan_id}-gate.log", text)


def _route_a(m: Machine, now: float) -> None:
    """The exec route: every lane state, a whole-wave edge, a worktree, a budget."""
    a = m.fixture_route("route-a", under_home=True)
    states = {
        "p1-01-x": ("merged", 1, "—"),
        "p1-02-x": ("red", 1, "—"),
        "p1-03-x": ("gating", 1, "—"),
        "p1-04-x": ("ready", 1, "—"),
        "p1-05-x": ("running", 1, "—"),
        "p1-06-x": ("queued", 1, "p1-01-x"),
        "p1-07-x": ("queued", 1, "p1-02-x"),
        "p1-08-x": ("queued", 2, "all of wave 1"),
    }
    for plan_id, (state, _, _) in states.items():
        m.lane(a, plan_id, state)
    _ = _git(m.env, "-C", a.repo, "worktree", "add", "-q", m.root / "wt-a", "p1-05-x")
    rows = "".join(f"| {p} | {w} | {d} |\n" for p, (_, w, d) in states.items())
    _ = m.put(
        a.plan / "plans/p1-00-index.md",
        f"# Phase 1 plans\n\n| Plan | Wave | Depends on |\n|---|---|---|\n{rows}",
    )
    budget = {
        "label": "phase 1",
        "estimate": 12.5,
        "phase": "1",
        "at": "2026-01-01T00:00:00Z",
        "session": "s1",
        "groups": 4,
    }
    _ = m.put(a.plan / "route-budget.json", json.dumps({"budgets": [budget]}))
    _ = m.put_entry("s1", a, activated=now - 600)
    _ = m.put_events(
        "s1",
        m.line(a, "s1", "dispatch", now - 300, tuid="t-a1", name="worker-1", bg=True),
        m.line(
            a,
            "s1",
            "launch",
            now - 299,
            tuid="t-a1",
            child=WORKER,
            mode="background",
            name="worker-1",
            model="model-x",
        ),
        m.line(a, "s1", "start", now - 298, agent=WORKER),
        m.line(a, "s1", "pre", now - 200, agent=WORKER, tool="Bash", tuid="t-a2"),
        m.line(a, "s1", "pre", now - 100, tool="Bash", tuid="t-a3"),
        m.line(a, "s1", "post", now - 99, tool="Bash", tuid="t-a3", ms=900),
    )
    m.live_route_key = a.key


def build_machine(root: Path) -> Machine:
    """The machine of AC-P1-4-33 under root, callable outside a TestCase.

    route-a an exec route (`_route_a`), session s1; route-b waiting on the user: an
    open `AskUserQuestion` (s2) and a permission prompt (s7); route-c blind (s3); s6
    moved from route-c to route-b, its log holding route-c lines; route-d a repository
    (s4); route-e ended, two runs (s5), its marker deleted; route-f idle, no event log
    (s8).
    """
    m = Machine(root)
    now = time.time()
    _route_a(m, now)
    b = m.fixture_route("route-b", repo=False)
    c = m.fixture_route("route-c", repo=False)
    _ = m.put_entry("s2", b, activated=now - 500)
    _ = m.put_events("s2", m.line(b, "s2", "pre", now - 60, tool="AskUserQuestion"))
    _ = m.put_entry("s7", b, activated=now - 400)
    _ = m.put_events(
        "s7", m.line(b, "s7", "notify", now - 30, type="permission_prompt")
    )
    _ = m.put_entry("s3", c, activated=now - 700)
    _ = m.put_events(
        "s3", m.line(c, "s3", "pre", now - 50, tool="Bash", gap=["tool_use_id"])
    )
    _ = m.put_entry("s6", b, previous=[m.prev(c)], activated=now - 450)
    _ = m.put_events(
        "s6",
        m.line(c, "s6", "post", now - 460, tool="Read", tuid="t-c1"),
        m.line(b, "s6", "post", now - 40, tool="Read", tuid="t-b1"),
    )
    d = m.fixture_route("route-d")
    _ = m.put_entry("s4", d, activated=now - 800)
    _ = m.put_events("s4", m.line(d, "s4", "turn-end", now - 70, bg_tasks=0))
    e = m.fixture_route("route-e", repo=False)
    old = run_id(50)
    _ = m.put_entry("s5", e, previous=[m.prev(e, old)], activated=now - 90_000)
    _ = m.put_events(
        "s5",
        m.line(e, "s5", "turn-end", now - 100_000, run=old),
        m.line(e, "s5", "turn-end", now - 95_000),
    )
    Sandbox.rm(e.marker)
    m.written.remove(e.marker)
    m.ended_run_key = e.run_key()
    f = m.fixture_route("route-f", repo=False)
    ago = -(dsp_monitor.IDLE_S + 3600)
    _ = m.put_entry("s8", f, activated=now + ago)
    last = f.marker.with_name(f"{f.marker.stem}.s8.last")
    _ = m.put(last, "")
    for path in (f.marker, last):
        Sandbox.touch(path, ago)
    m.idle_route_key = f.key
    return m


# --- transcript records, as the bash suite's jq one-liners wrote them


def human(offset: float) -> str:
    """A prompt the user typed, `offset` seconds from now."""
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": "go"},
        }
    )


def peer(offset: float) -> str:
    """A message another session sent, `offset` seconds from now."""
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "origin": {"kind": "peer"},
            "message": {
                "role": "user",
                "content": "Another Claude session sent a message: done",
            },
        }
    )


def sent(offset: float, tool_id: str, name: str) -> str:
    """An Agent call that dispatches name, `offset` seconds from now."""
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "message": {
                "id": tool_id,
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "Agent",
                        "input": {"name": name},
                    }
                ],
            },
        }
    )


def used(offset: float, request: str, tokens: int) -> str:
    """An assistant turn of request that used tokens input tokens."""
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "requestId": request,
            "message": {
                "id": request,
                "model": "claude-opus-5-5",
                "content": [],
                "usage": {"input_tokens": tokens, "output_tokens": 0},
            },
        }
    )


def call(
    tool_id: str, name: str, inp: Mapping[str, object], result: object
) -> list[str]:
    """A tool call and its result: two records."""
    return [
        jline(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": tool_id, "name": name, "input": inp}
                    ]
                },
            }
        ),
        jline(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result,
                        }
                    ]
                },
            }
        ),
    ]


def notice(task: str, status: str = "") -> str:
    """A task notification the agent received; a monitor's event has no status."""
    status_line = f"<status>{status}</status>\n" if status else ""
    prompt = (
        f"<task-notification>\n<task-id>{task}</task-id>\n{status_line}"
        "<event>x</event>\n</task-notification>"
    )
    return jline(
        {
            "type": "attachment",
            "attachment": {
                "type": "queued_command",
                "prompt": prompt,
                "origin": {"kind": "task-notification"},
            },
        }
    )


def crec(
    offset: float, request: str, tokens: int, cwd: str, entrypoint: str = "cli"
) -> str:
    """An assistant turn of request from cwd and entrypoint, for the usage report."""
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "requestId": request,
            "cwd": cwd,
            "entrypoint": entrypoint,
            "message": {
                "id": request,
                "model": "claude-opus-5-5",
                "content": [],
                "usage": {"input_tokens": tokens},
            },
        }
    )


def decision_index(settled: str, security: str = "", extra: str = "") -> str:
    """A decision index: one SETTLED row, a measured figure, dimensions and decisions.

    The requirement dimensions name the security owner given, or N/A; the decisions
    table holds D1 and extra.
    """
    dims = ["## Requirement dimensions", "| Dimension | Owner |", "|---|---|"]
    dims.extend(
        f"| {d} | D1 |"
        for d in (
            "Actors and workflows",
            "Data identity",
            "Ownership and round-trip",
            "Business rules",
            "State machines",
            "Integrations and events",
            "Validation and exceptions",
            "Background jobs",
        )
    )
    dims.append(
        f"| Security and privacy | {security or 'N/A: no accounts, local only'} |"
    )
    return (
        "# Phase 1\n## SETTLED — do not re-open\n### Import\n"
        "| # | Ruling | Source |\n|---|---|---|\n"
        f"{settled}\n"
        "### Measured numbers that bind any ruling\n| Figure | Source |\n|---|---|\n"
        "| 3 s | `src/a.ts:4` |\n\n"
        + "\n".join(dims)
        + "\n"
        + "\n## The decisions\n| # | Decision | Serves |\n|---|---|---|\n"
        "| D1 | x | Ask1 |\n"
        f"{extra}\n"
    )


def dispositions(rows: str) -> str:
    """A Dispositions table holding rows."""
    return (
        f"\n## Dispositions\n| Finding | Disposition | Basis |\n|---|---|---|\n{rows}\n"
    )
