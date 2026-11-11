# SPDX-License-Identifier: MIT
"""The nudge when the lead edits the route's repository itself once Stage 5 began.

The PostToolUse hook gives it (F68).
"""

import json
import unittest
from pathlib import Path

import support
from support import RS, ev

NUDGE = "edited .* files of the repository yourself"


class LeadEdits(support.Route):
    """Edits by the lead and by agents, before and after a wave's budget."""

    out: str = ""

    def edit(self, path: Path, tool: str = "Edit", agent: str = "") -> str:
        """The PostToolUse event of a tool's edit of path, by agent when given."""
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        extra = f',"agent_id":"{agent}"' if agent else ""
        return ev(
            "PostToolUse",
            "s1",
            f'"tool_name":"{tool}",'
            f'"tool_input":{{"{key}":{json.dumps(str(path))}}}{extra}',
        )

    def nudged(self, path: Path, tool: str = "Edit", agent: str = "") -> bool:
        """Whether the hook nudges on that edit; its output is kept in out."""
        self.unthrottle()
        self.out = self.hook_out(self.edit(path, tool, agent)).out
        return support.grep(self.out, NUDGE, E=True)

    def test_edits_after_the_budget_are_nudged(self) -> None:
        """The second edit after a budget is nudged, then every tenth."""
        r, wt, p = self.R, self.WT, self.P
        for f in (
            r / "src/a.py",
            wt / "src/b.py",
            r / "build/out.log",
            p / "plans/p.md",
        ):
            _ = self.write(f, "x\n")
        _ = self.write(r / ".gitignore", "build/\n")
        outside = self.T / "scratch/notes.md"
        _ = self.write(outside, "x\n")
        other = self.init_repo(self.T / "other") / "c.py"
        _ = self.write(other, "x\n")
        # before Stage 5 the lead writes plans and fixes them: nothing counts
        for _ in range(3):
            self.ok("no budget, no nudge", not self.nudged(r / "src/a.py"))
        out = self.py(
            RS, "--budget", "w1", "--estimate", "10", "--groups", "2", session="s1"
        ).out
        self.ok("budget recorded", "budget recorded" in out, out)
        self.ok("the first edit passes", not self.nudged(r / "src/a.py"))
        # the planning dir, ignored files, files outside the repository and an agent's
        # edits are not the lead executing
        for path in (p / "plans/p.md", r / "build/out.log", outside, other):
            self.ok(f"{path.name} does not count", not self.nudged(path))
        self.ok(
            "an agent's edit does not count",
            not self.nudged(r / "src/a.py", agent="a1"),
        )
        # a conflict resolved mid-merge in a worktree does not count
        merge_head = r / ".git/worktrees/wt/MERGE_HEAD"
        _ = self.write(merge_head, "0" * 40 + "\n")
        self.ok("a mid-merge edit does not count", not self.nudged(wt / "src/b.py"))
        support.Sandbox.rm(merge_head)
        # the second edit, here in a lane's worktree, is nudged; then every tenth
        self.ok("the second edit is nudged", self.nudged(wt / "src/b.py", tool="Write"))
        self.ok("it cites the evidence", "F68" in self.out, self.out)
        hits = [self.nudged(r / "src/a.py", tool="MultiEdit") for _ in range(10)]
        self.ok("then every tenth edit", hits == [False] * 9 + [True], str(hits))
        # a new wave's budget starts the count again
        _ = self.py(
            RS, "--budget", "w2", "--estimate", "5", "--groups", "1", session="s1"
        )
        self.ok("a new budget resets", not self.nudged(r / "src/a.py"))
        self.ok("its second edit is nudged", self.nudged(r / "src/a.py"))


if __name__ == "__main__":
    _ = unittest.main()
