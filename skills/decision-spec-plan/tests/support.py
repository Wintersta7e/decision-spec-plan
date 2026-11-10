"""Fixtures and helpers shared by the hook and checker tests.

Every test runs the scripts as the hooks run them: a subprocess, its environment built from
scratch (PATH, a throwaway HOME, no system git config), so no `CLAUDECODE`, `CLAUDE_*` session or
real registry reaches it unless a case sets it. Each check is a subTest named by what it checks, so
a failure names the check and the rest of the method still runs.
"""

import datetime
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
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PLUGIN = TESTS.parent
SCRIPTS = PLUGIN / "scripts"
RS = SCRIPTS / "route_state.py"
GUARD = SCRIPTS / "push_guard.py"
PY = sys.executable
sys.path.insert(0, str(SCRIPTS))  # the modules some tests import
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def jline(obj):
    """One JSON record as `jq -nc` writes it."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def jstr(text):
    """A string as `jq -Rs . <<<"$text"` quotes it: the here-string adds a newline."""
    return json.dumps(text + "\n", ensure_ascii=False)


def ts(offset):
    """An ISO timestamp `offset` seconds from now, in the transcripts' UTC form."""
    t = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=int(offset))
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bracket(p, i):
    """The end of the bracket expression that opens at p[i]."""
    j = i + 1
    if p[j : j + 1] == "^":
        j += 1
    if p[j : j + 1] == "]":
        j += 1
    return p.index("]", j)


def _posix(p, basic):
    """A grep pattern (basic or extended) as a Python regex."""
    out, i = [], 0
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


def grep(text, pattern, *, E=False, F=False, x=False, count=False):
    """Whether `grep -q` finds pattern in text as `<<<"$text"` feeds it (the number of matching
    lines with count): basic regex by default, -E, -F, -x."""
    lines = text.split("\n")
    if F:

        def hit(line):
            return line == pattern if x else pattern in line

    else:
        rx = re.compile(_posix(pattern, basic=not E))

        def hit(line):
            return bool(rx.fullmatch(line) if x else rx.search(line))

    n = sum(1 for line in lines if hit(line))
    return n if count else n > 0


