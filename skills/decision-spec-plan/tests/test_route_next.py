# SPDX-License-Identifier: MIT
"""`route_state.py --next`: the Agent call of each lane that can take a group now.

A lane mid-plan starts at its checkpoint's `Next task:`, a queued one at its plan's
first task with the worktree still to add; a lane waiting on an unmerged plan, one with
an agent out, and a checkpoint with no `Next task:` line get the reason instead. No call
is printed while the group brief is missing or keeps an ADAPT slot.
"""

import json
import unittest
from pathlib import Path
from typing import cast

from typing_extensions import override

import support
from support import RS, jline

REFUSED = 2  # --next with no usable brief
INDEX = """# Phase 1 plans

| Plan | Wave | Depends on |
|---|---|---|
| p1-01 | 1 | — |
| p1-02 | 1 | — |
| p1-03 | 2 | p1-01 |
| p1-04 | 1 | — |
"""


def plan(tasks: int) -> str:
    """A plan with that many tasks."""
    return "# Plan\n\n" + "".join(
        f"## Task {n}\n\nWork.\n\n" for n in range(1, tasks + 1)
    )


class _Next(support.Route):
    """`--next` and its printed calls, for the classes below."""

    def next_(self, *extra: object) -> support.Result:
        """`--next` of phase 1 on R, by session s1."""
        return self.py(
            RS, self.P, "--phase", "1", "--repo", self.R, "--next", *extra, session="s1"
        )

    def calls(self, out: str) -> dict[str, dict[str, object]]:
        """The printed Agent calls by name."""
        found = (
            cast("dict[str, object]", json.loads(ln))
            for ln in out.splitlines()
            if ln.startswith("  {")
        )
        return {str(c["name"]): c for c in found}


class Next(_Next):
    """Phase 1 of R: four plans, lane p1-01 mid-plan on its own branch."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the plans and lane p1-01's commit and checkpoint."""
        super().setUpClass()
        _ = cls.write(cls.P / "plans/p1-00-index.md", INDEX)
        for i, n in (("01", 3), ("02", 7), ("03", 1), ("04", 2)):
            _ = cls.write(cls.P / f"plans/p1-{i}-x.md", plan(n))
        cls.LANE: Path = cls.T / "repo-p1-01"
        _ = cls.git("-C", cls.R, "worktree", "add", "-q", "-b", "p1-01", cls.LANE)
        _ = cls.write(cls.LANE / "a.txt", "a\n")
        _ = cls.git("-C", cls.LANE, "add", "a.txt")
        _ = cls.git("-C", cls.LANE, "commit", "-qm", "feat: task 2")
        sha = cls.rev(cls.LANE)
        _ = cls.write(
            cls.P / "lanes/p1-01-checkpoint.md",
            f"Tasks 1-2 done.\nNext task: 3\nFinal SHA: {sha}\n",
        )
        _ = cls.write(
            cls.P / "lanes/p1-04-checkpoint.md", f"Task 1 done.\nFinal SHA: {sha}\n"
        )
        _ = cls.write(cls.LEAD, jline({"type": "user"}) + "\n")

    def agent(self, name: str, *, ended: bool) -> None:
        """A subagent transcript of the lead's, by name, finished or still working."""
        sub = self.LEAD.parent / "s1/subagents"
        stop = "end_turn" if ended else "tool_use"
        _ = self.write(sub / f"agent-{name}.meta.json", json.dumps({"name": name}))
        _ = self.write(
            sub / f"agent-{name}.jsonl",
            jline({"type": "assistant", "message": {"stop_reason": stop}}) + "\n",
        )

    def test_next(self) -> None:
        """Each lane gets its call or the reason it takes none."""
        brief = self.P / "GROUP-BRIEF-p1.md"
        r = self.next_()
        self.ok(
            "no brief, no call",
            r.code == REFUSED and "GROUP-BRIEF-p1.md" in r.out,
            r.out,
        )
        _ = self.write(brief, "# brief\n\u2039ADAPT: commit rules\u203a\n")
        r = self.next_()
        self.ok(
            "an ADAPT slot left, no call", r.code == REFUSED and "keeps an" in r.out
        )
        _ = self.write(brief, "# brief\nCommit as `type: subject`.\n")

        r = self.next_("--group-size", "2")
        calls = self.calls(r.out)
        mid = calls.get("exec-p1-01-g1", {})
        prompt = str(mid.get("prompt", ""))
        self.ok(
            "a lane mid-plan starts at Next task, and its last task runs the gate",
            r.code == 0
            and mid.get("subagent_type") == "decision-spec-plan:dsp-deep"
            and mid.get("run_in_background") is True
            and "Your tasks: 3." in prompt
            and "the plan's last" in prompt
            and str(self.LANE) in prompt
            and str(brief) in prompt
            and "the previous group's" in prompt,
            r.out,
        )
        queued = str(calls.get("exec-p1-02-g1", {}).get("prompt", ""))
        self.ok(
            "a queued lane starts at task 1 for the group size, its worktree to add",
            "Your tasks: 1, 2." in queued
            and "the plan's last" not in queued
            and "none yet" in queued
            and f"git worktree add {self.T / 'repo-p1-02'} -b p1-02 {self.MAIN}`"
            in r.out,
            r.out,
        )
        self.ok(
            "two calls, each with its ETA",
            set(calls) == {"exec-p1-01-g1", "exec-p1-02-g1"}
            and r.out.count("ETA exec-p1-0") == len(calls),
            r.out,
        )
        self.ok("a lane waiting on a plan", "p1-03: waits for p1-01" in r.out, r.out)
        self.ok(
            "a checkpoint with no Next task line",
            "p1-04: p1-04-checkpoint.md has no `Next task: <n>` line" in r.out,
            r.out,
        )

        self.agent("exec-p1-02-g1", ended=False)
        r = self.next_()
        self.ok(
            "an agent out holds its lane",
            "p1-02: out: exec-p1-02-g1" in r.out
            and "exec-p1-02-g" not in str(self.calls(r.out)),
            r.out,
        )
        self.agent("exec-p1-02-g1", ended=True)
        self.ok(
            "once it ended, the next group is g2",
            "exec-p1-02-g2" in self.calls(self.next_().out),
        )

    def test_lane_dir(self) -> None:
        """A repo on a Windows drive gets its lane worktree on WSL's own disk."""
        from dsp_route.next_groups import lane_dir

        cases = {
            "/mnt/c/src/app": Path.home() / "dsp-worktrees/app-p1-01",
            "/mnt/d/work/app": Path.home() / "dsp-worktrees/app-p1-01",
            "/mnt/wsl/app": Path("/mnt/wsl/app-p1-01"),
            "/home/u/app": Path("/home/u/app-p1-01"),
        }
        for top, want in cases.items():
            got = lane_dir(Path(top), "p1-01")
            self.ok(f"{top}: {got}", got == want, f"want {want}")


