"""`route_state.py`'s report: lanes and how each merged, spec sections, base drift, odd inputs,
lanes that moved past their merged SHA (F41), and the hook's delta on a changed lane line."""

import unittest

import support
from support import RS, ev, grep


def x_text(n):
    return "x" * n


class Lanes(support.Route):
    """Final SHA, merged by ancestry, by patch, by the integrator's record; an open lane's line."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lanes = cls.P / "lanes"
        # the main gate logs section 152 left behind
        cls.write(lanes / "red-gate.log", f"sha={cls.MAIN} dirty=0\n...\nexit=1\n")
        cls.write(lanes / "dirty-gate.log", f"sha={cls.MAIN} dirty=3\n...\nexit=0\n")
        cls.write(lanes / "wave1-int-gate.log", f"sha={cls.MAIN} dirty=0\nok\nexit=0\n")
        # the lane checkpoint section 846 wrote
        cls.write(lanes / "p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {cls.MAIN}\n")

    def report(self, *extra):
        return self.py(RS, self.P, "--phase", "1", "--repo", self.R, *extra).out

    def test_lanes(self):
        R, P, T, WT, MAIN = self.R, self.P, self.T, self.WT, self.MAIN
        lanes = P / "lanes"
        self.git("-C", WT, "commit", "-q", "--allow-empty", "-m", "lane-a")
        self.write(WT / "f.txt", "x\n")
        self.git("-C", WT, "add", "f.txt")
        self.git("-C", WT, "commit", "-q", "-m", "lane-b")
        F2 = self.rev(WT)
        self.git("-C", R, "cherry-pick", F2)
        self.write(
            lanes / "p1-02-checkpoint.md",
            f"Final SHA: {F2}\nnote: older commit {MAIN[:7]}\n",
        )
        out = self.report("--all")
        self.ok(
            "Final SHA used, rebased lane merged by patch",
            grep(out, f"p1-02 .*{F2[:7]}[0-9a-f]* merged (by patch)"),
            out,
        )
        self.ok(
            "ancestor lane merged; main's worktree not counted",
            grep(out, "p1-01 .*merged") and grep(out, "1 lane worktrees"),
            out,
        )
        self.write(WT / "g.txt", "fixup\n")
        self.git("-C", WT, "add", "g.txt")
        self.git("-C", WT, "commit", "-q", "-m", "fixup! lane-b")
        F3 = self.rev(WT)
        self.write(R / "g.txt", "squashed\n")
        self.git("-C", R, "add", "g.txt")
        self.git("-C", R, "commit", "-q", "-m", "squashed")
        SQ = self.rev(R)
        self.write(lanes / "p1-03-checkpoint.md", f"Final SHA: {F3}\n")
        out = self.report("--all")
        self.ok(
            "squashed lane without a record: not merged",
            grep(out, "p1-03 .*not merged"),
            out,
        )
        self.write(
            lanes / "wave1-integration.md",
            f"# wave 1\nMerged p1-03 `{F3[:9]}` → `{SQ[:9]}`\n",
        )
        out = self.report("--all")
        self.ok(
            "squashed lane merged per the integrator's record",
            grep(out, f"p1-03 .*merged as {SQ[:9]} (wave1-integration.md)"),
            out,
        )
        self.ok(
            "no Final SHA flag when present",
            not grep(out, "no `Final SHA:` line"),
            out,
        )
        # a merged lane's long checkpoint: no next group reads it, so no length flag (F76)
        self.write(
            lanes / "p1-05-checkpoint.md",
            f"Final SHA: {MAIN}\n" + "".join(f"{i}\n" for i in range(1, 41)),
        )
        out = self.report("--all")
        self.ok(
            "no length flag on a merged lane's checkpoint",
            grep(out, "p1-05 .*merged")
            and not grep(out, "checkpoint over 35 lines *lanes/p1-05"),
            out,
        )
        self.rm(lanes / "p1-05-checkpoint.md")
        # an open lane's line is the lead's check of a return (F80); lanes are found whatever
        # their name, never another phase's
        WT2 = T / "wt2"
        self.git("-C", R, "worktree", "add", "-q", "-b", "fix-ui", WT2, "main")
        self.write(WT2 / "a.txt", "a\n")
        self.git("-C", WT2, "add", "a.txt")
        self.git("-C", WT2, "commit", "-q", "-m", "ui: a", "-m", "Co-Authored-By: t")
        FX = self.rev(WT2)
        self.write(lanes / "fix-ui-checkpoint.md", f"Final SHA: {FX}\n")
        self.write(lanes / "p2-01-checkpoint.md", f"Final SHA: {MAIN}\n")
        self.write(lanes / "fix-ui-rulings.md", x_text(13000))
        self.write(lanes / "fix-ui-rulings-archive.md", x_text(20000))
        out = self.report()
        self.ok(
            "an open lane's line without --all, any name, not another phase's",
            grep(
                out,
                "fix-ui .* not merged · 1 commits · no gate log at this SHA · "
                "trailers Co-Authored-By ×1$",
            )
            and not grep(out, "p2-01"),
            out,
        )
        # an open lane's rulings file every group reads whole, past 12 KB; never its archive (F67)
        self.ok(
            "an open lane's rulings file over 12 KB is flagged, its archive is not",
            grep(out, "rulings over 12 KB *lanes/fix-ui-rulings.md (13 KB")
            and not grep(out, "rulings-archive.md ("),
            out,
        )
        # a CI harness's log runs only that suite: no full gate, as push_guard.py reads it
        self.write(
            lanes / "fix-ui-it-gate.log", f"sha={FX} dirty=0\nharness=it\nok\nexit=0\n"
        )
        out = self.report()
        self.ok(
            "the lane line: a harness log is no full gate",
            grep(out, "fix-ui .* · no gate log at this SHA · "),
            out,
        )
        self.rm(lanes / "fix-ui-it-gate.log")
        self.write(lanes / "fix-ui-gate.log", f"sha={FX} dirty=0\nok\nexit=0\n")
        self.write(WT2 / "a.txt", "b\n", mode="a")
        out = self.report()
        self.ok(
            "the lane line: gate at its SHA, uncommitted work",
            grep(
                out,
                "fix-ui .* · gate exit=0 · trailers Co-Authored-By ×1 · "
                "1 uncommitted in its worktree$",
            ),
            out,
        )
        self.unthrottle()
        self.hook("report", ev("SessionStart", "s1", '"source":"compact"'))
        self.git("-C", WT2, "commit", "-q", "-am", "ui: b")
        self.write(lanes / "fix-ui-checkpoint.md", f"Final SHA: {self.rev(WT2)}\n")
        self.unthrottle()
        self.hook(
            r"/changed between [\s\S]*fix-ui +[0-9a-f]+ not merged · 2 commits · "
            r"no gate log at this SHA/",
            ev("PostToolUse", "s1", '"tool_name":"Bash"'),
        )


class Sections(support.Route):
    """--sections: a closed range with a pending section, an open range."""

    def test_sections(self):
        P = self.P
        self.write(P / "spec/01-scope.md", "x\n")
        self.write(P / "spec/02-core.md", "x\n")
        out = self.py(RS, P, "--phase", "1", "--sections", "1-").out
        self.ok(
            "--sections 1- counts every section from §1",
            grep(out, "spec       2 sections from §1"),
            out,
        )
        out = self.py(RS, P, "--phase", "1", "--sections", "1-3").out
        self.ok(
            "--sections 1-3 lists the pending one",
            grep(out, "spec       2/3 sections (pending §3)"),
            out,
        )


class BaseDrift(support.Sandbox):
    """The base or an assumed branch moved since the decision index recorded them (F91)."""

    def test_base_drift(self):
        B = self.init_repo(self.T / "base", commits=("base",))
        self.git("-C", B, "branch", "api")
        B0 = self.rev(B, "main")
        self.write(
            B / ".plan/decisions/phase1/00-index.md",
            f"# Phase 1\n> **Base**: `main` at `{B0}`\n"
            f"> **Assumes**: `api` at `{B0[:12]}` — its new endpoints\n"
            f"> **Assumes**: `gone` at `{B0}`\n",
        )
        out = self.py(RS, B / ".plan", "--phase", "1", "--repo", B).out
        self.ok(
            "base drift: nothing moved, one assumed ref gone",
            not grep(out, r"base moved\|assumed ref moved")
            and grep(out, f"assumes ref gone *gone (recorded at {B0[:9]})"),
            out,
        )
        self.git("-C", B, "checkout", "-q", "api")
        self.git("-C", B, "commit", "-q", "--allow-empty", "-m", "endpoint")
        self.git("-C", B, "checkout", "-q", "main")
        self.git("-C", B, "merge", "-q", "--no-ff", "-m", "merge", "api")
        out = self.py(RS, B / ".plan", "--phase", "1", "--repo", B).out
        self.ok(
            "base drift: the base moved and an assumed branch merged into it",
            grep(out, f"base moved *main 2 commits past {B0[:9]}")
            and grep(
                out,
                f"assumed ref moved *api {B0[:9]} → [0-9a-f]\\{{9\\}}, merged into main",
            ),
            out,
        )


class OddInputs(support.Sandbox):
    """A squashed lane named in backticks, another phase's gate log, a carriage return before
    exit=, a non-UTF-8 byte, an en dash, a detached master repo."""

    def test_odd_inputs(self):
        T = self.T
        S = self.init_repo(T / "srepo")
        self.git("-C", S, "checkout", "-q", "-b", "p1-01")
        for f in ("a", "b"):
            self.write(S / f, f"{f}\n")
            self.git("-C", S, "add", f)
            self.git("-C", S, "commit", "-q", "-m", f)
        LANE = self.rev(S)
        self.git("-C", S, "checkout", "-q", "main")
        self.git("-C", S, "merge", "-q", "--squash", "p1-01")
        self.git("-C", S, "commit", "-q", "-m", "squash")
        self.git("-C", S, "branch", "-q", "-D", "p1-01")
        SP = S / ".plan"
        (SP / "lanes").mkdir(parents=True)
        (SP / "decisions/phase1").mkdir(parents=True)
        self.write(SP / "lanes/p1-01-checkpoint.md", f"Final SHA: {LANE}\n")
        short = self.git("-C", S, "rev-parse", "--short=9", "main")
        self.write(
            SP / "lanes/wave1-integration.md",
            f"- Merged `p1-01` `{LANE[:9]}` → `{short}`\n",
        )
        self.write(SP / "lanes/p2-03-gate.log", f"sha={'a' * 40} dirty=0\nexit=1\n")
        self.write(
            SP / "lanes/wave1-gate.log",
            f"sha={self.rev(S, 'main')} dirty=0\nprogress 100%\rexit=0\n",
        )
        self.write_bytes(SP / "decisions/phase1/00-index.md", b"| **D1** | Caf\xe9 |\n")
        out = self.py(
            RS, SP, "--phase", "1", "--repo", S, "--sections", "1–2", merge=True
        ).out
        self.ok(
            "report: a squashed lane recorded in backticks is merged",
            grep(out, "1 merged into main"),
            out,
        )
        self.ok(
            "report: another phase's gate log is not counted; a CR is no line break",
            not grep(out, "p2-03-gate.log")
            and grep(out, "gates      0 green · 0 red · 1 without exit="),
            out,
        )
        self.ok(
            "report: a cp1252 byte in the index and an en dash in --sections",
            grep(out, "decisions  0 D files (1 in the index")
            and grep(out, "spec       0/2 sections"),
            out,
        )
        DM = self.init_repo(T / "drepo", branch="master", commits=("one", "lane"))
        self.write(
            DM / ".plan/lanes/p1-01-checkpoint.md", f"Final SHA: {self.rev(DM)}\n"
        )
        self.git("-C", DM, "checkout", "-q", "--detach")
        out = self.py(RS, DM / ".plan", "--phase", "1", "--repo", DM).out
        self.ok(
            "report: a detached master repo with no origin uses master",
            grep(out, "1 merged into master") and not grep(out, "does not exist"),
            out,
        )


class BaseDriftMergedAndUpstream(support.Sandbox):
    """An assumed branch merged without moving; the base's upstream moved on a fetch (F91)."""

    def test_merged_and_upstream(self):
        T = self.T
        B2 = self.init_repo(T / "base2", commits=("base",))
        self.git("-C", B2, "checkout", "-q", "-b", "feat")
        self.git("-C", B2, "commit", "-q", "--allow-empty", "-m", "f")
        F0 = self.rev(B2, "feat")
        self.git("-C", B2, "checkout", "-q", "main")
        self.write(
            B2 / ".plan/decisions/phase1/00-index.md",
            f"> **Base**: `main` at `{self.rev(B2, 'main')}`\n> **Assumes**: `feat` at `{F0}`\n",
        )
        self.git("-C", B2, "merge", "-q", "--no-ff", "-m", "merge", "feat")
        out = self.py(RS, B2 / ".plan", "--phase", "1", "--repo", B2).out
        self.ok(
            "base drift: an assumed branch merged without moving",
            grep(out, f"assumed ref merged *feat {F0[:9]} into main"),
            out,
        )
        clone = T / "clone"
        self.git("clone", "-q", B2, clone)
        C0 = self.rev(clone, "main")
        self.write(
            clone / ".plan/decisions/phase1/00-index.md",
            f"> **Base**: `main` at `{C0}`\n",
        )
        self.git("-C", B2, "commit", "-q", "--allow-empty", "-m", "later")
        self.git("-C", clone, "fetch", "-q")
        out = self.py(RS, clone / ".plan", "--phase", "1", "--repo", clone).out
        self.ok(
            "base drift: the base's upstream moved, fetched not pulled",
            grep(out, f"main@{{upstream}} 1 commits past {C0[:9]}", F=True),
            out,
        )