def grep_file(path, pattern, **kw):
    """grep over a file's lines."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return grep(text.removesuffix("\n"), pattern, **kw)


class Result:
    """A finished command: code, and out as `$( … )` captures it (trailing newlines cut)."""

    def __init__(self, proc):
        self.code = proc.returncode
        self.out = proc.stdout.rstrip("\n")


def ev(event, session, extra=""):
    """A hook event as the bash suite spelled it, field for field."""
    tail = f",{extra}" if extra else ""
    return (
        f'{{"hook_event_name":"{event}","session_id":"{session}","cwd":"/tmp"{tail}}}'
    )


def hook_matches(want, out):
    """Whether the hook's output meets want: silent | report | delta | /regex/ | deny:regex |
    ask:regex, the regexes read against the context or the permission reason."""
    if want == "silent":
        return out == ""
    try:
        spec = json.loads(out)["hookSpecificOutput"]
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(spec, dict):
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


def bash_q(text):
    """`printf %q` of text, as bash quotes it."""
    return subprocess.run(
        ["bash", "-c", 'printf %q "$1"', "_", text],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class Sandbox(unittest.TestCase):
    """A throwaway directory T with HOME under it. With `no_hooks`, git's global core.hooksPath
    names a directory with no hooks: --activate then installs no pre-push hook, and the command
    guard's own checks are what the tests see."""

    no_hooks = True
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="dsp-test-")
        cls.T = Path(cls._tmp.name).resolve()
        cls.HOME = cls.T / "home"
        cls.HOME.mkdir()
        cls.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(cls.HOME),
            "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C.UTF-8",
        }
        if cls.no_hooks:
            cls.git("config", "--global", "core.hooksPath", f"{cls.T}/no-hooks")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # --- running things

    @classmethod
    def run_(
        cls,
        argv,
        *,
        input=None,
        env=None,
        unset=(),
        cwd=None,
        merge=False,
        memory=None,
        timeout=None,
    ):
        """argv run in the sandbox's environment plus env, less unset; stderr merged into out
        with merge, else left out; memory caps the address space in bytes."""
        full = {**cls.env, **(env or {})}
        for name in unset:
            full.pop(name, None)

        def cap():
            if memory:
                resource.setrlimit(resource.RLIMIT_AS, (memory, memory))

        proc = subprocess.run(
            [str(a) for a in argv],
            input=input,
            env=full,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge else subprocess.DEVNULL,
            text=True,
            errors="replace",
            preexec_fn=cap if memory else None,
            timeout=timeout,
            check=False,
        )
        return Result(proc)

    @classmethod
    def py(cls, script, *args, session=None, **kw):
        """A script of the plugin run with python3; session sets CLAUDE_CODE_SESSION_ID."""
        env = dict(kw.pop("env", None) or {})
        if session is not None:
            env["CLAUDE_CODE_SESSION_ID"] = session
        path = script if isinstance(script, Path) else SCRIPTS / script
        return cls.run_([PY, path, *args], env=env, **kw)

    @classmethod
    def git(cls, *args, check=True, **kw):
        """git with the throwaway identity; its stdout, or the Result without check."""
        r = cls.run_([*GIT, *args], **kw)
        if check and r.code != 0:
            raise AssertionError(f"git {' '.join(map(str, args))} failed: {r.out}")
        return r.out if check else r

    @classmethod
    def rev(cls, repo, ref="HEAD"):
        return cls.git("-C", repo, "rev-parse", ref)

    @classmethod
    def init_repo(cls, path, branch="main", commits=("one",)):
        cls.git("init", "-q", "-b", branch, path)
        for m in commits:
            cls.git("-C", path, "commit", "-q", "--allow-empty", "-m", m)
        return Path(path)

    @staticmethod
    def write(path, text, mode="w"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode, encoding="utf-8", newline="") as f:
            f.write(text)
        return path

    @staticmethod
    def write_bytes(path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    @staticmethod
    def append(path, *lines):
        """Records appended to a transcript, one per line."""
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in lines))

    @staticmethod
    def touch(path, offset=0):
        """A file's mtime set `offset` seconds from now (created when missing)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        t = datetime.datetime.now().timestamp() + offset
        os.utime(path, (t, t))

    @staticmethod
    def chmod_x(*paths):
        for p in paths:
            os.chmod(p, os.stat(p).st_mode | 0o111)

    @staticmethod
    def rm(*paths):
        for p in paths:
            p = Path(p)
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)

    # --- checks

    def ok(self, msg, cond, detail=""):
        """One check of the suite: a subTest named msg that holds cond."""
        with self.subTest(msg):
            self.assertTrue(cond, f"{msg}\n{detail}"[:4000])

    def guard(self, want, cwd, command, agent=None):
        """push_guard.py on a Bash call of command from cwd (by agent, if given) exits want: an
        exit code, or "ask" for exit 0 asking the user. An exit 0 must print nothing."""
        event = {"tool_input": {"command": command}, "cwd": str(cwd)}
        if agent:
            event["agent_id"] = agent
        r = self.py(GUARD, input=json.dumps(event), merge=True)
        got = r.code
        if want == "ask":
            try:
                decision = json.loads(r.out)["hookSpecificOutput"]["permissionDecision"]
            except (ValueError, KeyError, TypeError):
                decision = None
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

    def gmsg(self, cwd, command):
        """push_guard.py's output on command from cwd."""
        stdin = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
        return self.py(GUARD, input=stdin, merge=True).out

    last = ""

    def hook(self, want, event, rs=RS):
        """`route_state.py --hook` on event meets want (see hook_matches)."""
        out = self.py(rs, "--hook", input=event + "\n", merge=True).out
        self.last = out
        self.ok(f"hook  {want}  {event}", hook_matches(want, out), out[:1500])
        return out

    def hook_out(self, event, rs=RS):
        return self.py(rs, "--hook", input=event + "\n", merge=True)

    def stophook(self, want, rx, event):
        """`route_state.py --hook` on a stop event exits want, rx found (grep -E) in its output."""
        r = self.hook_out(event)
        self.ok(
            f"stop {want}  {event}",
            r.code == want and grep(r.out, rx, E=True),
            f"got {r.code}: {r.out[:600]}",
        )


