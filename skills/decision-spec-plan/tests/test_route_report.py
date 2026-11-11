# SPDX-License-Identifier: MIT
"""`route_state.py`'s report: lanes, sections, base drift, odd inputs and lane deltas.

Lanes and how each merged, spec sections, base drift, odd inputs, lanes that moved past
their merged SHA (F41), and the hook's delta on a changed lane line.
"""

import shutil
import unittest

from typing_extensions import override

import support
from support import RS, ev, grep


def x_text(n: int) -> str:
    """A text of n x characters."""
    return "x" * n


class Lanes(support.Route):
    """Final SHA, merged by ancestry, by patch, by the integrator's record; open lanes.

    An open lane's line too.
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the gate logs and the lane checkpoint the report reads."""
        super().setUpClass()
        lanes = cls.P / "lanes"
        # the main gate logs section 152 left behind
        _ = cls.write(lanes / "red-gate.log", f"sha={cls.MAIN} dirty=0\n...\nexit=1\n")
        _ = cls.write(
            lanes / "dirty-gate.log", f"sha={cls.MAIN} dirty=3\n...\nexit=0\n"
        )
        _ = cls.write(
            lanes / "wave1-int-gate.log", f"sha={cls.MAIN} dirty=0\nok\nexit=0\n"
        )
        # the lane checkpoint section 846 wrote
        _ = cls.write(
            lanes / "p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {cls.MAIN}\n"
        )

    def report(self, *extra: object) -> str:
        """route_state.py's report on phase 1 of R, plus extra."""
        return self.py(RS, self.P, "--phase", "1", "--repo", self.R, *extra).out

    def test_lanes(self) -> None:
        """How each lane merged, then an open lane's line and the hook's delta."""
        repo, plan, wt, main_sha = self.R, self.P, self.WT, self.MAIN
        lanes = plan / "lanes"
        _ = self.git("-C", wt, "commit", "-q", "--allow-empty", "-m", "lane-a")
        _ = self.write(wt / "f.txt", "x\n")
        _ = self.git("-C", wt, "add", "f.txt")
        _ = self.git("-C", wt, "commit", "-q", "-m", "lane-b")
        f2 = self.rev(wt)
        _ = self.git("-C", repo, "cherry-pick", f2)
        _ = self.write(
            lanes / "p1-02-checkpoint.md",
            f"Final SHA: {f2}\nnote: older commit {main_sha[:7]}\n",
        )
        out = self.report("--all")
        self.ok(
            "Final SHA used, rebased lane merged by patch",
            grep(out, f"p1-02 .*{f2[:7]}[0-9a-f]* merged (by patch)"),
            out,
        )
        self.ok(
            "ancestor lane merged; main's worktree not counted",
            grep(out, "p1-01 .*merged") and grep(out, "1 lane worktrees"),
            out,
        )
        _ = self.write(wt / "g.txt", "fixup\n")
        _ = self.git("-C", wt, "add", "g.txt")
        _ = self.git("-C", wt, "commit", "-q", "-m", "fixup! lane-b")
        f3 = self.rev(wt)
        _ = self.write(repo / "g.txt", "squashed\n")
        _ = self.git("-C", repo, "add", "g.txt")
        _ = self.git("-C", repo, "commit", "-q", "-m", "squashed")
        sq = self.rev(repo)
        _ = self.write(lanes / "p1-03-checkpoint.md", f"Final SHA: {f3}\n")
        out = self.report("--all")
        self.ok(
            "squashed lane without a record: not merged",
            grep(out, "p1-03 .*not merged"),
            out,
        )
        _ = self.write(
            lanes / "wave1-integration.md",
            f"# wave 1\nMerged p1-03 `{f3[:9]}` → `{sq[:9]}`\n",
        )
        out = self.report("--all")
        self.ok(
            "squashed lane merged per the integrator's record",
            grep(out, f"p1-03 .*merged as {sq[:9]} (wave1-integration.md)"),
            out,
        )
        self.ok(
            "no Final SHA flag when present",
            not grep(out, "no `Final SHA:` line"),
            out,
        )
        # a merged lane's long checkpoint: no next group reads it, so no
        # length flag (F76)
        _ = self.write(
            lanes / "p1-05-checkpoint.md",
            f"Final SHA: {main_sha}\n" + "".join(f"{i}\n" for i in range(1, 41)),
        )
        out = self.report("--all")
        self.ok(
            "no length flag on a merged lane's checkpoint",
            grep(out, "p1-05 .*merged")
            and not grep(out, "checkpoint over 35 lines *lanes/p1-05"),
            out,
        )
        self.rm(lanes / "p1-05-checkpoint.md")
        self.open_lane()

    def open_lane(self) -> None:
        """An open lane's line is the lead's check of a return (F80).

        Lanes are found whatever their name, never another phase's.
        """
        repo, main_sha = self.R, self.MAIN
        lanes = self.P / "lanes"
        wt2 = self.T / "wt2"
        _ = self.git("-C", repo, "worktree", "add", "-q", "-b", "fix-ui", wt2, "main")
        _ = self.write(wt2 / "a.txt", "a\n")
        _ = self.git("-C", wt2, "add", "a.txt")
        _ = self.git(
            "-C", wt2, "commit", "-q", "-m", "ui: a", "-m", "Co-Authored-By: t"
        )
        fx = self.rev(wt2)
        _ = self.write(lanes / "fix-ui-checkpoint.md", f"Final SHA: {fx}\n")
        _ = self.write(lanes / "p2-01-checkpoint.md", f"Final SHA: {main_sha}\n")
        _ = self.write(lanes / "fix-ui-rulings.md", x_text(13000))
        _ = self.write(lanes / "fix-ui-rulings-archive.md", x_text(20000))
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
        # an open lane's rulings file every group reads whole, past 12 KB; never
        # its archive (F67)
        self.ok(
            "an open lane's rulings file over 12 KB is flagged, its archive is not",
            grep(out, "rulings over 12 KB *lanes/fix-ui-rulings.md (13 KB")
            and not grep(out, "rulings-archive.md ("),
            out,
        )
        # a CI harness's log runs only that suite: no full gate, as push_guard.py reads
        # it
        _ = self.write(
            lanes / "fix-ui-it-gate.log", f"sha={fx} dirty=0\nharness=it\nok\nexit=0\n"
        )
        out = self.report()
        self.ok(
            "the lane line: a harness log is no full gate",
            grep(out, "fix-ui .* · no gate log at this SHA · "),
            out,
        )
        self.rm(lanes / "fix-ui-it-gate.log")
        _ = self.write(lanes / "fix-ui-gate.log", f"sha={fx} dirty=0\nok\nexit=0\n")
        _ = self.write(wt2 / "a.txt", "b\n", mode="a")
        out = self.report()
        self.ok(
            "the lane line: gate at its SHA, uncommitted work",
            grep(
                out,
                "fix-ui .* · gate exit=0 · "
                "trailers Co-Authored-By ×1 · "
                "1 uncommitted in its worktree$",
            ),
            out,
        )
        self.unthrottle()
        _ = self.hook("report", ev("SessionStart", "s1", '"source":"compact"'))
        _ = self.git("-C", wt2, "commit", "-q", "-am", "ui: b")
        _ = self.write(lanes / "fix-ui-checkpoint.md", f"Final SHA: {self.rev(wt2)}\n")
        self.unthrottle()
        _ = self.hook(
            r"/changed between [\s\S]*fix-ui +[0-9a-f]+ not merged · 2 commits · "
            r"no gate log at this SHA/",
            ev("PostToolUse", "s1", '"tool_name":"Bash"'),
        )


