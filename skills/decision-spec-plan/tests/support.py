# SPDX-License-Identifier: MIT
"""Fixtures and helpers shared by the hook and checker tests.

Every test runs the scripts as the hooks run them: a subprocess, its environment built
from scratch (PATH, a throwaway HOME, no system git config), so no `CLAUDECODE`,
`CLAUDE_*` session or real registry reaches it unless a case sets it. Each check is a
subTest named by what it checks, so a failure names the check and the rest of the method
still runs.
"""

import datetime as dt
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import (
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
    def git_shim(cls, root: Path, sleep: float = 0) -> tuple[dict[str, str], Path]:
        """A logging git at root/git: the env that puts it first on PATH, and its log.

        The scripts resolve git by `shutil.which`, so the shim sees every spawn they
        make. Before git runs it appends one line per spawn to root/git.log:
        `<epoch ns> <args>`, the first field `date +%s%N` and the rest `$*`. A count is
        the number of lines; a time stamp is `int(line.split(" ", 1)[0])`. With sleep,
        it waits that many seconds before running git.
        """
        real = shutil.which("git", path=cls.env["PATH"])
        if real is None:
            msg = "git_shim: no git on PATH"
            raise AssertionError(msg)
        log = root / "git.log"
        wait = f"sleep {sleep}\n" if sleep else ""
        shim = cls.write(
            root / "git",
            "#!/bin/sh\n"
            f"printf '%s %s\\n' \"$(date +%s%N)\" \"$*\" >> '{log}'\n"
            f"{wait}exec '{real}' \"$@\"\n",
        )
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