class LaneMovedPastMerge(support.Sandbox):
    """F41: a lane's commits past its merged SHA that main lacks; a lane the integrator rebased
    and merged has none, though its tip is not the checkpoint's SHA."""

    def test_f41(self):
        TF = self.T / "f41"
        r, wt = TF / "r", TF / "wt"
        self.init_repo(r, commits=("base",))
        self.git("-C", r, "worktree", "add", "-q", "-b", "p1-01-a", wt)
        self.write(wt / "x", "x\n")
        self.git("-C", wt, "add", "x")
        self.git("-C", wt, "commit", "-q", "-m", "lane")
        c1 = self.rev(wt)
        self.write(r / "y", "y\n")
        self.git("-C", r, "add", "y")
        self.git("-C", r, "commit", "-q", "-m", "main2")
        self.git("-C", wt, "rebase", "-q", "main")
        self.git("-C", r, "merge", "-q", "--ff-only", "p1-01-a")
        cp = self.write(TF / "plan/lanes/p1-01-a-checkpoint.md", f"Final SHA: {c1}\n")
        self.touch(cp, -3600)

        def report():
            return self.py(
                RS, TF / "plan", "--phase", "1", "--repo", r, "--all", merge=True
            ).out

        out = report()
        self.ok(
            "report: a lane rebased and merged has not moved past its SHA",
            grep(out, "p1-01-a .*merged") and not grep(out, "F41"),
            out,
        )
        self.write(wt / "z", "z\n")
        self.git("-C", wt, "add", "z")
        self.git("-C", wt, "commit", "-q", "-m", "late")
        out = report()
        self.ok(
            "report: a lane commit after its merge, missing from main, is flagged",
            grep(out, "lane moved past its merged SHA *p1-01-a (1 commits, F41)"),
            out,
        )
        # a red CI-harness run is reported like any gate log, though it is no full gate
        self.write(
            TF / "plan/lanes/p1-01-a-gate-pg.log",
            f"sha={c1} dirty=0\nharness=pg\n3 failed\nexit=1\n",
        )
        out = report()
        self.ok(
            "report: a red CI-harness gate log is flagged",
            grep(out, "gates .* 1 red")
            and grep(out, "RED harness=pg exit=1 *lanes/p1-01-a-gate-pg.log"),
            out,
        )


