"""criteria_check.py: a `# comment` in a fenced block does not end the acceptance section, and
only the test cell names a test: a spec path or a type's `::` path in a notes column is no test."""

import unittest

import support
from support import grep


class CriteriaCheck(support.Sandbox):
    no_hooks = False

    def test_criteria(self):
        C = self.T / "crit"
        self.write(
            C / "spec/38-auth.md",
            "# 38 Auth\n## Acceptance criteria\n1. **AC-P4-38-1** login works\n"
            "2. **AC-P4-38-2** logout works, checked with:\n```bash\n# start the server first\n"
            "./run.sh\n```\n3. **AC-P4-38-3** a session expires after 30 minutes\n"
            "4. **AC-P4-38-4** five failures lock the account\n## Notes\n",
        )
        (C / "plans").mkdir(parents=True)
        r = self.py("criteria_check.py", C / "spec", "--phase", "4", "--sections", "38")
        self.ok(
            "criteria_check: a fenced # comment does not end the section",
            r.code == 0 and grep(r.out, "^§38 +4 +4  ok$", E=True),
            f"exit {r.code}: {r.out}",
        )
        self.write(
            C / "spec/39-sessions.md",
            "# 39 Sessions\n## Acceptance criteria\n1. **AC-P4-39-1** a\n2. **AC-P4-39-2** b\n"
            "3. **AC-P4-39-3** c\n",
        )
        self.write(
            C / "plans/p4-01-auth.md",
            "# p4-01-auth\n## Task 1: sessions\n| Id | Task | Test file | Notes |\n"
            "|---|---|---|---|\n| AC-P4-39-1 | 1 | `tests/session_test.py` | |\n"
            "| AC-P4-39-2 | 1 | — | per `spec/39-sessions.md` |\n"
            "| AC-P4-39-3 | 1 | — | calls `Session::end` |\n",
        )
        r = self.py(
            "criteria_check.py",
            C / "spec",
            "--phase",
            "4",
            "--sections",
            "39",
            "--plans",
            C / "plans",
        )
        self.ok(
            "criteria_check: only the test cell names a test",
            r.code == 1
            and grep(r.out, "1 of 3 criteria mapped to a task and a test")
            and grep(r.out, "NO TEST FILE: AC-P4-39-2, AC-P4-39-3$"),
            f"exit {r.code}: {r.out}",
        )
        # a table row's id may be bold around code; colocated pytest files and .Tests projects
        # are tests
        self.write(
            C / "spec/45-parse.md",
            "# 45 Parsing\n## Acceptance criteria\n| Id | Criterion |\n|---|---|\n"
            "| **`AC-P4-45-1`** | empty input |\n| **`AC-P4-45-2`** | one row |\n",
        )
        self.write(
            C / "plans45/p4-02-parse.md",
            "# p4-02\n| Id | Task | Test file |\n|---|---|---|\n"
            "| AC-P4-45-1 | 1 | `src/parser/test_parse.py` |\n"
            "| AC-P4-45-2 | 1 | `MyApp.Tests/ParserTests.cs` |\n\n## Task 1 — parse\n",
        )
        r = self.py(
            "criteria_check.py",
            C / "spec",
            "--phase",
            "4",
            "--sections",
            "45",
            "--plans",
            C / "plans45",
        )
        self.ok(
            "criteria_check: bold-code table ids, colocated and .Tests test paths",
            r.code == 0 and grep(r.out, "2 of 2 criteria mapped"),
            f"exit {r.code}: {r.out}",
        )


if __name__ == "__main__":
    unittest.main()
