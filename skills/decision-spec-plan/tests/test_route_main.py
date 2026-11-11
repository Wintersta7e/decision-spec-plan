# SPDX-License-Identifier: MIT
"""Routes side by side, and what a re-activation keeps.

`--main` on a master repository and a wrong `--main` in an old marker, two routes in one
repository, a legacy one-per-repository marker, and what a re-activation keeps.
"""

import json
import shutil
import unittest
from typing import cast

from typing_extensions import override

import support
from support import RS, ev, human, used

BUDGETS = 8  # the budgets TwoRoutes records on the first route


class MainBranch(support.Route):
    """`--main` on a master repository, and a wrong one."""

    def test_main_default_and_fallback(self) -> None:
        """--main defaults to master, and a wrong --main falls back with a flag."""
        t, home, repo, plan = self.T, self.HOME, self.R, self.P
        reg = home / ".claude/dsp-routes"
        mrepo = self.init_repo(t / "mrepo", branch="master")
        (mrepo / ".plan").mkdir()
        # The route of s1 restarted as s9: listed once, active as of s9's transcript
        # (5 min ago).
        _ = shutil.copy(reg / "s1.json", reg / "s9.json")
        self.touch(home / ".claude/projects/p/s9.jsonl", -300)
        self.touch(self.MK(repo), -3 * 86400)
        # The stop hook's sent-waits sidecar lives in the registry too, and is no route.
        _ = self.write(reg / "s9.waits.json", '{"a1:b1": 1}\n')
        r = self.py(
            RS,
            mrepo / ".plan",
            "--phase",
            "1",
            "--repo",
            mrepo,
            "--activate",
            session="s3",
            merge=True,
        )
        self.ok("activate skips a waits sidecar in the registry", r.code == 0, r.out)
        (reg / "s9.waits.json").unlink()
        self.ok(
            "--main defaults to master",
            support.grep_file(self.MK(mrepo), '"--main", "master"'),
            self.MK(mrepo).read_text(),
        )
        self.ok(
            "activate lists the other route once, active as of its lead's transcript",
            support.grep(
                r.out,
                f"other route on this account: {plan} (lead last active 5m ago)",
                count=True,
            )
            == 1,
            r.out,
        )
        out = self.py(
            RS, mrepo / ".plan", "--phase", "1", "--repo", mrepo, "--main", "main"
        ).out
        self.ok(
            "a wrong --main falls back with a flag",
            support.grep(out, "--main main does not exist .*using master"),
            out,
        )


