# SPDX-License-Identifier: MIT
"""The event recorder: its line, its append under a lock, its cap and its retention.

Each case runs `record()` in a subprocess with the sandbox's environment, so the log
lands under the sandbox HOME, as a hook's call writes it.
"""

import concurrent.futures
import contextlib
import json
import os
import stat
import statistics
import subprocess
import time
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import cast

from typing_extensions import override

import support
from support import PY, SCRIPTS

# record() for each [event, entry, t0, decision] of the JSON list on stdin
RECORD = """import json, sys
sys.path.insert(0, sys.argv[1])
from dsp_route.record import record
for event, entry, t0, decision in json.load(sys.stdin):
    record(event, entry, t0, decision and (decision[0], decision[1]))"""

# argv: scripts, the writer's name, a line count: that many distinct post lines; prints
# how many the lock gave up on (the designed drop), counted where `_append` asks for it
WRITER = """import sys
sys.path.insert(0, sys.argv[1])
from dsp_route import record as r
locked, gave_up = r._locked, []
r._locked = lambda fd: locked(fd) or gave_up.append(fd) or False
for k in range(int(sys.argv[3])):
    r.record({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Read",
              "tool_use_id": f"{sys.argv[2]}-{k}"}, {"run": "r1"}, 1.0, None)
print(len(gave_up))"""

# argv: the log, a ready file: holds the log's flock until killed
HOLD = """import fcntl, os, pathlib, sys, time
log = pathlib.Path(sys.argv[1])
log.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
pathlib.Path(sys.argv[2]).write_text("held")
time.sleep(120)"""

# argv: scripts, the log; stdin: [event, entry]. Counts record()'s flock calls.
COUNT = """import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from dsp_route import record as r
calls = []
flock = r.fcntl.flock
def counted(*a):
    calls.append(a)
    return flock(*a)
r.fcntl.flock = counted
event, entry = json.load(sys.stdin)
r.record(event, entry, 1.0, None)
lines = pathlib.Path(sys.argv[2]).read_text().splitlines()
print(json.dumps({"attempts": len(calls), "lines": len(lines)}))"""

# the lock attempts a held log gets before its line is dropped: about 23 ms in all
LOCK_TRIES = 50
ENTRY: dict[str, object] = {
    "run": "r1",
    "planning_dir": "/p",
    "marker": "/r/dsp-route.json",
}
# free text of a payload that no line may carry
FREE = ("desc", "to", "error", "cwd")

Call = tuple[Mapping[str, object], Mapping[str, object], float, list[str] | None]


def event(hook: str, **fields: object) -> dict[str, object]:
    """A payload of hook for session s1."""
    return {"session_id": "s1", "hook_event_name": hook, **fields}


def post(tuid: str, agent: str | None = None) -> dict[str, object]:
    """A PostToolUse of Read, by agent (None: the lead)."""
    extra: dict[str, object] = {} if agent is None else {"agent_id": agent}
    return event("PostToolUse", tool_name="Read", tool_use_id=tuid, cwd="/w", **extra)


@contextlib.contextmanager
def held(env: Mapping[str, str], log: Path, ready: Path) -> Generator[None, None, None]:
    """Another process holds log's flock for the block."""
    proc = subprocess.Popen(
        [PY, "-c", HOLD, log, ready],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and proc.poll() is None:
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)
        if not ready.exists():
            msg = "the holder never took the lock"
            raise AssertionError(msg)
        yield
    finally:
        proc.kill()
        _ = proc.wait()
        ready.unlink(missing_ok=True)


