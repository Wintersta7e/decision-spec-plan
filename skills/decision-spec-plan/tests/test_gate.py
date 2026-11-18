# SPDX-License-Identifier: MIT
"""gate.py writes the log the push checks read.

The log holds sha and dirty before the run, the status after it.
"""

import fcntl
import os
import unittest
from pathlib import Path
from typing import ClassVar

from typing_extensions import override

import support
from support import grep, grep_file

GATE_STATUS = 3  # the status the first gate's command exits with


def lines(path: Path) -> list[str]:
    """The file's lines, without the piece after its last newline."""
    return path.read_text().split("\n")[:-1]


class GateLog(support.Sandbox):
    """gate.py runs in repository R3, which has a bare origin."""

    no_hooks: ClassVar[bool] = False

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Create R3 with one commit, its planning dir P3 and its origin."""
        super().setUpClass()
        cls.R3: Path = cls.T / "r3"
        cls.P3: Path = cls.R3 / ".plan"
        _ = cls.git("init", "-q", "--bare", cls.T / "r3.git")
        _ = cls.git("init", "-q", "-b", "main", cls.R3)
        _ = cls.write(cls.R3 / "f", "a\n")
        _ = cls.git("-C", cls.R3, "add", "f")
        _ = cls.git("-C", cls.R3, "commit", "-q", "-m", "one")
        _ = cls.git("-C", cls.R3, "remote", "add", "origin", cls.T / "r3.git")

    def test_gate_log(self) -> None:
        """The log's lines, its name, a dirty tree and a missing command."""
        r3, p3 = self.R3, self.P3
        head = self.rev(r3)
        tree = self.git("-C", r3, "rev-parse", "HEAD^{tree}").strip()
        cmd = f"echo out; echo err >&2; exit {GATE_STATUS}"
        r = self.py("gate.py", p3, "g1", "--repo", r3, "--", cmd)
        log = p3 / "lanes/g1-gate.log"
        got = lines(log)
        self.ok(
            "gate.py: exits with the gate's status; sha, cmd, merged output and exit= "
            "in the "
            "log; output still printed",
            r.code == GATE_STATUS
            and got[0] == f"sha={head} dirty=0 tree={tree}"
            and got[1] == f"cmd={cmd}"
            and grep_file(log, "err", x=True)
            and got[-1] == f"exit={GATE_STATUS}"
            and grep(r.out, "out", x=True),
            f"exit {r.code}, log: {log.read_text()}",
        )
        _ = self.py(
            "gate.py", p3, "g2", "--repo", r3, "--harness", "e2e", "--wt", "p1-01",
            "--", "printf", "a b",
        )  # fmt: skip
        log = p3 / "lanes/g2-e2e-gate.log"
        got = lines(log)
        self.ok(
            "gate.py --harness --wt: named log, harness line, argv command, "
            "exit= on its own line",
            got[:5]
            == [
                f"sha={head} dirty=0 wt=p1-01 tree={tree}",
                "harness=e2e",
                "cmd=printf 'a b'",
                "a b",
                "exit=0",
            ],
            log.read_text(),
        )
        _ = self.write(r3 / "f", "b\n", mode="a")
        r = self.py("gate.py", p3, "g3", "--repo", r3, "--", "true", merge=True)
        self.ok(
            "gate.py: a dirty tree is counted and warned about",
            grep_file(p3 / "lanes/g3-gate.log", "^sha=.* dirty=1 tree=[0-9a-f]*$")
            and grep(r.out, "gates no commit"),
            r.out,
        )
        _ = self.git("-C", r3, "checkout", "-q", "f")
        r = self.py("gate.py", p3, "g4", "--repo", r3)
        self.ok(
            "gate.py with no command: refused, no log",
            r.code != 0 and not (p3 / "lanes/g4-gate.log").exists(),
        )