class RungSWithoutRepo(support.Sandbox):
    """A rung-S route activated without --repo: its marker sits in the planning dir's repository,
    and its index rows are the decisions — no D file is pending (templates.md §1)."""

    def test_rung_s_without_repo(self):
        sr = self.init_repo(self.T / "sr")
        self.write(
            sr / ".plan/decisions/phase1/00-index.md", "| D1 | a |\n| D2 | b |\n"
        )
        self.py(
            RS,
            sr / ".plan",
            "--phase",
            "1",
            "--activate",
            "--rung",
            "S",
            session="rs1",
            cwd=self.T,
        )
        out = self.hook_out(
            '{"hook_event_name":"PostToolUse","session_id":"rs1","cwd":"/tmp","tool_name":"Read"}'
        ).out
        self.ok(
            "report: a rung-S route without --repo lists no D file as pending",
            grep(out, "decisions  0 D files (2 in the index)")
            and not grep(out, "pending"),
            out,
        )


class DeltaLaneLine(support.Sandbox):
    """The hook's delta: a lane line that changed is no cleared flag."""

    def test_changed_lane_line(self):
        TC = self.T / "cl"
        r, wt = TC / "r", TC / "wt"
        self.init_repo(r, commits=("base",))
        self.git("-C", r, "worktree", "add", "-q", "-b", "p1-01-a", wt)
        self.git("-C", wt, "commit", "-q", "--allow-empty", "-m", "l1")
        cp = r / ".plan/lanes/p1-01-a-checkpoint.md"
        self.write(cp, f"Final SHA: {self.rev(wt)}\n")
        self.touch(cp, -3600)
        self.py(
            RS, r / ".plan", "--phase", "1", "--repo", r, "--activate", session="rc1"
        )
        cev = '{"hook_event_name":"PostToolUse","session_id":"rc1","cwd":"/tmp","tool_name":"Read"}'
        self.hook_out(cev)
        self.git("-C", wt, "commit", "-q", "--allow-empty", "-m", "l2")
        self.write(cp, f"Final SHA: {self.rev(wt)}\n")
        self.touch(cp, -3600)
        self.rm(self.HOME / ".claude/dsp-routes/rc1.checked")
        out = self.hook_out(cev).out
        self.ok(
            "hook delta: a changed lane line is no cleared flag",
            grep(out, "changed between") and not grep(out, "flags cleared"),
            out,
        )


if __name__ == "__main__":
    unittest.main()