class TwoRoutes(support.Route):
    """Two routes in one repository, and a legacy one-per-repository marker."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Restart s1's route as s9 and record eight budgets on it."""
        super().setUpClass()
        reg = cls.HOME / ".claude/dsp-routes"
        # s9: the route of s1 restarted as another lead session (the --main section's
        # copy)
        _ = shutil.copy(reg / "s1.json", reg / "s9.json")
        cls.touch(cls.HOME / ".claude/projects/p/s9.jsonl", -300)
        # the eight budgets the Stage 5 budget section recorded on the first route
        for session, label in (
            ("s1", "w1"),
            ("s1", "w2"),
            ("s9", "w3"),
            ("s1", "w3"),
            ("s1", "w4"),
            ("s1", "w4b"),
            ("s1", "w5"),
            ("s1", "w6"),
        ):
            _ = cls.py(
                RS,
                "--budget",
                label,
                "--estimate",
                "50",
                "--groups",
                "9",
                session=session,
            )
        assert len(cls.budgets()) == BUDGETS, cls.budgets()

    def test_two_routes_one_repository(self) -> None:
        """Each route keeps its own state; the pushing session's route decides."""
        t, home, repo, plan = self.T, self.HOME, self.R, self.P
        reg = home / ".claude/dsp-routes"
        p2 = repo / ".plan2"
        (p2 / "lanes").mkdir(parents=True)
        _ = self.py(
            RS,
            p2,
            "--phase",
            "4",
            "--repo",
            repo,
            "--activate",
            "--rung",
            "M",
            session="s5",
        )
        m1, m2 = self.marker(), self.marker(plan=p2)
        self.ok(
            "a second route in the repository leaves the first's phase and budgets",
            m1["args"][2] == "1"
            and len(self.budgets()) == BUDGETS
            and m2["args"][2] == "4",
            json.dumps(m1),
        )
        l5 = home / ".claude/projects/p/s5.jsonl"
        _ = self.py(
            RS, "--budget", "w9", "--estimate", "1", "--groups", "9", session="s5"
        )
        _ = self.write(l5, human(1) + "\n")
        # 5M by the first route's other lead
        self.append(home / ".claude/projects/p/s9.jsonl", used(2, "u9", 5000000))
        _ = self.hook(
            "/^ETA exec-p4-01-a/",
            ev(
                "PreToolUse",
                "s5",
                '"tool_name":"Agent","tool_input":{"name":"exec-p4-01-a"},'
                f'"tool_use_id":"v1","transcript_path":"{l5}"',
            ),
        )

        # the pushing session's own route decides; with no session, the newest route
        def gs(session: str, command: str) -> bool:
            stdin = json.dumps(
                {
                    "tool_input": {"command": command},
                    "cwd": str(repo),
                    "session_id": session,
                }
            )
            return self.py(support.GUARD, input=stdin).code == 0

        _ = self.write(
            plan / "lanes/two-gate.log",
            f"sha={self.rev(repo, 'main')} dirty=0\nok\nexit=0\n",
        )
        self.ok(
            "guard: s1's route has main's gate log", gs("s1", "git push origin main")
        )
        self.ok("guard: s5's route holds main", not gs("s5", "git push origin main"))
        self.ok(
            "guard: no session, the newest route holds main",
            not gs("", "git push origin main"),
        )
        self.rm(self.MK(repo, p2), reg / "s5.json", plan / "lanes/two-gate.log")

        # a route activated under the one-per-repository marker moves to its own,
        # budgets and all
        xrepo = t / "xrepo"
        _ = self.git("init", "-q", "-b", "main", xrepo)
        (xrepo / ".plan").mkdir()
        _ = self.write(
            xrepo / ".git/dsp-route.json",
            f'{{"planning_dir": "{(xrepo / ".plan").resolve()}", '
            '"budgets": [{"label": "old"}]}\n',
        )
        _ = self.py(
            RS,
            xrepo / ".plan",
            "--phase",
            "1",
            "--repo",
            xrepo,
            "--activate",
            session="s6",
        )
        self.ok(
            "a legacy marker moves to the route's own, budgets kept",
            not (xrepo / ".git/dsp-route.json").exists()
            and self.marker(xrepo).get("budgets", [{}])[0].get("label") == "old",
            str(sorted(p.name for p in (xrepo / ".git").iterdir())),
        )
        self.rm(reg / "s6.json")


class ReactivationKeepsRung(support.Sandbox):
    """What a re-activation keeps: the rung, the sins setting and the ledger."""

    def test_reactivation_rung_and_ledger(self) -> None:
        """The rung and ledger survive a re-activation; old rounds stay unbound."""
        t, home = self.T, self.HOME
        q = self.init_repo(t / "qrepo")
        (q / ".plan/decisions/phase1").mkdir(parents=True)
        mk = support.Route.MK

        def activate(phase: str, *extra: str) -> None:
            plan = q / ".plan"
            _ = self.py(
                RS,
                plan,
                "--phase",
                phase,
                "--repo",
                q,
                "--activate",
                *extra,
                session="s7",
            )

        def marker() -> support.Marker:
            return cast("support.Marker", json.loads(mk(q).read_text()))

        activate("1", "--rung", "S")
        activate("1", "--sins", "on")
        m = marker()
        self.ok(
            "a re-activation without --rung keeps the rung",
            m.get("rung") == "S" and m.get("sins") == "on",
            json.dumps(m),
        )
        _ = self.write(
            q / ".plan/decisions/phase1/00-index.md", "| **D1** | x |\n| **D2** | y |\n"
        )
        out = self.py(RS, q / ".plan", "--phase", "1", "--repo", q).out
        self.ok(
            "rung S: the index's decisions are not pending D files",
            support.grep(out, "decisions  0 D files (2 in the index)")
            and not support.grep(out, "pending"),
            out,
        )
        mk(q).unlink()
        activate("1", "--rung", "S")
        m = marker()
        self.ok(
            "an ended route's phase stays bound by the ledger",
            m.get("ledger", {}).get("1") is True,
            json.dumps(m),
        )
        # a review round written before its phase was first activated keeps its
        # format; a later one is bound
        p2 = q / ".plan/decisions/phase2"
        (p2 / "old-round").mkdir(parents=True)
        (p2 / "new-round").mkdir(parents=True)
        self.touch(p2 / "old-round/00-index.md")
        activate("2")
        self.touch(p2 / "new-round/00-index.md")
        activate("2")
        led = marker().get("ledger", {})
        self.ok(
            "a round older than its phase's first activation is unbound, "
            "a later one bound",
            led.get("2/old-round") is False and "2/new-round" not in led,
            json.dumps(led),
        )
        (home / ".claude/dsp-routes/s7.json").unlink()


if __name__ == "__main__":
    _ = unittest.main()