class Sections(support.Route):
    """--sections: a closed range with a pending section, an open range."""

    def test_sections(self) -> None:
        """An open range counts every section; a closed one lists the pending one."""
        plan = self.P
        _ = self.write(plan / "spec/01-scope.md", "x\n")
        _ = self.write(plan / "spec/02-core.md", "x\n")
        out = self.py(RS, plan, "--phase", "1", "--sections", "1-").out
        self.ok(
            "--sections 1- counts every section from §1",
            grep(out, "spec       2 sections from §1"),
            out,
        )
        out = self.py(RS, plan, "--phase", "1", "--sections", "1-3").out
        self.ok(
            "--sections 1-3 lists the pending one",
            grep(out, "spec       2/3 sections (pending §3)"),
            out,
        )


class BaseDrift(support.Sandbox):
    """The base or an assumed branch moved since the decision index named it (F91)."""

    def test_base_drift(self) -> None:
        """Nothing moved, then the base moved and an assumed branch merged into it."""
        base = self.init_repo(self.T / "base", commits=("base",))
        _ = self.git("-C", base, "branch", "api")
        b0 = self.rev(base, "main")
        _ = self.write(
            base / ".plan/decisions/phase1/00-index.md",
            f"# Phase 1\n> **Base**: `main` at `{b0}`\n"
            f"> **Assumes**: `api` at `{b0[:12]}` — its new endpoints\n"
            f"> **Assumes**: `gone` at `{b0}`\n",
        )
        out = self.py(RS, base / ".plan", "--phase", "1", "--repo", base).out
        self.ok(
            "base drift: nothing moved, one assumed ref gone",
            not grep(out, r"base moved\|assumed ref moved")
            and grep(out, f"assumes ref gone *gone (recorded at {b0[:9]})"),
            out,
        )
        _ = self.git("-C", base, "checkout", "-q", "api")
        _ = self.git("-C", base, "commit", "-q", "--allow-empty", "-m", "endpoint")
        _ = self.git("-C", base, "checkout", "-q", "main")
        _ = self.git("-C", base, "merge", "-q", "--no-ff", "-m", "merge", "api")
        out = self.py(RS, base / ".plan", "--phase", "1", "--repo", base).out
        self.ok(
            "base drift: the base moved and an assumed branch merged into it",
            grep(out, f"base moved *main 2 commits past {b0[:9]}")
            and grep(
                out,
                f"assumed ref moved *api {b0[:9]} → [0-9a-f]\\{{9\\}}, "
                "merged into main",
            ),
            out,
        )