class GateMachine(support.Sandbox):
    """gate.py keeps the machine the user's: half the cores, and a shared slot."""

    def test_half_the_cores(self) -> None:
        """The build tools' parallelism is half the cores unless the caller set it."""
        r, pd = self.T / "hc/r", self.T / "hc/pd"
        _ = self.init_repo(r)
        cmd = 'echo "jobs=$CARGO_BUILD_JOBS cmake=$CMAKE_BUILD_PARALLEL_LEVEL"'
        _ = self.py("gate.py", pd, "a", "--repo", r, "--", cmd)
        half = max(1, (os.cpu_count() or 2) // 2)
        self.ok(
            "gate.py: unset parallelism is half the cores",
            grep_file(pd / "lanes/a-gate.log", f"jobs={half} cmake={half}", x=True),
            (pd / "lanes/a-gate.log").read_text(),
        )
        env = {"CARGO_BUILD_JOBS": "3"}
        _ = self.py("gate.py", pd, "b", "--repo", r, "--", cmd, env=env)
        self.ok(
            "gate.py: a set value is kept",
            grep_file(pd / "lanes/b-gate.log", f"jobs=3 cmake={half}", x=True),
            (pd / "lanes/b-gate.log").read_text(),
        )
        _ = self.py("gate.py", pd, "c", "--repo", r, "--", "echo ni=$(ps -o ni= -p $$)")
        self.ok(
            "gate.py: the gate runs at nice 19",
            grep_file(pd / "lanes/c-gate.log", "ni= *19", x=True),
            (pd / "lanes/c-gate.log").read_text(),
        )

    def test_slot_held(self) -> None:
        """With every slot held, gate.py waits its time out, then runs anyway."""
        r, pd = self.T / "sl/r", self.T / "sl/pd"
        _ = self.init_repo(r)
        slots = self.HOME / ".claude/dsp-routes/gate-slots"
        slots.mkdir(parents=True, exist_ok=True)
        env = {"DSP_GATE_SLOTS": "1", "DSP_GATE_WAIT_MIN": "0"}
        free = self.py(
            "gate.py", pd, "a", "--repo", r, "--", "true", env=env, merge=True
        )
        with (slots / "0.lock").open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            busy = self.py(
                "gate.py", pd, "b", "--repo", r, "--", "true", env=env, merge=True
            )
        self.ok(
            "gate.py: a free slot runs without a word",
            free.code == 0 and "slot" not in free.out,
            free.out,
        )
        self.ok(
            "gate.py: a held slot past the wait runs anyway and says so",
            busy.code == 0
            and grep(busy.out, "no gate slot came free")
            and lines(pd / "lanes/b-gate.log")[-1] == "exit=0",
            busy.out,
        )


class GateNoLock(support.Sandbox):
    """gate.py counts a stat-dirty tree's changes without rewriting its index."""

    def test_gate_takes_no_lock(self) -> None:
        """The index is unchanged by gate.py; plain git status rewrites it."""
        r, pd = self.T / "nl/r", self.T / "nl/pd"
        _ = self.init_repo(r, commits=())
        _ = self.write(r / "g", "g\n")
        _ = self.git("-C", r, "add", "g")
        _ = self.git("-C", r, "commit", "-q", "-m", "base")
        self.stat_dirty(r / "g")
        before = self.index_state(r)
        _ = self.py("gate.py", pd, "g", "--repo", r, "--", "true")
        after = self.index_state(r)
        first = lines(pd / "lanes/g-gate.log")[0]
        self.ok(
            "gate.py: index unchanged and no index.lock in a stat-dirty tree; dirty=0",
            after == before and " dirty=0 " in first,
            f"before {before}\nafter  {after}\n{first}",
        )
        _ = self.git("-C", r, "status", "--porcelain")
        control = self.index_state(r)
        self.ok(
            "control: plain git status rewrites the index gate.py left unchanged",
            control != before,
            f"before {before}\ncontrol {control}",
        )


if __name__ == "__main__":
    _ = unittest.main()