class Route(Sandbox):
    """The suite's main fixture: repository R (main two commits, feature one behind, worktree wt
    on feature), its planning dir P, and with `activate` a route of session s1 on it."""

    activate = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.R = cls.init_repo(cls.T / "repo", commits=("one", "two"))
        cls.git("-C", cls.R, "branch", "feature", "HEAD~1")
        cls.WT = cls.T / "wt"
        cls.git("-C", cls.R, "worktree", "add", "-q", cls.WT, "feature")
        cls.P = cls.R / ".plan"
        for d in ("lanes", "plans", "decisions/phase1", "spec"):
            (cls.P / d).mkdir(parents=True)
        cls.MAIN = cls.rev(cls.R, "main")
        cls.LEAD = cls.HOME / ".claude/projects/p/s1.jsonl"
        if cls.activate:
            cls.activate_route()

    @classmethod
    def activate_route(cls, *extra, session="s1", phase="1"):
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

    @staticmethod
    def MK(repo, plan=None):
        """The marker of the route whose planning dir is plan (default <repo>/.plan)."""
        real = os.path.realpath(plan or Path(repo) / ".plan")
        digest = hashlib.sha1(real.encode()).hexdigest()[:10]
        return Path(repo) / ".git" / f"dsp-route-{digest}.json"

    @classmethod
    def marker(cls, repo=None, plan=None):
        return json.loads(cls.MK(repo or cls.R, plan).read_text())

    @classmethod
    def budgets(cls, plan=None):
        """The budgets `route_state.py --budget` recorded in the route's planning dir."""
        path = Path(plan or cls.P) / "route-budget.json"
        return json.loads(path.read_text())["budgets"] if path.exists() else []

    @classmethod
    def set_marker(cls, data, repo=None, plan=None):
        cls.MK(repo or cls.R, plan).write_text(json.dumps(data))

    @classmethod
    def edit_marker(cls, fn, repo=None):
        m = cls.marker(repo)
        fn(m)
        cls.set_marker(m, repo)

    def unthrottle(self):
        for f in (self.HOME / ".claude/dsp-routes").glob("*.checked"):
            f.unlink()


# --- transcript records, as the bash suite's jq one-liners wrote them


def human(offset):
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": "go"},
        }
    )


def peer(offset):
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


def sent(offset, tool_id, name):
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


def used(offset, request, tokens):
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


def call(tool_id, name, inp, result):
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


def notice(task, status=""):
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


def crec(offset, request, tokens, cwd, entrypoint="cli"):
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


def decision_index(settled, security="", extra=""):
    """A decision index: one SETTLED row, a measured figure, the requirement dimensions (the
    security owner given, or N/A) and the decisions table with D1 and extra."""
    dims = ["## Requirement dimensions", "| Dimension | Owner |", "|---|---|"]
    for d in (
        "Actors and workflows",
        "Data identity",
        "Ownership and round-trip",
        "Business rules",
        "State machines",
        "Integrations and events",
        "Validation and exceptions",
        "Background jobs",
    ):
        dims.append(f"| {d} | D1 |")
    dims.append(
        f"| Security and privacy | {security or 'N/A: no accounts, local only'} |"
    )
    return (
        "# Phase 1\n## SETTLED — do not re-open\n### Import\n| # | Ruling | Source |\n|---|---|---|\n"
        f"{settled}\n"
        "### Measured numbers that bind any ruling\n| Figure | Source |\n|---|---|\n"
        "| 3 s | `src/a.ts:4` |\n\n"
        + "\n".join(dims)
        + "\n"
        + "\n## The decisions\n| # | Decision | Serves |\n|---|---|---|\n| D1 | x | Ask1 |\n"
        f"{extra}\n"
    )


def dispositions(rows):
    return (
        f"\n## Dispositions\n| Finding | Disposition | Basis |\n|---|---|---|\n{rows}\n"
    )
