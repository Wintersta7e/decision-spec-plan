"""The PostToolUse nudge when the lead edits the route's repository itself once Stage 5 began
(F68)."""

import json
import unittest

import support
from support import RS, ev

NUDGE = "edited .* files of the repository yourself"


class LeadEdits(support.Route):
    def edit(self, path, tool="Edit", agent=""):
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        extra = f',"agent_id":"{agent}"' if agent else ""
        return ev(
            "PostToolUse",
            "s1",
            f'"tool_name":"{tool}","tool_input":{{"{key}":{json.dumps(str(path))}}}{extra}',
        )

    def nudged(self, path, **kw):
        self.unthrottle()
        self.out = self.hook_out(self.edit(path, **kw)).out
        return support.grep(self.out, NUDGE, E=True)

    def test_edits_after_the_budget_are_nudged(self):
        R, WT, P = self.R, self.WT, self.P
        for f in (
            R / "src/a.py",
            WT / "src/b.py",
            R / "build/out.log",
            P / "plans/p.md",
        ):
            self.write(f, "x\n")
        self.write(R / ".gitignore", "build/\n")
        outside = self.T / "scratch/notes.md"
        self.write(outside, "x\n")
        other = self.init_repo(self.T / "other") / "c.py"
        self.write(other, "x\n")
        # before Stage 5 the lead writes plans and fixes them: nothing counts
        for _ in range(3):
            self.ok("no budget, no nudge", not self.nudged(R / "src/a.py"))
        out = self.py(
            RS, "--budget", "w1", "--estimate", "10", "--groups", "2", session="s1"
        ).out
        self.ok("budget recorded", "budget recorded" in out, out)
        self.ok("the first edit passes", not self.nudged(R / "src/a.py"))
        # the planning dir, ignored files, files outside the repository and an agent's edits
        # are not the lead executing
        for path in (P / "plans/p.md", R / "build/out.log", outside, other):
            self.ok(f"{path.name} does not count", not self.nudged(path))
        self.ok(
            "an agent's edit does not count",
            not self.nudged(R / "src/a.py", agent="a1"),
        )
        # a conflict resolved mid-merge in a worktree does not count
        merge_head = R / ".git/worktrees/wt/MERGE_HEAD"
        self.write(merge_head, "0" * 40 + "\n")
        self.ok("a mid-merge edit does not count", not self.nudged(WT / "src/b.py"))
        support.Sandbox.rm(merge_head)
        # the second edit, here in a lane's worktree, is nudged; then every tenth
        self.ok("the second edit is nudged", self.nudged(WT / "src/b.py", tool="Write"))
        self.ok("it cites the evidence", "F68" in self.out, self.out)
        hits = [self.nudged(R / "src/a.py", tool="MultiEdit") for _ in range(10)]
        self.ok("then every tenth edit", hits == [False] * 9 + [True], str(hits))
        # a new wave's budget starts the count again
        self.py(RS, "--budget", "w2", "--estimate", "5", "--groups", "1", session="s1")
        self.ok("a new budget resets", not self.nudged(R / "src/a.py"))
        self.ok("its second edit is nudged", self.nudged(R / "src/a.py"))


if __name__ == "__main__":
    unittest.main()
