"""Routes side by side: `--main` on a master repository and a wrong `--main` in an old marker, two
routes in one repository, a legacy one-per-repository marker, and what a re-activation keeps."""

import json
import shutil
import unittest

import support
from support import RS, ev, human, used


class MainBranch(support.Route):
    def test_main_default_and_fallback(self):
        T, HOME, R, P = self.T, self.HOME, self.R, self.P
        reg = HOME / ".claude/dsp-routes"
        M = self.init_repo(T / "mrepo", branch="master")
        (M / ".plan").mkdir()
        # The route of s1 restarted as s9: listed once, active as of s9's transcript (5 min ago).
        shutil.copy(reg / "s1.json", reg / "s9.json")
        self.touch(HOME / ".claude/projects/p/s9.jsonl", -300)
        self.touch(self.MK(R), -3 * 86400)
        # The stop hook's sent-waits sidecar lives in the registry too, and is no route.
        self.write(reg / "s9.waits.json", '{"a1:b1": 1}\n')
        r = self.py(
            RS,
            M / ".plan",
            "--phase",
            "1",
            "--repo",
            M,
            "--activate",
            session="s3",
            merge=True,
        )
        self.ok("activate skips a waits sidecar in the registry", r.code == 0, r.out)
        (reg / "s9.waits.json").unlink()
        self.ok(
            "--main defaults to master",
            support.grep_file(self.MK(M), '"--main", "master"'),
            self.MK(M).read_text(),
        )
        self.ok(
            "activate lists the other route once, active as of its lead's transcript",
            support.grep(
                r.out,
                f"other route on this account: {P} (lead last active 5m ago)",
                count=True,
            )
            == 1,
            r.out,
        )
        out = self.py(
            RS, M / ".plan", "--phase", "1", "--repo", M, "--main", "main"
        ).out
        self.ok(
            "a wrong --main falls back with a flag",
            support.grep(out, "--main main does not exist .*using master"),
            out,
        )


class TwoRoutes(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reg = cls.HOME / ".claude/dsp-routes"
        # s9: the route of s1 restarted as another lead session (the --main section's copy)
        shutil.copy(reg / "s1.json", reg / "s9.json")
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
            cls.py(
                RS,
                "--budget",
                label,
                "--estimate",
                "50",
                "--groups",
                "9",
                session=session,
            )
        assert len(cls.budgets()) == 8, cls.budgets()

    def test_two_routes_one_repository(self):
        T, HOME, R, P = self.T, self.HOME, self.R, self.P
        reg = HOME / ".claude/dsp-routes"
        P2 = R / ".plan2"
        (P2 / "lanes").mkdir(parents=True)
        self.py(
            RS,
            P2,
            "--phase",
            "4",
            "--repo",
            R,
            "--activate",
            "--rung",
            "M",
            session="s5",
        )
        m1, m2 = self.marker(), self.marker(plan=P2)
        self.ok(
            "a second route in the repository leaves the first's phase and budgets",
            m1["args"][2] == "1" and len(self.budgets()) == 8 and m2["args"][2] == "4",
            json.dumps(m1),
        )
        L5 = HOME / ".claude/projects/p/s5.jsonl"
        self.py(RS, "--budget", "w9", "--estimate", "1", "--groups", "9", session="s5")
        self.write(L5, human(1) + "\n")
        # 5M by the first route's other lead
        self.append(HOME / ".claude/projects/p/s9.jsonl", used(2, "u9", 5000000))
        self.hook(
            "/^ETA exec-p4-01-a/",
            ev(
                "PreToolUse",
                "s5",
                '"tool_name":"Agent","tool_input":{"name":"exec-p4-01-a"},'
                f'"tool_use_id":"v1","transcript_path":"{L5}"',
            ),
        )

        # the pushing session's own route decides; with no session, the newest route
        def gs(session, command):
            stdin = json.dumps(
                {
                    "tool_input": {"command": command},
                    "cwd": str(R),
                    "session_id": session,
                }
            )
            return self.py(support.GUARD, input=stdin).code == 0

        self.write(
            P / "lanes/two-gate.log", f"sha={self.rev(R, 'main')} dirty=0\nok\nexit=0\n"
        )
        self.ok(
            "guard: s1's route has main's gate log", gs("s1", "git push origin main")
        )
        self.ok("guard: s5's route holds main", not gs("s5", "git push origin main"))
        self.ok(
            "guard: no session, the newest route holds main",
            not gs("", "git push origin main"),
        )
        self.rm(self.MK(R, P2), reg / "s5.json", P / "lanes/two-gate.log")

        # a route activated under the one-per-repository marker moves to its own, budgets and all
        X = T / "xrepo"
        self.git("init", "-q", "-b", "main", X)
        (X / ".plan").mkdir()
        self.write(
            X / ".git/dsp-route.json",
            f'{{"planning_dir": "{(X / ".plan").resolve()}", "budgets": [{{"label": "old"}}]}}\n',
        )
        self.py(
            RS, X / ".plan", "--phase", "1", "--repo", X, "--activate", session="s6"
        )
        self.ok(
            "a legacy marker moves to the route's own, budgets kept",
            not (X / ".git/dsp-route.json").exists()
            and self.marker(X).get("budgets", [{}])[0].get("label") == "old",
            str(sorted(p.name for p in (X / ".git").iterdir())),
        )
        self.rm(reg / "s6.json")


class ReactivationKeepsRung(support.Sandbox):
    def test_reactivation_rung_and_ledger(self):
        T, HOME = self.T, self.HOME
        Q = self.init_repo(T / "qrepo")
        (Q / ".plan/decisions/phase1").mkdir(parents=True)
        MK = support.Route.MK

        def activate(phase, *extra):
            plan = Q / ".plan"
            self.py(
                RS,
                plan,
                "--phase",
                phase,
                "--repo",
                Q,
                "--activate",
                *extra,
                session="s7",
            )

        activate("1", "--rung", "S")
        activate("1", "--sins", "on")
        m = json.loads(MK(Q).read_text())
        self.ok(
            "a re-activation without --rung keeps the rung",
            m.get("rung") == "S" and m.get("sins") == "on",
            json.dumps(m),
        )
        self.write(
            Q / ".plan/decisions/phase1/00-index.md", "| **D1** | x |\n| **D2** | y |\n"
        )
        out = self.py(RS, Q / ".plan", "--phase", "1", "--repo", Q).out
        self.ok(
            "rung S: the index's decisions are not pending D files",
            support.grep(out, "decisions  0 D files (2 in the index)")
            and not support.grep(out, "pending"),
            out,
        )
        MK(Q).unlink()
        activate("1", "--rung", "S")
        m = json.loads(MK(Q).read_text())
        self.ok(
            "an ended route's phase stays bound by the ledger",
            m.get("ledger", {}).get("1") is True,
            json.dumps(m),
        )
        # a review round written before its phase was first activated keeps its format; a
        # later one is bound
        p2 = Q / ".plan/decisions/phase2"
        (p2 / "old-round").mkdir(parents=True)
        (p2 / "new-round").mkdir(parents=True)
        self.touch(p2 / "old-round/00-index.md")
        activate("2")
        self.touch(p2 / "new-round/00-index.md")
        activate("2")
        led = json.loads(MK(Q).read_text()).get("ledger", {})
        self.ok(
            "a round older than its phase's first activation is unbound, a later one bound",
            led.get("2/old-round") is False and "2/new-round" not in led,
            json.dumps(led),
        )
        (HOME / ".claude/dsp-routes/s7.json").unlink()


if __name__ == "__main__":
    unittest.main()
