# SPDX-License-Identifier: MIT
"""gate.py writes the log the push checks read.

The log holds sha and dirty before the run, the status after it.
"""

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
        cmd = f"echo out; echo err >&2; exit {GATE_STATUS}"
        r = self.py("gate.py", p3, "g1", "--repo", r3, "--", cmd)
        log = p3 / "lanes/g1-gate.log"
        got = lines(log)
        self.ok(
            "gate.py: exits with the gate's status; sha, cmd, merged output and exit= "
            "in the "
            "log; output still printed",
            r.code == GATE_STATUS
            and got[0] == f"sha={head} dirty=0"
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
                f"sha={head} dirty=0 wt=p1-01",
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
            grep_file(p3 / "lanes/g3-gate.log", "^sha=.* dirty=1$")
            and grep(r.out, "gates no commit"),
            r.out,
        )
        _ = self.git("-C", r3, "checkout", "-q", "f")
        r = self.py("gate.py", p3, "g4", "--repo", r3)
        self.ok(
            "gate.py with no command: refused, no log",
            r.code != 0 and not (p3 / "lanes/g4-gate.log").exists(),
        )


if __name__ == "__main__":
    _ = unittest.main()
