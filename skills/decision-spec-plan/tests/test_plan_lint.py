"""plan_lint.py: a plan cut off inside a code fence indented under a step is unbalanced."""

import unittest

import support
from support import grep


class PlanLint(support.Sandbox):
    no_hooks = False

    def test_indented_unclosed_fence(self):
        L = self.T / "lint"
        self.write(
            L / "p4-01-cut.md",
            "**Goal:** a\n**Spec:** b\n**Depends on:** none\n## Task 1 — a\n- Produces: a\n"
            "- Consumes: none\n- [ ] Step 1: write the test\n  ```python\n  def test_a():\n"
            "      assert a() ==\n",
        )
        r = self.py("plan_lint.py", L)
        self.ok(
            "plan_lint: an indented unclosed fence is unbalanced",
            r.code == 1 and grep(r.out, r"unbalanced fences (1)"),
            f"exit {r.code}: {r.out}",
        )


if __name__ == "__main__":
    unittest.main()
