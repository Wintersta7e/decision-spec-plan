# SPDX-License-Identifier: MIT
"""plan_lint.py on unbalanced fences and the gate table.

A plan cut off inside a code fence indented under a step is unbalanced.
"""

import unittest
from typing import ClassVar

import support
from support import grep


class PlanLint(support.Sandbox):
    """plan_lint.py on plans written into the sandbox."""

    no_hooks: ClassVar[bool] = False

    def test_indented_unclosed_fence(self) -> None:
        """A plan cut off inside an indented code fence is unbalanced."""
        lint = self.T / "lint"
        _ = self.write(
            lint / "p4-01-cut.md",
            "**Goal:** a\n**Spec:** b\n**Depends on:** none\n## Task 1 — a\n"
            "- Produces: a\n"
            "- Consumes: none\n- [ ] Step 1: write the test\n  ```python\n"
            "  def test_a():\n"
            "      assert a() ==\n",
        )
        r = self.py("plan_lint.py", lint)
        self.ok(
            "plan_lint: an indented unclosed fence is unbalanced",
            r.code == 1 and grep(r.out, r"unbalanced fences (1)"),
            f"exit {r.code}: {r.out}",
        )

    def test_gate_table(self) -> None:
        """Each gate's minutes and where it runs; a long one never in a group.

        12.12M went on a gate that never completed.
        """
        gates = self.T / "gates"
        head = (
            "**Goal:** a\n**Spec:** b\n**Depends on:** none\n## Task 1 — a\n"
            "- Produces: a\n"
            "- Consumes: none\n- [ ] Step 1: write the test\n"
        )
        table = "## Gates\n| Gate | Command | Minutes | Runs |\n|---|---|---|---|\n"
        _ = self.write(gates / "p1-01-none.md", head)
        _ = self.write(
            gates / "p1-02-good.md",
            head + table + "| unit | `npm test` | 3 | group |\n"
            "| e2e | `npm run e2e` | ~45 min | `lead` |\n"
            "| matrix | three databases | 90 | CI |\n",
        )
        _ = self.write(
            gates / "p1-03-bad.md",
            head + table + "| e2e | `npm run e2e` | 45 | group |\n"
            "| lint | `npm run lint` | quick | group |\n"
            "| db | `make db` | 5 | laptop |\n",
        )
        r = self.py("plan_lint.py", gates)
        self.ok(
            "plan_lint: the gate table — missing, good, a long gate in a group, "
            "no minutes, "
            "no place",
            r.code == 1
            and grep(r.out, "p1-01-none.md .*no gate table")
            and grep(r.out, "p1-02-good.md .* ok$")
            and grep(r.out, "gate 'e2e' takes 45 min in a group (over 30)")
            and grep(r.out, "gate 'lint' has no minutes")
            and grep(r.out, "gate 'db' runs 'laptop', not group, lead or CI"),
            f"exit {r.code}: {r.out}",
        )
        r = self.py("plan_lint.py", gates, "--glob", "p1-03-*", "--group-minutes", "60")
        self.ok(
            "plan_lint --group-minutes: the group's own limit",
            not grep(r.out, "gate 'e2e' takes"),
            r.out,
        )


if __name__ == "__main__":
    _ = unittest.main()
