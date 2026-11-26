# SPDX-License-Identifier: MIT
"""The hold on the lead's own edits of the route's repository once the route is active.

PreToolUse denies a third file of its own, in the main checkout as in a lane's worktree,
written by an edit tool or by a Bash command; PostToolUse counts the files whose write
ran (F68).
"""

import json
import unittest
from pathlib import Path

from typing_extensions import override

import support
from support import RS, ev

# A diff of one file, src/e.py, as `git diff` writes it.
PATCH = """diff --git a/src/e.py b/src/e.py
--- a/src/e.py
+++ b/src/e.py
@@ -1 +1 @@
-x
+y
"""


class LeadEdits(support.Route):
    """Edits by the lead and by agents, by edit tools and Bash commands."""

    out: str = ""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the files the tests edit, an ignored dir and a patch outside R."""
        super().setUpClass()
        r, wt = cls.R, cls.WT
        for f in (
            *(r / f"src/{n}.py" for n in "acde"),
            *(wt / f"src/{n}.py" for n in "bd"),
            r / "build/out.log",
            cls.P / "plans/p.md",
        ):
            _ = cls.write(f, "x\n")
        _ = cls.write(r / ".gitignore", "build/\n")
        _ = cls.write(cls.T / "fix.patch", PATCH)

    @override
    def setUp(self) -> None:
        """Start each test with no file counted."""
        support.Sandbox.rm(self.HOME / ".claude/dsp-routes/s1.edits")

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

    def bash(self, name: str, command: str, cwd: Path) -> str:
        """The `name` hook event of the lead's Bash call of command in cwd."""
        return ev(
            name,
            "s1",
            f'"tool_name":"Bash","tool_input":{{"command":{json.dumps(command)}}},'
            f'"cwd":{json.dumps(str(cwd))}',
        )

    def decision(self, event: str) -> str:
        """The hold's PreToolUse decision on event, "" when it passes; output in out."""
        self.out = self.hook_out(event).out
        for kind in ("deny", "ask"):
            if support.hook_matches(kind + ":F68", self.out):
                return kind
        return ""

    def held(self, path: Path, tool: str = "Edit", agent: str = "") -> str:
        """The PreToolUse decision on an edit of path."""
        return self.decision(self.edit("PreToolUse", path, tool, agent))

    def ran(self, path: Path, tool: str = "Edit", agent: str = "") -> str:
        """The hold's decision, then the PostToolUse of the edit having run."""
        decision = self.held(path, tool, agent)
        self.unthrottle()
        _ = self.hook_out(self.edit("PostToolUse", path, tool, agent))
        return decision

    def ran_bash(self, command: str) -> str:
        """The hold's decision on a Bash command in R, then its PostToolUse."""
        decision = self.decision(self.bash("PreToolUse", command, self.R))
        self.unthrottle()
        _ = self.hook_out(self.bash("PostToolUse", command, self.R))
        return decision

    def set_run(self, run: str) -> None:
        """The route marker's run id set to run."""

        def change(m: support.Marker) -> None:
            m["run"] = run

        self.edit_marker(change)

    def test_a_third_file_is_denied(self) -> None:
        """Armed at activation: two files pass, a third is denied in any checkout."""
        r, wt, p = self.R, self.WT, self.P
        outside = self.write(self.T / "scratch/notes.md", "x\n")
        other = self.write(self.init_repo(self.T / "other") / "c.py", "x\n")
        self.ok("no budget yet", not self.budgets())
        self.ok("the first file passes", self.ran(r / "src/a.py") == "")
        # the planning dir, ignored files, files outside the repository and an agent's
        # edits are not the lead executing
        for path in (p / "plans/p.md", r / "build/out.log", outside, other):
            self.ok(f"{path.name} does not count", self.ran(path) == "")
        self.ok("an agent's edit passes", self.ran(r / "src/c.py", agent="a1") == "")
        self.ok("the second file passes", self.ran(wt / "src/b.py", "Write") == "")
        self.ok("a file already edited passes", self.ran(r / "src/a.py") == "")
        decision = self.held(wt / "src/d.py")
        self.ok("a third file in a worktree is denied", decision == "deny", self.out)
        self.ok("it cites the evidence", "126 edits" in self.out, self.out)
        decision = self.held(r / "src/c.py", "MultiEdit")
        self.ok("a third file in the main checkout is denied", decision == "deny")
        self.ok(
            "the deny names the rule and the group to dispatch",
            "main checkout as in a lane's worktree" in self.out
            and "`exec-` group" in self.out,
            self.out,
        )
        # a budget is no new count: the tally is the route's run's
        out = self.py(
            RS, "--budget", "w1", "--estimate", "10", "--groups", "2", session="s1"
        ).out
        self.ok("budget recorded", "budget recorded" in out, out)
        self.ok("a budget resets nothing", self.held(r / "src/c.py") == "deny")
        run = self.marker().get("run", "")
        self.set_run("another-run")
        try:
            self.ok("another run counts afresh", self.held(r / "src/c.py") == "")
        finally:
            self.set_run(run)

    def test_bash_writes_count(self) -> None:
        """A Bash command's writes to repository files count and are held as edits."""
        r, fix = self.R, self.T / "fix.patch"
        self.ok("a redirection's file passes", self.ran_bash("echo x > src/a.py") == "")
        self.ok("it counted: a second passes", self.ran(self.WT / "src/b.py") == "")
        self.ok("and a third edit is denied", self.held(r / "src/e.py") == "deny")
        for command, cwd in (
            ("echo x > src/e.py", r),
            ("echo x >> e.py", r / "src"),
            ("sed -i s/x/y/ src/e.py", r),
            ("printf x | tee -a src/e.py", r),
            ("cd src && perl -pi -e 's/x/y/' e.py", r),
            (f"git apply {fix}", r / "src"),
            (f"patch -p1 < {fix}", r),
        ):
            got = self.decision(self.bash("PreToolUse", command, cwd))
            self.ok(f"denied: {command}", got == "deny", self.out)
        # a file already counted, the planning dir, an ignored file, a command that
        # writes nothing and one the reader cannot read are not held
        deep = "echo $(" * 3000 + ")" * 3000 + " > src/e.py"
        for command in (
            "echo y > src/a.py",
            "echo x >> .plan/plans/p.md",
            "echo x > build/out.log",
            "sed s/x/y/ src/e.py",
            f"git apply --check {fix}",
            'echo x > "$F"',
            deep,
        ):
            self.ok(f"passes: {command[:40]}", self.ran_bash(command) == "", self.out)
        self.ok("none of them counted", self.held(r / "src/e.py") == "deny")
        self.ok("a counted file still passes", self.held(r / "src/a.py") == "")

    def test_a_rebase_counts_once_pushed(self) -> None:
        """A rebase or merge in progress passes until its branch reached a remote."""
        r, wt = self.R, self.WT
        for f in (r / "src/a.py", wt / "src/b.py"):
            _ = self.ran(f)
        rebase = r / ".git/worktrees/wt/rebase-merge"
        _ = self.write(rebase / "head-name", "refs/heads/feature\n")
        try:
            self.ok("a rebase edit passes unpushed", self.ran(wt / "src/d.py") == "")
            _ = self.git(
                "-C", r, "update-ref", "refs/remotes/origin/feature", self.MAIN
            )
            self.ok("pushed, it counts", self.held(wt / "src/d.py") == "deny", self.out)
        finally:
            support.Sandbox.rm(rebase)
        self.ok(
            "the unpushed edit was not counted", self.held(wt / "src/d.py") == "deny"
        )
        merge_head = self.write(r / ".git/MERGE_HEAD", self.MAIN + "\n")
        try:
            self.ok("a merge on unpushed main passes", self.held(r / "src/c.py") == "")
            _ = self.git("-C", r, "update-ref", "refs/remotes/origin/main", self.MAIN)
            self.ok("pushed main counts", self.held(r / "src/c.py") == "deny", self.out)
        finally:
            support.Sandbox.rm(merge_head)
            for ref in ("feature", "main"):
                _ = self.git("-C", r, "update-ref", "-d", f"refs/remotes/origin/{ref}")


if __name__ == "__main__":
    _ = unittest.main()