class Recorder(support.Sandbox):
    """`record()` and its log, called as a hook calls it, under the sandbox HOME."""

    @property
    def events_dir(self) -> Path:
        """The sandbox's `~/.claude/dsp-routes/events`."""
        return self.HOME / ".claude/dsp-routes/events"

    @property
    def log(self) -> Path:
        """Session s1's log."""
        return self.events_dir / "s1.jsonl"

    @override
    def setUp(self) -> None:
        """Start each case with no log."""
        self.rm(self.events_dir)

    def rec(self, *calls: Call) -> None:
        """record() of each call, in one process; it prints nothing and exits 0."""
        r = self.run_([PY, "-c", RECORD, SCRIPTS], input=json.dumps(calls), merge=True)
        self.ok(
            "record() prints nothing and exits 0", (r.code, r.out) == (0, ""), r.out
        )

    def test_lock_attempts(self) -> None:
        """A held lock: exactly LOCK_TRIES attempts, then the line is dropped."""
        with held(self.env, self.log, self.T / "ready"):
            r = self.run_(
                [PY, "-c", COUNT, SCRIPTS, self.log],
                input=json.dumps([post("t1"), ENTRY]),
                merge=True,
            )
        got = cast("dict[str, object]", json.loads(r.out))
        self.ok(
            f"{got.get('attempts')} flock attempts, {got.get('lines')} lines",
            got == {"attempts": LOCK_TRIES, "lines": 0},
            r.out,
        )

    def test_line_cap(self) -> None:
        """A description is never recorded; an oversized line keeps the join keys."""
        from dsp_route import record  # the hook imports it lazily (TID253)

        big = event(
            "PreToolUse",
            tool_name="Agent",
            tool_use_id="t1",
            tool_input={"name": "n", "description": "d" * 100_000},
        )
        self.rec((big, ENTRY, 1.0, None))
        raw = self.log.read_bytes()
        line = self.events()[0]
        self.ok(
            f"a 100 KB description: {len(raw)} bytes, no desc, run kept",
            len(raw) <= record.LINE_MAX
            and "desc" not in line
            and "trunc" not in line
            and line.get("run") == "r1",
            line,
        )

        self.rm(self.events_dir)
        wide = {**ENTRY, "planning_dir": "p" * 5000, "marker": "m" * 5000}
        self.rec((event("Stop", cwd="c" * 5000), wide, 1.0, None))
        line = self.events()[0]
        self.ok(
            "oversized paths fall back to the joinable keys",
            set(line) == {"v", "ts", "session", "run", "hook", "ev", "trunc"},
            line,
        )

    def test_gaps_and_refusals(self) -> None:
        """A missing or unknown field is a gap; a payload with no ids is refused."""
        launched = event(
            "PostToolUse",
            tool_name="Agent",
            tool_use_id="t1",
            tool_response={"status": "async_launched", "agentID": "x"},
        )
        weird = event(
            "PostToolUse",
            tool_name="Agent",
            tool_use_id="t2",
            tool_response={"status": "weird", "agentId": "a1"},
        )
        self.rec((launched, ENTRY, 1.0, None), (weird, ENTRY, 2.0, None))
        lines = self.events()
        self.ok(
            "a renamed agentId is a gap",
            lines[0].get("ev") == "launch"
            and lines[0].get("gap") == ["tool_response.agentId"],
            lines[0],
        )
        self.ok(
            "an unknown status is a post with its value as a gap",
            lines[1].get("ev") == "post"
            and lines[1].get("gap") == ["tool_response.status=weird"],
            lines[1],
        )

        self.rm(self.events_dir)
        refused: list[Mapping[str, object]] = [
            {"hook_event_name": "Stop"},
            {"session_id": "s1"},
            event("Stop", session_id="../x"),
        ]
        self.rec(*((e, ENTRY, 1.0, None) for e in refused))
        self.ok(
            f"{len(refused)} payloads refused, no events dir",
            not self.events_dir.exists(),
        )

    def test_task_stop_target(self) -> None:
        """A TaskStop post keeps the name or id it stopped (128 chars); others none."""
        long = "w" * 200

        def stop(tuid: str, tool: str, task: str) -> dict[str, object]:
            return event(
                "PostToolUse",
                tool_name=tool,
                tool_use_id=tuid,
                tool_input={"task_id": task},
            )

        calls = [
            stop("t1", "TaskStop", "worker-1"),
            stop("t2", "TaskStop", long),
            stop("t3", "Bash", "worker-1"),
        ]
        self.rec(*((c, ENTRY, 1.0, None) for c in calls))
        got = [(x.get("target"), x.get("trunc")) for x in self.events()]
        want = [("worker-1", None), (long[: len("w" * 128)], True), (None, None)]
        self.ok(f"{len(calls)} posts: targets {got}", got == want, got)

    def test_parallel_writers(self) -> None:
        """40 processes x 200 lines on one log: none torn, each loss a lock give-up.

        A writer whose lock tries run out drops its line by design (LOCK_TRIES); on a
        starved CPU a few do (5-6 of 8000 measured on one loaded core). A line lost any
        other way, a line written twice, or more than 1% dropped, fails.
        """
        procs, lines = 40, 200
        writers = [
            subprocess.Popen(
                [PY, "-c", WRITER, SCRIPTS, f"w{i}", str(lines)],
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for i in range(procs)
        ]
        outs = [w.communicate(timeout=300)[0] for w in writers]
        codes = [w.returncode for w in writers]
        dropped = sum(int(o) for o in outs)
        written = torn = 0
        tuids: set[object] = set()
        for text in self.log.read_text().splitlines():
            try:
                tuids.add(cast("dict[str, object]", json.loads(text)).get("tuid"))
                written += 1
            except ValueError:
                torn += 1
        lost = procs * lines - len(tuids)
        self.ok(
            f"written {written}, torn {torn}, lost {lost}, dropped {dropped}",
            codes == [0] * procs
            and written == len(tuids)
            and torn == 0
            and lost == dropped
            and dropped <= procs * lines // 100,
            codes,
        )

    def test_cap_and_heartbeat(self) -> None:
        """Past CAP_BYTES: one cap line, one post per agent a minute, the rest kept."""
        from dsp_route import record  # the hook imports it lazily (TID253)

        start = record.CAP_BYTES - 100  # shorter than a post, so the first crosses it
        _ = self.write_bytes(self.log, b"")
        os.truncate(self.log, start)
        agent = {"agent_id": "a1", "agent_type": "t", "cwd": "/w"}
        self.rec(
            (post("t1", "a1"), ENTRY, 1.0, None),
            (post("t2", "a1"), ENTRY, 2.0, None),
            (post("t3", "a1"), ENTRY, 3.0, None),
            (event("SubagentStart", **agent), ENTRY, 4.0, None),
            (event("SubagentStop", **agent), ENTRY, 5.0, None),
            (event("TeammateIdle", teammate_name="n", **agent), ENTRY, 6.0, None),
        )
        stamp = self.events_dir / "s1.a1.hb"
        before = self._past_cap(start)
        self.touch(stamp, -61)
        self.rec((post("t4", "a1"), ENTRY, 7.0, None))
        after = self._past_cap(start)
        free = [k for e in after for k in FREE if k in e]
        self.ok(f"past the cap: free text {free}", not free, after)
        kinds = [e.get("ev") for e in before]
        self.ok(
            f"{kinds.count('cap')} cap line, {kinds.count('post')} posts, "
            f"{len(before)} lines",
            kinds == ["post", "cap", "post", "start", "stop", "idle"],
            before,
        )
        self.ok(
            f"a 61 s old heartbeat lets the next post in ({len(after)} lines)",
            [e.get("tuid") for e in after if e.get("ev") == "post"]
            == ["t1", "t2", "t4"],
            after,
        )

    def _past_cap(self, start: int) -> list[dict[str, object]]:
        """The lines written from byte start of the sparse log."""
        with self.log.open("rb") as f:
            _ = f.seek(start)
            data = f.read()
        return [
            cast("dict[str, object]", json.loads(t)) for t in data.splitlines() if t
        ]

    def test_sweep(self) -> None:
        """`sweep()` removes old logs and stamps, once a day, and nothing else."""
        old = time.time() - 15 * 86400
        for name in ("old.jsonl", "old.hb", "young.jsonl", "x.txt"):
            _ = self.write(self.events_dir / name, "{}\n")
        for name in ("old.jsonl", "old.hb", "x.txt"):
            os.utime(self.events_dir / name, (old, old))
        young = time.time() - 13 * 86400
        os.utime(self.events_dir / "young.jsonl", (young, young))
        sweep = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from dsp_route.record import sweep; sweep()"
        )
        r = self.run_([PY, "-c", sweep, SCRIPTS], merge=True)
        left = sorted(p.name for p in self.events_dir.iterdir())
        self.ok(
            f"swept to {len(left)} files",
            r.code == 0 and left == [".swept", "x.txt", "young.jsonl"],
            (r.out, left),
        )
        _ = self.write(self.events_dir / "late.jsonl", "{}\n")
        os.utime(self.events_dir / "late.jsonl", (old, old))
        _ = self.run_([PY, "-c", sweep, SCRIPTS])
        self.ok(
            "a second sweep within a day keeps a new old file",
            (self.events_dir / "late.jsonl").exists(),
        )
        self.touch(self.events_dir / ".swept", -25 * 3600)
        _ = self.run_([PY, "-c", sweep, SCRIPTS])
        self.ok(
            "a day later it is swept",
            not (self.events_dir / "late.jsonl").exists(),
        )


