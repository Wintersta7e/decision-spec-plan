"""gate.py writes the log the push checks read: sha and dirty before the run, the status after
it."""

import unittest
from pathlib import Path

import support
from support import grep, grep_file


def lines(path):
    return Path(path).read_text().split("\n")[:-1]


class GateLog(support.Sandbox):
    no_hooks = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.R3 = cls.T / "r3"
        cls.P3 = cls.R3 / ".plan"
        cls.git("init", "-q", "--bare", cls.T / "r3.git")
        cls.git("init", "-q", "-b", "main", cls.R3)
        cls.write(cls.R3 / "f", "a\n")
        cls.git("-C", cls.R3, "add", "f")
        cls.git("-C", cls.R3, "commit", "-q", "-m", "one")
        cls.git("-C", cls.R3, "remote", "add", "origin", cls.T / "r3.git")

    def test_gate_log(self):
        R3, P3 = self.R3, self.P3
        head = self.rev(R3)
        cmd = "echo out; echo err >&2; exit 3"
        r = self.py("gate.py", P3, "g1", "--repo", R3, "--", cmd)
        log = P3 / "lanes/g1-gate.log"
        got = lines(log)
        self.ok(
            "gate.py: exits with the gate's status; sha, cmd, merged output and exit= in the "
            "log; output still printed",
            r.code == 3
            and got[0] == f"sha={head} dirty=0"
            and got[1] == f"cmd={cmd}"
            and grep_file(log, "err", x=True)
            and got[-1] == "exit=3"
            and grep(r.out, "out", x=True),
            f"exit {r.code}, log: {log.read_text()}",
        )
        self.py(
            "gate.py", P3, "g2", "--repo", R3, "--harness", "e2e", "--wt", "p1-01", "--",
            "printf", "a b",
        )  # fmt: skip
        log = P3 / "lanes/g2-e2e-gate.log"
        got = lines(log)
        self.ok(
            "gate.py --harness --wt: named log, harness line, argv command, exit= on its own line",
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
        self.write(R3 / "f", "b\n", mode="a")
        r = self.py("gate.py", P3, "g3", "--repo", R3, "--", "true", merge=True)
        self.ok(
            "gate.py: a dirty tree is counted and warned about",
            grep_file(P3 / "lanes/g3-gate.log", "^sha=.* dirty=1$")
            and grep(r.out, "gates no commit"),
            r.out,
        )
        self.git("-C", R3, "checkout", "-q", "f")
        r = self.py("gate.py", P3, "g4", "--repo", R3)
        self.ok(
            "gate.py with no command: refused, no log",
            r.code != 0 and not (P3 / "lanes/g4-gate.log").exists(),
        )


if __name__ == "__main__":
    unittest.main()
