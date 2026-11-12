# SPDX-License-Identifier: MIT
"""The event recorder: its line, its append under a lock, its cap and its retention.

Each case runs `record()` in a subprocess with the sandbox's environment, so the log
lands under the sandbox HOME, as a hook's call writes it.
"""

import contextlib
import json
import os
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

# argv: scripts, the writer's name, a line count: that many distinct post lines
WRITER = """import sys
sys.path.insert(0, sys.argv[1])
from dsp_route.record import record
for k in range(int(sys.argv[3])):
    record({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Read",
            "tool_use_id": f"{sys.argv[2]}-{k}"}, {"run": "r1"}, 1.0, None)"""

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

# the lock attempts a held log gets before its line is dropped: about 21 ms in all
LOCK_TRIES = 10
ENTRY: dict[str, object] = {
    "run": "r1",
    "planning_dir": "/p",
    "marker": "/r/dsp-route.json",
}

Call = tuple[Mapping[str, object], Mapping[str, object], float, list[str] | None]


def event(hook: str, **fields: object) -> dict[str, object]:
    """A payload of hook for session s1."""
    return {"session_id": "s1", "hook_event_name": hook, **fields}


def post(tuid: str, agent: str | None = None, cwd: str = "/w") -> dict[str, object]:
    """A PostToolUse of Read, by agent (None: the lead)."""
    extra: dict[str, object] = {} if agent is None else {"agent_id": agent}
    return event("PostToolUse", tool_name="Read", tool_use_id=tuid, cwd=cwd, **extra)


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
        """Cut fields and an oversized line keep the line within LINE_MAX, with run."""
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
            f"a 100 KB description: {len(raw)} bytes, trunc and run kept",
            len(raw) <= record.LINE_MAX
            and line.get("trunc") is True
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

    def test_parallel_writers(self) -> None:
        """40 processes x 200 lines on one log: none torn, none lost."""
        procs, lines = 40, 200
        writers = [
            subprocess.Popen(
                [PY, "-c", WRITER, SCRIPTS, f"w{i}", str(lines)],
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for i in range(procs)
        ]
        codes = [w.wait(timeout=300) for w in writers]
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
            f"written {written}, torn {torn}, lost {lost}",
            codes == [0] * procs
            and written == procs * lines
            and torn == 0
            and lost == 0,
            codes,
        )

    def test_cap_and_heartbeat(self) -> None:
        """Past CAP_BYTES: one cap line, one post per agent a minute, the rest kept."""
        from dsp_route import record  # the hook imports it lazily (TID253)

        _ = self.write_bytes(self.log, b"")
        os.truncate(self.log, record.CAP_BYTES - 200)
        wide = "/w/" + "x" * 200  # so the first post crosses the cap
        agent = {"agent_id": "a1", "agent_type": "t"}
        self.rec(
            (post("t1", "a1", wide), ENTRY, 1.0, None),
            (post("t2", "a1", wide), ENTRY, 2.0, None),
            (post("t3", "a1", wide), ENTRY, 3.0, None),
            (event("SubagentStart", **agent), ENTRY, 4.0, None),
            (event("SubagentStop", **agent), ENTRY, 5.0, None),
            (event("TeammateIdle", teammate_name="n", **agent), ENTRY, 6.0, None),
        )
        stamp = self.events_dir / "s1.a1.hb"
        before = self._past_cap(record.CAP_BYTES - 200)
        self.touch(stamp, -61)
        self.rec((post("t4", "a1", wide), ENTRY, 7.0, None))
        after = self._past_cap(record.CAP_BYTES - 200)
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