MON = {"DSP_MONITOR": "1"}
# how much longer a hook call may take with the log's lock held: about 10x the
# measured worst case
HANG_S = 0.25
SENTINEL = "sentinel-5f1e9c"
A1 = {"agent_id": "a1", "agent_type": "general-purpose"}
HELPER = {
    "name": "helper",
    "description": "look around",
    "subagent_type": "general-purpose",
    "run_in_background": "true",
}
USAGE = {
    "input_tokens": 1,
    "output_tokens": 2,
    "cache_creation_input_tokens": 3,
    "cache_read_input_tokens": 4,
}


def lead(hook: str, **fields: object) -> dict[str, object]:
    """A payload of hook for session s1, as the lead's hook receives it."""
    return {"session_id": "s1", "hook_event_name": hook, "cwd": "/w", **fields}


def kinds() -> list[tuple[dict[str, object], str, dict[str, object]]]:
    """A payload per kind of line, its kind and fields the line must hold."""
    launched = {"status": "async_launched", "agentId": "a2"}
    spawned = {
        "status": "teammate_spawned",
        "agentId": "ahelper-1",
        "name": "helper",
        "team_name": "t",
        "agent_type": "general-purpose",
        "resolvedModel": "m1",
    }
    done = {
        "status": "completed",
        "agentId": "a3",
        "resolvedModel": "m1",
        "totalDurationMs": 1200,
        "totalToolUseCount": 4,
        "totalTokens": 900,
        "usage": {**USAGE, "service_tier": "standard"},
    }
    bg = [{"id": "1", "status": "running"}, {"id": "2", "status": "completed"}]
    return [
        (
            lead("PreToolUse", tool_name="Agent", tool_use_id="d1", tool_input=HELPER),
            "dispatch",
            {"tuid": "d1", "name": "helper", "bg": True},
        ),
        (
            lead(
                "PostToolUse",
                tool_name="Agent",
                tool_use_id="d1",
                tool_input=HELPER,
                tool_response=spawned,
            ),
            "launch",
            {
                "tuid": "d1",
                "child": "ahelper-1",
                "mode": "teammate",
                "name": "helper",
                "team": "t",
                "child_type": "general-purpose",
                "model": "m1",
            },
        ),
        (
            lead(
                "PostToolUse",
                tool_name="Agent",
                tool_use_id="d2",
                tool_input={"name": "bg"},
                tool_response=launched,
            ),
            "launch",
            {"tuid": "d2", "child": "a2", "mode": "background", "name": "bg"},
        ),
        (
            lead(
                "PostToolUse",
                tool_name="Agent",
                tool_use_id="d3",
                tool_input={"name": "fg"},
                tool_response=done,
            ),
            "return",
            {
                "tuid": "d3",
                "child": "a3",
                "name": "fg",
                "model": "m1",
                "ms": 1200,
                "tools": 4,
                "final_tokens": 900,
                "usage": USAGE,
            },
        ),
        (
            lead(
                "PostToolUseFailure",
                tool_name="Agent",
                tool_use_id="d4",
                tool_input={"name": "bad"},
                error="boom\nat line 2",
                is_interrupt=False,
                duration_ms=7,
            ),
            "failed",
            {"tuid": "d4", "name": "bad", "interrupt": False, "ms": 7},
        ),
        (
            lead("SubagentStart", **A1),
            "start",
            {"agent": "a1", "atype": A1["agent_type"]},
        ),
        (lead("SubagentStop", **A1), "stop", {"agent": "a1"}),
        (
            lead("TeammateIdle", agent_id="a1", teammate_name="helper", team_name="t"),
            "idle",
            {"agent": "a1", "teammate": "helper", "team": "t"},
        ),
        (
            lead(
                "PreToolUse",
                tool_name="Bash",
                tool_use_id="b1",
                tool_input={"command": "ls", "description": "list"},
            ),
            "pre",
            {"tool": "Bash", "tuid": "b1"},
        ),
        (
            lead(
                "PreToolUse",
                tool_name="SendMessage",
                tool_use_id="m1",
                tool_input={"to": "helper", "message": "hi"},
            ),
            "pre",
            {"tool": "SendMessage", "tuid": "m1"},
        ),
        (
            lead(
                "PreToolUse",
                tool_name="mcp__notes__create_note",
                tool_use_id="n1",
                tool_input={},
            ),
            "pre",
            {"tool": "mcp__notes__create_note", "tuid": "n1"},
        ),
        (
            lead("PostToolUse", tool_name="Read", tool_use_id="r1", duration_ms=3),
            "post",
            {"tool": "Read", "tuid": "r1", "ms": 3},
        ),
        (
            lead("UserPromptSubmit", prompt="<agent-message from='x'>done"),
            "prompt",
            {"from": "return"},
        ),
        (lead("UserPromptSubmit", prompt="go on"), "prompt", {"from": "user"}),
        (lead("Stop", background_tasks=bg), "turn-end", {"bg_tasks": 1}),
        (lead("StopFailure", error="rate_limit"), "api-error", {}),
        (
            lead("Notification", notification_type="idle_prompt", message="m"),
            "notify",
            {"type": "idle_prompt"},
        ),
        (lead("PostCompact", trigger="auto"), "compact", {"trigger": "auto"}),
        (lead("SessionStart", source="compact"), "session", {"source": "compact"}),
        (lead("SessionEnd", reason="clear"), "session-end", {"reason": "clear"}),
    ]


