# SPDX-License-Identifier: MIT
"""The hold on the lead's own edits of the route's repository once Stage 5 began.

PreToolUse holds a third file of its own; PostToolUse counts the edits that ran (F68).
"""

import json
import unittest
from pathlib import Path

import support
from support import RS, ev


class LeadEdits(support.Route):
    """Edits by the lead and by agents, before and after a wave's budget."""

    out: str = ""

    def edit(self, name: str, path: Path, tool: str, agent: str) -> str:
        """The `name` hook event of a tool's edit of path, by agent when given."""
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        extra = f',"agent_id":"{agent}"' if agent else ""
        return ev(
            name,
            "s1",
            f'"tool_name":"{tool}",'
            f'"tool_input":{{"{key}":{json.dumps(str(path))}}}{extra}',
        )

    def held(self, path: Path, tool: str = "Edit", agent: str = "") -> str:
        """The PreToolUse decision on that edit, "" when it passes; output in out."""
        self.out = self.hook_out(self.edit("PreToolUse", path, tool, agent)).out
        for kind in ("deny", "ask"):
            if support.hook_matches(kind + ":F68", self.out):
                return kind
        return ""

    def ran(self, path: Path, tool: str = "Edit", agent: str = "") -> str:
        """The hold's decision, then the PostToolUse of the edit having run."""
        decision = self.held(path, tool, agent)
        self.unthrottle()
        _ = self.hook_out(self.edit("PostToolUse", path, tool, agent))
        return decision

    def test_a_third_file_is_held(self) -> None:
        """Two files of its own pass after a budget; a third is denied or asked."""
        r, wt, p = self.R, self.WT, self.P
        for f in (
            r / "src/a.py",
            r / "src/c.py",
            wt / "src/b.py",
            wt / "src/d.py",
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
        for f in (r / "src/a.py", r / "src/c.py", wt / "src/b.py"):
            self.ok("no budget, no hold", self.ran(f) == "")
        out = self.py(
            RS, "--budget", "w1", "--estimate", "10", "--groups", "2", session="s1"
        ).out
        self.ok("budget recorded", "budget recorded" in out, out)
        self.ok("the first file passes", self.ran(r / "src/a.py") == "")
        # the planning dir, ignored files, files outside the repository and an agent's
        # edits are not the lead executing
        for path in (p / "plans/p.md", r / "build/out.log", outside, other):
            self.ok(f"{path.name} does not count", self.ran(path) == "")
        self.ok("an agent's edit passes", self.ran(r / "src/c.py", agent="a1") == "")
        # a conflict resolved mid-merge in a worktree does not count
        merge_head = r / ".git/worktrees/wt/MERGE_HEAD"
        _ = self.write(merge_head, "0" * 40 + "\n")
        self.ok("a mid-merge edit does not count", self.ran(wt / "src/d.py") == "")
        support.Sandbox.rm(merge_head)
        self.ok("the second file passes", self.ran(wt / "src/b.py", "Write") == "")
        self.ok("a file already edited passes", self.ran(r / "src/a.py") == "")
        # a third file: a lane's worktree is its group's; the main checkout asks
        self.ok(
            "a third file in a worktree is denied", self.held(wt / "src/d.py") == "deny"
        )
        self.ok("it cites the evidence", "126 edits" in self.out, self.out)
        decision = self.held(r / "src/c.py", "MultiEdit")
        self.ok("a third file in the checkout asks", decision == "ask", self.out)
        # the user approved it: the edit ran, and the file passes from then on
        self.unthrottle()
        _ = self.hook_out(self.edit("PostToolUse", r / "src/c.py", "MultiEdit", ""))
        self.ok("an approved file passes", self.held(r / "src/c.py") == "")
        # a new wave's budget starts the count again
        _ = self.py(
            RS, "--budget", "w2", "--estimate", "5", "--groups", "1", session="s1"
        )
        self.ok("a new budget resets", self.ran(wt / "src/d.py") == "")


if __name__ == "__main__":
    _ = unittest.main()