class NextGreen(_Next):
    """Lane p1-01 green at its checkpoint; p1-02 a wave later with no Depends on."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the plans, the brief, and lane p1-01's commit, checkpoint and gate."""
        super().setUpClass()
        _ = cls.write(
            cls.P / "plans/p1-00-index.md",
            "| Plan | Wave | Depends on |\n|---|---|---|\n"
            "| p1-01 | 1 | — |\n| p1-02 | 2 | — |\n",
        )
        for i, n in (("01", 3), ("02", 2)):
            _ = cls.write(cls.P / f"plans/p1-{i}-x.md", plan(n))
        _ = cls.write(cls.P / "GROUP-BRIEF-p1.md", "# brief\n")
        lane = cls.T / "repo-p1-01"
        _ = cls.git("-C", cls.R, "worktree", "add", "-q", "-b", "p1-01", lane)
        _ = cls.write(lane / "a.txt", "a\n")
        _ = cls.git("-C", lane, "add", "a.txt")
        _ = cls.git("-C", lane, "commit", "-qm", "feat: task 2")
        cls.SHA: str = cls.rev(lane)
        _ = cls.write(
            cls.P / "lanes/p1-01-gate.log", f"sha={cls.SHA} dirty=0\nexit=0\n"
        )
        _ = cls.write(cls.LEAD, jline({"type": "user"}) + "\n")

    def checkpoint(self, after: str) -> None:
        """Lane p1-01's checkpoint, its `Next task:` line saying after."""
        _ = self.write(
            self.P / "lanes/p1-01-checkpoint.md",
            f"Tasks 1-2 done.\nNext task: {after}\nFinal SHA: {self.SHA}\n",
        )

    def test_green(self) -> None:
        """A green lane with a task left gets its call; with none it is ready."""
        self.checkpoint("3")
        r = self.next_()
        mid = str(self.calls(r.out).get("exec-p1-01-g1", {}).get("prompt", ""))
        self.ok("green with a next task: its call", "Your tasks: 3." in mid, r.out)
        self.ok(
            "a later wave waits for an open earlier one",
            "p1-02: waits for p1-01" in r.out and "exec-p1-02" not in r.out,
            r.out,
        )
        self.checkpoint("none")
        r = self.next_()
        self.ok(
            "green with none left: ready, no call",
            "p1-01: green gate" in r.out and not self.calls(r.out),
            r.out,
        )
        # at rung S with no plan index, the one plan is the index
        self.rm(self.P / "plans/p1-00-index.md")
        self.rm(self.P / "plans/p1-02-x.md")
        self.checkpoint("3")
        r = self.next_("--rung", "S")
        mid = str(self.calls(r.out).get("exec-p1-01-g1", {}).get("prompt", ""))
        self.ok("at S the one plan is read", "Your tasks: 3." in mid, r.out)


if __name__ == "__main__":
    _ = unittest.main()