class OddInputs(support.Sandbox):
    """Squashed lanes in backticks, other phases' logs, CRs, odd bytes and repos.

    A squashed lane named in backticks, another phase's gate log, a carriage return
    before exit=, a non-UTF-8 byte, an en dash, a detached master repo.
    """

    def test_odd_inputs(self) -> None:
        """The report reads each odd input as the lead means it."""
        tmp = self.T
        srepo = self.init_repo(tmp / "srepo")
        _ = self.git("-C", srepo, "checkout", "-q", "-b", "p1-01")
        for f in ("a", "b"):
            _ = self.write(srepo / f, f"{f}\n")
            _ = self.git("-C", srepo, "add", f)
            _ = self.git("-C", srepo, "commit", "-q", "-m", f)
        lane = self.rev(srepo)
        _ = self.git("-C", srepo, "checkout", "-q", "main")
        _ = self.git("-C", srepo, "merge", "-q", "--squash", "p1-01")
        _ = self.git("-C", srepo, "commit", "-q", "-m", "squash")
        _ = self.git("-C", srepo, "branch", "-q", "-D", "p1-01")
        splan = srepo / ".plan"
        (splan / "lanes").mkdir(parents=True)
        (splan / "decisions/phase1").mkdir(parents=True)
        _ = self.write(splan / "lanes/p1-01-checkpoint.md", f"Final SHA: {lane}\n")
        short = self.git("-C", srepo, "rev-parse", "--short=9", "main")
        _ = self.write(
            splan / "lanes/wave1-integration.md",
            f"- Merged `p1-01` `{lane[:9]}` → `{short}`\n",
        )
        _ = self.write(
            splan / "lanes/p2-03-gate.log", f"sha={'a' * 40} dirty=0\nexit=1\n"
        )
        _ = self.write(
            splan / "lanes/wave1-gate.log",
            f"sha={self.rev(srepo, 'main')} dirty=0\nprogress 100%\rexit=0\n",
        )
        _ = self.write_bytes(
            splan / "decisions/phase1/00-index.md", b"| **D1** | Caf\xe9 |\n"
        )
        out = self.py(
            RS,
            splan,
            "--phase",
            "1",
            "--repo",
            srepo,
            "--sections",
            "1–2",
            merge=True,
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
        drepo = self.init_repo(tmp / "drepo", branch="master", commits=("one", "lane"))
        _ = self.write(
            drepo / ".plan/lanes/p1-01-checkpoint.md",
            f"Final SHA: {self.rev(drepo)}\n",
        )
        _ = self.git("-C", drepo, "checkout", "-q", "--detach")
        out = self.py(RS, drepo / ".plan", "--phase", "1", "--repo", drepo).out
        self.ok(
            "report: a detached master repo with no origin uses master",
            grep(out, "1 merged into master") and not grep(out, "does not exist"),
            out,
        )


class BaseDriftMergedAndUpstream(support.Sandbox):
    """An assumed branch merged without moving; the base's upstream moved (F91).

    The upstream moved on a fetch.
    """

    def test_merged_and_upstream(self) -> None:
        """An assumed branch merged as it was, and an upstream fetched, not pulled."""
        tmp = self.T
        base2 = self.init_repo(tmp / "base2", commits=("base",))
        _ = self.git("-C", base2, "checkout", "-q", "-b", "feat")
        _ = self.git("-C", base2, "commit", "-q", "--allow-empty", "-m", "f")
        f0 = self.rev(base2, "feat")
        _ = self.git("-C", base2, "checkout", "-q", "main")
        _ = self.write(
            base2 / ".plan/decisions/phase1/00-index.md",
            f"> **Base**: `main` at `{self.rev(base2, 'main')}`\n"
            f"> **Assumes**: `feat` at `{f0}`\n",
        )
        _ = self.git("-C", base2, "merge", "-q", "--no-ff", "-m", "merge", "feat")
        out = self.py(RS, base2 / ".plan", "--phase", "1", "--repo", base2).out
        self.ok(
            "base drift: an assumed branch merged without moving",
            grep(out, f"assumed ref merged *feat {f0[:9]} into main"),
            out,
        )
        clone = tmp / "clone"
        _ = self.git("clone", "-q", base2, clone)
        c0 = self.rev(clone, "main")
        _ = self.write(
            clone / ".plan/decisions/phase1/00-index.md",
            f"> **Base**: `main` at `{c0}`\n",
        )
        _ = self.git("-C", base2, "commit", "-q", "--allow-empty", "-m", "later")
        _ = self.git("-C", clone, "fetch", "-q")
        out = self.py(RS, clone / ".plan", "--phase", "1", "--repo", clone).out
        self.ok(
            "base drift: the base's upstream moved, fetched not pulled",
            grep(out, f"main@{{upstream}} 1 commits past {c0[:9]}", F=True),
            out,
        )


class LaneGitCalls(support.Sandbox):
    """The report's git calls do not grow with its merged lanes.

    The hook runs the report after a tool call; at two git calls a lane, a route with
    47 lane checkpoints on a slow drive spent 24 s in each.
    """

    def test_git_calls(self) -> None:
        """Eight merged lanes cost the report as many git calls as two."""
        tg = self.T / "calls"
        repo, log, wrapper = tg / "r", tg / "git.log", tg / "bin/git"
        _ = self.init_repo(repo, commits=("base",))
        _ = self.write(
            wrapper,
            f'#!/bin/sh\necho x >> "{log}"\nexec "{shutil.which("git")}" "$@"\n',
        )
        self.chmod_x(wrapper)
        env = {"PATH": f"{wrapper.parent}:{self.env['PATH']}"}

        def calls(lanes: range) -> tuple[int, str]:
            for i in lanes:
                _ = self.git("-C", repo, "commit", "-q", "--allow-empty", "-m", f"l{i}")
                _ = self.write(
                    tg / f"plan/lanes/p1-{i:02d}-checkpoint.md",
                    f"Final SHA: {self.rev(repo)}\n",
                )
            _ = self.write(log, "")
            out = self.py(RS, tg / "plan", "--phase", "1", "--repo", repo, env=env).out
            return len(log.read_text().splitlines()), out

        two, _ = calls(range(2))
        eight, out = calls(range(2, 8))
        self.ok(
            f"report: 8 merged lanes take as many git calls as 2 ({eight} vs {two})",
            eight == two and grep(out, "8 checkpoints .* 8 merged into main"),
            out,
        )

    def test_cherry_cache(self) -> None:
        """A lane's patch check runs once per main tip, and again once main moves."""
        tc = self.T / "cherry"
        repo, log, wrapper = tc / "r", tc / "git.log", tc / "bin/git"
        _ = self.init_repo(repo, commits=("base",))
        _ = self.write(
            wrapper,
            f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{shutil.which("git")}" "$@"\n',
        )
        self.chmod_x(wrapper)
        env = {"PATH": f"{wrapper.parent}:{self.env['PATH']}"}
        _ = self.git("-C", repo, "switch", "-q", "-c", "lane")
        _ = self.write(repo / "x", "x\n")
        _ = self.git("-C", repo, "add", "x")
        _ = self.git("-C", repo, "commit", "-q", "-m", "lane")
        lane = self.rev(repo)
        _ = self.git("-C", repo, "switch", "-q", "main")
        # main moved on: the pick below is a new commit, never the lane's own SHA
        _ = self.git("-C", repo, "commit", "-q", "--allow-empty", "-m", "main2")
        _ = self.write(tc / "plan/lanes/p1-01-checkpoint.md", f"Final SHA: {lane}\n")

        def run() -> tuple[int, str]:
            _ = self.write(log, "")
            out = self.py(
                RS, tc / "plan", "--phase", "1", "--repo", repo, "--all", env=env
            ).out
            return sum(" cherry " in ln for ln in log.read_text().splitlines()), out

        (first, _), (again, out) = run(), run()
        _ = self.git("-C", repo, "cherry-pick", lane)
        moved, picked = run()
        self.ok(
            f"report: one patch check per main tip ({first}, {again}, {moved})",
            (first, again, moved) == (1, 0, 1)
            and grep(out, "p1-01 .* not merged")
            and grep(picked, "p1-01 .* merged (by patch)"),
            f"{out}\n{picked}",
        )


class LaneMovedPastMerge(support.Sandbox):
    """F41: a lane's commits past its merged SHA that main lacks.

    A lane the integrator rebased and merged has none, though its tip is not the
    checkpoint's SHA.
    """

    def test_f41(self) -> None:
        """A rebased and merged lane has not moved; a later commit has."""
        tf = self.T / "f41"
        r, wt = tf / "r", tf / "wt"
        _ = self.init_repo(r, commits=("base",))
        _ = self.git("-C", r, "worktree", "add", "-q", "-b", "p1-01-a", wt)
        _ = self.write(wt / "x", "x\n")
        _ = self.git("-C", wt, "add", "x")
        _ = self.git("-C", wt, "commit", "-q", "-m", "lane")
        c1 = self.rev(wt)
        _ = self.write(r / "y", "y\n")
        _ = self.git("-C", r, "add", "y")
        _ = self.git("-C", r, "commit", "-q", "-m", "main2")
        _ = self.git("-C", wt, "rebase", "-q", "main")
        _ = self.git("-C", r, "merge", "-q", "--ff-only", "p1-01-a")
        cp = self.write(tf / "plan/lanes/p1-01-a-checkpoint.md", f"Final SHA: {c1}\n")
        self.touch(cp, -3600)

        def report() -> str:
            return self.py(
                RS, tf / "plan", "--phase", "1", "--repo", r, "--all", merge=True
            ).out

        out = report()
        self.ok(
            "report: a lane rebased and merged has not moved past its SHA",
            grep(out, "p1-01-a .*merged") and not grep(out, "F41"),
            out,
        )
        _ = self.write(wt / "z", "z\n")
        _ = self.git("-C", wt, "add", "z")
        _ = self.git("-C", wt, "commit", "-q", "-m", "late")
        out = report()
        self.ok(
            "report: a lane commit after its merge, missing from main, is flagged",
            grep(out, "lane moved past its merged SHA *p1-01-a (1 commits, F41)"),
            out,
        )
        # a red CI-harness run is reported like any gate log, though it is no full gate
        _ = self.write(
            tf / "plan/lanes/p1-01-a-gate-pg.log",
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
    """A rung-S route activated without --repo: no D file is pending.

    Its marker sits in the planning dir's repository, and its index rows are the
    decisions — no D file is pending (templates.md §1).
    """

    def test_rung_s_without_repo(self) -> None:
        """The report lists the index rows as the decisions, none pending."""
        sr = self.init_repo(self.T / "sr")
        _ = self.write(
            sr / ".plan/decisions/phase1/00-index.md", "| D1 | a |\n| D2 | b |\n"
        )
        _ = self.py(
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
            '{"hook_event_name":"PostToolUse","session_id":"rs1","cwd":"/tmp",'
            '"tool_name":"Read"}'
        ).out
        self.ok(
            "report: a rung-S route without --repo lists no D file as pending",
            grep(out, "decisions  0 D files (2 in the index)")
            and not grep(out, "pending"),
            out,
        )


class DeltaLaneLine(support.Sandbox):
    """The hook's delta: a lane line that changed is no cleared flag."""

    def test_changed_lane_line(self) -> None:
        """A lane's new commit changes its line; the delta does not call it cleared."""
        tc = self.T / "cl"
        r, wt = tc / "r", tc / "wt"
        _ = self.init_repo(r, commits=("base",))
        _ = self.git("-C", r, "worktree", "add", "-q", "-b", "p1-01-a", wt)
        _ = self.git("-C", wt, "commit", "-q", "--allow-empty", "-m", "l1")
        cp = r / ".plan/lanes/p1-01-a-checkpoint.md"
        _ = self.write(cp, f"Final SHA: {self.rev(wt)}\n")
        self.touch(cp, -3600)
        _ = self.py(
            RS, r / ".plan", "--phase", "1", "--repo", r, "--activate", session="rc1"
        )
        cev = (
            '{"hook_event_name":"PostToolUse","session_id":"rc1","cwd":"/tmp",'
            '"tool_name":"Read"}'
        )
        _ = self.hook_out(cev)
        _ = self.git("-C", wt, "commit", "-q", "--allow-empty", "-m", "l2")
        _ = self.write(cp, f"Final SHA: {self.rev(wt)}\n")
        self.touch(cp, -3600)
        self.rm(self.HOME / ".claude/dsp-routes/rc1.checked")
        out = self.hook_out(cev).out
        self.ok(
            "hook delta: a changed lane line is no cleared flag",
            grep(out, "changed between") and not grep(out, "flags cleared"),
            out,
        )


if __name__ == "__main__":
    _ = unittest.main()