class Folded(support.Route):
    """The recorder through `route_state.py --hook` on s1's route, the switch on.

    The route's phase 1 has a budget the user answered, so `exec-p1-01-a` is allowed and
    `exec-p2-01-a` is held as another phase's (F74).
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Record phase 1's budget, answered."""
        super().setUpClass()
        at = support.ts(-60)
        budget = {
            "label": "w1",
            "estimate": 10,
            "phase": "1",
            "at": at,
            "session": "s1",
            "answered": at,
        }
        _ = cls.write(cls.P / "route-budget.json", json.dumps({"budgets": [budget]}))

    @property
    def events_dir(self) -> Path:
        """The sandbox's `~/.claude/dsp-routes/events`."""
        return self.HOME / ".claude/dsp-routes/events"

    @property
    def log(self) -> Path:
        """Session s1's log."""
        return self.events_dir / "s1.jsonl"

    @override
    def setUp(self) -> None:
        """Start each case with no log."""
        self.rm(self.events_dir)

    def run_hook(
        self, payload: Mapping[str, object], *, on: bool = True, timeout: float = 30
    ) -> support.Result:
        """`route_state.py --hook` on payload, the switch on (or unset)."""
        return self.py(
            support.RS,
            "--hook",
            input=json.dumps(payload) + "\n",
            env=MON if on else {},
            timeout=timeout,
        )

    def held_calls(self) -> list[tuple[str, dict[str, object], str]]:
        """The three held calls: a name, the payload and the hook's answer."""
        gate_log = {"file_path": f"{self.P}/lanes/x-gate.log", "content": "exit=0\n"}
        return [
            (
                "gate-log write",
                lead(
                    "PreToolUse",
                    tool_name="Write",
                    tool_use_id="w1",
                    tool_input=gate_log,
                ),
                "deny:a gate log holds only what the gate printed",
            ),
            (
                "gh pr merge",
                lead(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="g1",
                    tool_input={"command": "gh pr merge 1"},
                ),
                "ask:F81",
            ),
            (
                "another phase's exec- dispatch",
                lead(
                    "PreToolUse",
                    tool_name="Agent",
                    tool_use_id="e2",
                    tool_input={"name": "exec-p2-01-a"},
                ),
                "deny:names another phase",
            ),
        ]

    @contextlib.contextmanager
    def blocked(self, kind: str) -> Generator[None, None, None]:
        """The log blocked for the block: events a file, the log a FIFO, or held."""
        if kind == "file":
            _ = self.write(self.events_dir, "")
        elif kind == "fifo":
            self.events_dir.mkdir(parents=True)
            os.mkfifo(self.log)
        try:
            with contextlib.ExitStack() as stack:
                if kind == "lock":
                    stack.enter_context(held(self.env, self.log, self.T / "ready"))
                yield
        finally:
            self.rm(self.events_dir)

    def test_decision_output_unchanged(self) -> None:
        """A deny or ask prints the same, the log raising, blocked or held."""
        calls = self.held_calls()
        diffs: list[tuple[str, str, str]] = []
        for name, payload, want in calls:
            off = self.run_hook(payload, on=False, timeout=10)
            self.ok(
                f"{name}, switch off: {want}",
                support.hook_matches(want, off.out),
                off.out,
            )
            for kind in ("file", "fifo", "lock"):
                with self.blocked(kind):
                    on = self.run_hook(payload, timeout=10)
                if (on.code, on.out) != (off.code, off.out):
                    diffs.append((name, kind, on.out))
        self.ok(
            f"{len(calls) * 3} blocked runs print as the switched-off ones",
            not diffs,
            diffs,
        )

    def test_hang_ceiling(self) -> None:
        """A held lock adds at most HANG_S to a routed hook call."""
        payload = lead("PostToolUse", tool_name="Read", tool_use_id="r1")
        times: list[float] = []
        for _ in range(5):
            self.unthrottle()
            start = time.monotonic()
            _ = self.run_hook(payload)
            times.append(time.monotonic() - start)
        median = statistics.median(times)
        with held(self.env, self.log, self.T / "ready"):
            self.unthrottle()
            start = time.monotonic()
            _ = self.run_hook(payload)
            took = time.monotonic() - start
        self.ok(
            f"held {took:.3f} s, unheld median {median:.3f} s",
            took - median <= HANG_S,
            times,
        )

    def test_decisions_recorded(self) -> None:
        """A held call's line has its decision and hold; an allowed one has neither."""
        allowed = [
            lead(
                "PreToolUse",
                tool_name="Agent",
                tool_use_id="e1",
                tool_input={"name": "exec-p1-01-a"},
            ),
            lead(
                "PreToolUse",
                tool_name="Agent",
                tool_use_id="p1",
                tool_input={"name": "plan-p1-01"},
            ),
        ]
        outs = [self.run_hook(p).out for _, p, _ in self.held_calls()]
        outs += [self.run_hook(p).out for p in allowed]
        by = {e.get("tuid"): e for e in self.events()}
        want = {
            "w1": ("pre", "deny", "F97"),
            "g1": ("pre", "ask", "F81"),
            "e2": ("dispatch", "deny", "F74"),
        }
        got = {
            t: (
                by.get(t, {}).get("ev"),
                by.get(t, {}).get("decision"),
                by.get(t, {}).get("hold"),
            )
            for t in want
        }
        self.ok(
            f"{len(want)} held calls recorded with their holds",
            got == want,
            (got, outs),
        )
        free = [by.get(t) for t in ("e1", "p1")]
        self.ok(
            f"{len(free)} allowed dispatches carry no decision",
            all(
                e is not None
                and e.get("ev") == "dispatch"
                and "decision" not in e
                and "hold" not in e
                for e in free
            ),
            (free, outs),
        )

    def test_every_kind(self) -> None:
        """Each kind's line through the hook: its fields, the common ones, the modes."""
        table = kinds()
        for payload, _, _ in table:
            self.unthrottle()
            _ = self.run_hook(payload)
        lines = self.events()
        entry = self.entry()
        self.ok(
            f"{len(lines)} lines for {len(table)} events",
            len(lines) == len(table),
            lines,
        )
        wrong: list[dict[str, object]] = []
        for (payload, kind, fields), line in zip(table, lines, strict=False):
            common = (
                line.get("v") == 1
                and line.get("run") == entry.get("run")
                and line.get("planning_dir") == entry["planning_dir"]
                and line.get("marker") == entry["marker"]
                and ("agent" in line) == ("agent_id" in payload)
            )
            if (
                not common
                or line.get("ev") != kind
                or any(line.get(k) != v for k, v in fields.items())
                or any(k in line for k in FREE)
            ):
                wrong.append(line)
        self.ok(
            f"{len(lines) - len(wrong)} of {len(lines)} lines as their kind",
            not wrong,
            wrong,
        )
        modes = (
            stat.S_IMODE(self.events_dir.stat().st_mode),
            stat.S_IMODE(self.log.stat().st_mode),
        )
        self.ok(
            "events 0700, the log 0600",
            modes == (0o700, 0o600),
            [oct(m) for m in modes],
        )

        stamps = self.stamps()
        outs = [
            self.run_hook(lead(h)).out for h in ("Stop", "StopFailure", "SessionEnd")
        ]
        self.ok(
            f"lead Stop, StopFailure, SessionEnd: silent, {len(stamps)} stamps kept",
            outs == ["", "", ""] and self.stamps() == stamps and stamps,
            (outs, stamps, self.stamps()),
        )

    def stamps(self) -> set[tuple[str, int]]:
        """The hook's `.last` and `.checked` stamps of s1, by name and mtime."""
        reg = self.HOME / ".claude/dsp-routes"
        found = [*self.MK(self.R).parent.glob("*.s1.last"), *reg.glob("s1.*.checked")]
        return {(p.name, p.stat().st_mtime_ns) for p in found}

    def test_nothing_private(self) -> None:
        """No prompt, command, message, output or transcript path reaches the log."""
        s = SENTINEL
        payloads = [
            lead("UserPromptSubmit", prompt=s),
            lead(
                "PreToolUse",
                tool_name="Bash",
                tool_use_id="b1",
                tool_input={"command": f"echo {s}"},
            ),
            lead(
                "PreToolUse",
                tool_name="Agent",
                tool_use_id="d1",
                tool_input={"name": "helper", "prompt": s},
            ),
            lead(
                "PreToolUse",
                tool_name="SendMessage",
                tool_use_id="m1",
                tool_input={"to": "helper", "message": s},
            ),
            lead(
                "PostToolUse",
                tool_name="Read",
                tool_use_id="r1",
                tool_response={"content": s},
            ),
            lead("Stop", last_assistant_message=s),
            lead("PostCompact", trigger="auto", compact_summary=s),
        ]
        for p in payloads:
            self.unthrottle()
            _ = self.run_hook({**p, "transcript_path": s})
        data = self.log.read_bytes()
        hits = data.count(s.encode())
        self.ok(
            f"{len(data.splitlines())} lines, {hits} sentinel hits",
            len(data.splitlines()) == len(payloads) and hits == 0,
            data[:2000],
        )

    def test_parallel_hooks(self) -> None:
        """8 parallel streams of 25 hook calls: every one recorded, none torn."""
        sent = {f"t{i}-{k}" for i in range(8) for k in range(25)}

        def stream(i: int) -> None:
            for k in range(25):
                _ = self.run_hook(lead("Notification", notification_type=f"t{i}-{k}"))

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            for f in [pool.submit(stream, i) for i in range(8)]:
                f.result()
        written = torn = 0
        types: set[object] = set()
        for text in self.log.read_text().splitlines():
            try:
                types.add(cast("dict[str, object]", json.loads(text)).get("type"))
                written += 1
            except ValueError:
                torn += 1
        lost = len(sent) - len(types & sent)
        self.ok(
            f"written {written}, torn {torn}, lost {lost}",
            types == sent and torn == 0 and written == len(sent),
        )

    def scan(self) -> dict[Path, int]:
        """Each path under HOME and P, by its mtime."""
        found: dict[Path, int] = {}
        for root in (self.HOME, self.P):
            for p in (root, *root.rglob("*")):
                found[p] = p.lstat().st_mtime_ns
        return found

    def test_retention(self) -> None:
        """SubagentStart sweeps old logs once a day; nothing else deletes."""
        d = self.events_dir
        old, young = time.time() - 15 * 86400, time.time() - 13 * 86400

        def plant(name: str, t: float) -> None:
            _ = self.write(d / name, "{}\n")
            os.utime(d / name, (t, t))

        for name, t in (("old.jsonl", old), ("old.hb", old), ("young.jsonl", young)):
            plant(name, t)
        start = lead("SubagentStart", **A1)
        changed: set[Path] = set()
        scanned = 0

        def started() -> None:
            nonlocal scanned
            before = self.scan()
            _ = self.run_hook(start)
            after = self.scan()
            scanned += len(after)
            changed.update(
                p for p in before.keys() | after.keys() if before.get(p) != after.get(p)
            )

        started()
        left = sorted(p.name for p in d.iterdir())
        self.ok(
            "a SubagentStart removes the two old files",
            left == [".swept", "s1.jsonl", "young.jsonl"],
            left,
        )
        plant("late.jsonl", old)
        started()
        self.ok(
            "a second within a day keeps a new old file", (d / "late.jsonl").exists()
        )
        self.touch(d / ".swept", -25 * 3600)
        started()
        self.ok("a day later it is swept", not (d / "late.jsonl").exists())
        outside = sorted(str(p) for p in changed if p != d and d not in p.parents)
        self.ok(
            f"scanned {scanned} paths: {len(changed)} changed, all under events/",
            changed and not outside,
            outside,
        )

        plant("late.jsonl", old)
        self.touch(d / ".swept", -25 * 3600)
        others = [
            lead(
                "PreToolUse",
                tool_name="Bash",
                tool_use_id="b1",
                tool_input={"command": "ls"},
            ),
            lead("PostToolUse", tool_name="Read", tool_use_id="r1"),
            lead("Stop"),
            lead("SessionEnd", reason="clear"),
        ]
        for p in others:
            _ = self.run_hook(p)
        self.ok(
            f"{len(others)} other events delete nothing",
            (d / "late.jsonl").exists(),
        )
