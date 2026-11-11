# SPDX-License-Identifier: MIT
"""test_check.py: a lane must not turn its gate green by testing less.

A lane that deletes a test file, drops a test or adds a skip turns its gate green by
testing less; the plan must name each deletion, and every skip goes to the lead.
"""

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

import support
from support import Result, grep

# test_check.py's exit code when the range changed nothing
NOTHING_TO_CHECK = 2
# the skip forms test_skip_forms writes: pytestmark, skipTest and [Ignore("…")]
SKIP_FORMS = 3


class TestCheck(support.Sandbox):
    """test_check.py on the diff of a range against the plans."""

    no_hooks: ClassVar[bool] = False

    def base(self, repo: Path, msg: str = "base") -> None:
        """Everything in repo committed with message msg."""
        _ = self.git("-C", repo, "add", "-A", ".")
        _ = self.git("-C", repo, "commit", "-q", "-m", msg)

    def check(self, plans: Path, rng: str, repo: Path) -> Result:
        """test_check.py on the range rng of repo against plans."""
        return self.py("test_check.py", plans, "--diff", rng, "--repo", repo)

    def tcrepo(self) -> Path:
        """A fresh repository with plans/ and repo/tests/ under a new directory."""
        tb = Path(tempfile.mkdtemp(prefix="tc.", dir=self.T))
        (tb / "plans").mkdir()
        (tb / "repo/tests").mkdir(parents=True)
        _ = self.git("init", "-q", "-b", "main", tb / "repo")
        return tb

    def tcrun(self, tb: Path, start: str = "HEAD~1") -> str:
        """test_check.py's output on start..HEAD of the repository tcrepo made."""
        return self.check(tb / "plans", f"{start}..HEAD", tb / "repo").out

    def test_deleted_dropped_skipped(self) -> None:
        """Deleted files, dropped tests and added skips; the plan names deletions."""
        tc = self.T / "tcheck"
        repo = tc / "repo"
        (tc / "plans").mkdir(parents=True)
        (repo / "tests").mkdir(parents=True)
        (repo / "src").mkdir(parents=True)
        plan = self.write(
            tc / "plans/p1-01-x.md",
            "# p1-01-x\n## File structure\n| `src/list.ts` | list |\n## Task 1\n",
        )
        _ = self.git("init", "-q", "-b", "main", repo)
        w = self.write
        _ = w(
            repo / "tests/test_names.py",
            "def test_merge():\n    assert 1\n    assert 11\n\n\n"
            "def test_split():\n    assert 2\n"
            "\n\ndef test_shift():\n    assert 4\n",
        )
        _ = w(repo / "src/list.test.ts", "it('sorts', () => {});\n")
        _ = w(repo / "tests/test_old.py", "def test_gone():\n    assert 3\n")
        _ = w(repo / "tests/test_moved.py", "def test_moves():\n    assert 5\n")
        _ = w(repo / "tests/test_loose.py", "def test_loose():\n    assert x == 1\n")
        _ = w(
            repo / "tests/seam.rs",
            '#[test]\nfn reads() {\n    let v = load().expect("loads");\n'
            "    // assert_eq!(v, 1) by construction\n    check(v);\n}\n",
        )
        _ = w(
            repo / "src/lib.rs",
            "fn one() -> u8 { 1 }\n\n#[test]\n"
            "fn adds() {\n    assert_eq!(one(), 1);\n}\n",
        )
        self.base(repo)
        _ = w(repo / "tests/test_names.py", "def test_merge():\n    assert 1\n")
        _ = w(repo / "tests/test_other.py", "def test_shift():\n    assert 4\n")
        _ = w(repo / "tests/test_loose.py", "def test_loose():\n    assert x\n")
        _ = w(
            repo / "tests/seam.rs", "#[test]\nfn reads() {\n    check(load_ok());\n}\n"
        )
        _ = w(repo / "src/list.test.ts", "it.skip('sorts', () => {});\n")
        _ = w(repo / "src/lib.rs", "fn one() -> u8 { [0, 1].iter().skip(1).sum() }\n")
        (repo / "tests/unit").mkdir()
        _ = self.git(
            "-C", repo, "mv", "tests/test_moved.py", "tests/unit/test_moved.py"
        )
        _ = self.git("-C", repo, "rm", "-q", "tests/test_old.py")
        self.base(repo, "lane")
        r = self.check(tc / "plans", "HEAD~1..HEAD", repo)
        out = r.out
        self.ok(
            "test_check: a deleted test file, two dropped tests, a dropped assertion "
            "and an added skip; moves, iter().skip and an assertion rewritten in place "
            "are not",
            r.code == 1
            and grep(out, "DELETED  tests/test_old.py", x=True)
            and grep(out, "REMOVED  test_split  tests/test_names.py", x=True)
            and grep(out, "REMOVED  adds  src/lib.rs", x=True)
            and grep(out, "^SKIP     src/list.test.ts:1 ")
            and grep(out, "FEWER    tests/test_names.py  1 fewer assertions", x=True)
            and not grep(
                out,
                r"test_merge\|test_shift\|test_gone\|test_moves\|lib.rs:"
                r"\|^REMOVED  sorts\|test_other\|test_loose\|seam.rs",
            ),
            f"exit {r.code}: {out}",
        )
        _ = self.write(
            plan,
            "Task 1 deletes `tests/test_old.py`, "
            "drops test_split and the `adds` test.\n",
            mode="a",
        )
        r = self.check(tc / "plans", "HEAD~1..HEAD", repo)
        self.ok(
            "test_check: deletions the plan names pass, a skip and a dropped assertion "
            "still go to the lead",
            r.code == 1
            and grep(r.out, "^SKIP     src/list.test.ts:1 ")
            and grep(r.out, "^FEWER    tests/test_names.py")
            and not grep(r.out, r"^DELETED\|^REMOVED"),
            f"exit {r.code}: {r.out}",
        )
        _ = w(repo / "src/list.test.ts", "it('sorts', () => {});\n")
        _ = w(
            repo / "tests/test_names.py",
            "def test_merge():\n    assert 1\n    assert 11\n",
        )
        self.base(repo, "unskip")
        r = self.check(tc / "plans", "HEAD~2..HEAD", repo)
        self.ok(
            "test_check: exit 0 when every change is named and nothing is skipped",
            r.code == 0,
            r.out,
        )
        r = self.check(tc / "plans", "HEAD..HEAD", repo)
        self.ok("test_check: an empty range fails", r.code == NOTHING_TO_CHECK, r.out)

    def test_renamed_out_and_quoted_path(self) -> None:
        """A test file renamed out of the test paths, and a path git quotes.

        A test file renamed out of the test paths stops running as surely as one
        deleted; a path git quotes (a `"` in it) keeps its own lines, never the previous
        file's.
        """
        tq = self.T / "tcheck2"
        repo = tq / "repo"
        (repo / "tests").mkdir(parents=True)
        _ = self.write(tq / "plans/p1-01-x.md", "# p1-01-x\n")
        _ = self.git("init", "-q", "-b", "main", repo)
        w = self.write
        _ = w(repo / "tests/test_hide.py", "def test_hidden():\n    assert 1\n")
        _ = w(
            repo / 'tests/test_q"x.py',
            "def test_kept():\n    assert 1\n\n\ndef test_quoted():\n    assert 2\n",
        )
        _ = w(repo / "tests/test_a.py", "def test_a():\n    assert 1\n")
        _ = w(
            repo / "tests/test sp.py",
            "def test_spaced():\n    assert 1\n\n\ndef test_other():\n    assert 2\n",
        )
        self.base(repo)
        (repo / "notes").mkdir()
        _ = self.git("-C", repo, "mv", "tests/test_hide.py", "notes/hide.txt")
        _ = w(repo / 'tests/test_q"x.py', "def test_kept():\n    assert 1\n")
        _ = w(repo / "tests/test_a.py", "def test_a():\n    assert 1\n    assert 3\n")
        _ = w(repo / "tests/test sp.py", "def test_other():\n    assert 2\n")
        self.base(repo, "lane")
        r = self.check(tq / "plans", "HEAD~1..HEAD", repo)
        self.ok(
            "test_check: a test file renamed out of the test paths, and a quoted path",
            r.code == 1
            and grep(r.out, "DELETED  tests/test_hide.py", x=True)
            and grep(r.out, 'REMOVED  test_quoted  tests/test_q"x.py', x=True)
            and grep(r.out, "REMOVED  test_spaced  tests/test sp.py", x=True)
            and not grep(r.out, r"test_a.py\|hide.txt"),
            f"exit {r.code}: {r.out}",
        )

    def test_acceptance_tests_read_only(self) -> None:
        """An acceptance test is read-only once written.

        A later commit that changes its lines — `== 3` loosened to `> 0` — goes to the
        lead, which no count of tests or assertions shows (F99); only the mapping
        table's rows, and only test files.
        """
        ta = self.T / "tcheck3"
        repo = ta / "repo"
        (repo / "tests").mkdir(parents=True)
        _ = self.write(
            ta / "plans/p1-01-x.md",
            "# p1-01-x\n| AC | Gate | Run |\n|---|---|---|\n"
            "| AC-P1-3-1 | full | `tests/test_unit.py` |"
            "\n\n| Id | Task | Test file |\n|---|---|---|\n"
            "| AC-P1-3-1 | 1 | `tests/test_ac.py::test_rule` |\n"
            "| AC-P1-3-2, -3 | 2 | `tests/test_pre.py` |\n| AC-P1-3-4 | 2 | manual |\n"
            "| AC-P1-3-5 | 2 | `src/lib.rs::tests::adds` |\n",
        )
        _ = self.git("init", "-q", "-b", "main", repo)
        w = self.write
        _ = w(repo / "src/lib.rs", "fn one() -> u8 { 1 }\n")
        _ = w(repo / "tests/test_pre.py", "def test_pre():\n    assert load() == []\n")
        _ = w(repo / "tests/test_unit.py", "def test_unit():\n    assert 1\n")
        self.base(repo)
        ac = w(
            repo / "tests/test_ac.py",
            "from m import total\n\n\ndef test_rule():\n    assert total(x) == 3\n",
        )
        self.base(repo, "task 1")
        # a test added beside it, its import widened: the import line changes, no
        # assertion does
        _ = w(ac, ac.read_text().replace("import total", "import more, total", 1))
        _ = w(ac, "\n\ndef test_more():\n    assert more(y) == 4\n", mode="a")
        _ = w(repo / "tests/test_unit.py", "def test_unit():\n    assert 2\n")
        self.base(repo, "task 2")
        _ = w(ac, ac.read_text().replace("== 3", "> 0", 1))
        pre = repo / "tests/test_pre.py"
        _ = w(pre, pre.read_text().replace("== []", "is not None", 1))
        _ = w(repo / "src/lib.rs", "fn one() -> u8 { 2 }\n")
        self.base(repo, "fix")
        c3 = self.git("-C", repo, "log", "-1", "--format=%h")
        r = self.check(ta / "plans", "HEAD~3..HEAD", repo)
        self.ok(
            "test_check: an acceptance test changed after it was written goes to the "
            "lead; its first commit and additions do not",
            r.code == 1
            and grep(r.out, f"EDITED   tests/test_ac.py  {c3}", x=True)
            and grep(r.out, f"EDITED   tests/test_pre.py  {c3}", x=True)
            and not grep(r.out, r"test_unit\|manual\|FEWER"),
            f"exit {r.code}: {r.out}",
        )
        r = self.check(ta / "plans", "HEAD~3..HEAD~1", repo)
        self.ok(
            "test_check: an acceptance test written and then added to passes",
            r.code == 0,
            r.out,
        )

    def test_redefined_test(self) -> None:
        """An assertion dropped beside a test's changed signature.

        The test is still there, so no REMOVED line covers the assertion.
        """
        tb = self.tcrepo()
        t = tb / "repo/tests/test_a.py"
        _ = self.write(t, "def test_x():\n    assert g() == 2\n    assert f() == 1\n")
        self.base(tb / "repo")
        _ = self.write(t, "def test_x(tmp_path):\n    assert f() == 1\n")
        self.base(tb / "repo", "sig")
        out = self.tcrun(tb)
        self.ok(
            "test_check: an assertion dropped in the hunk of a test re-defined under "
            "its name is counted",
            grep(out, "FEWER    tests/test_a.py  1 fewer assertions", x=True),
            out,
        )

    def test_skip_forms(self) -> None:
        """Skips written as pytestmark, skipTest and [Ignore("…")]."""
        tb = self.tcrepo()
        tests = tb / "repo/tests"
        w = self.write
        _ = w(tests / "test_a.py", "import pytest\n\n\ndef test_a():\n    assert a()\n")
        _ = w(
            tests / "test_b.py",
            "class T(unittest.TestCase):\n    def test_b(self):\n"
            "        self.assertTrue(b())\n",
        )
        _ = w(
            tests / "CTests.cs",
            "public class CTests {\n    [Test]\n"
            "    public void Works() { Assert.That(c()); }\n}\n",
        )
        self.base(tb / "repo")
        _ = w(
            tests / "test_a.py",
            'import pytest\n\npytestmark = pytest.mark.skip(reason="flaky")\n\n\n'
            "def test_a():\n    assert a()\n",
        )
        _ = w(
            tests / "test_b.py",
            "class T(unittest.TestCase):\n    def test_b(self):\n"
            '        self.skipTest("later")\n        self.assertTrue(b())\n',
        )
        _ = w(
            tests / "CTests.cs",
            'public class CTests {\n    [Test]\n    [Ignore("later")]\n'
            "    public void Works() { Assert.That(c()); }\n}\n",
        )
        self.base(tb / "repo", "skip")
        out = self.tcrun(tb)
        self.ok(
            'test_check: pytestmark, skipTest and [Ignore("…")] are skips',
            grep(out, "^SKIP", count=True) == SKIP_FORMS,
            out,
        )

    def test_noprefix(self) -> None:
        """The user's diff.noprefix leaves the paths whole."""
        tb = self.tcrepo()
        t = tb / "repo/tests/parse.rs"
        _ = self.write(
            t,
            "#[test]\nfn parses() {\n"
            "    assert_eq!(1, f());\n    assert_eq!(2, g());\n}\n",
        )
        self.base(tb / "repo")
        _ = self.write(t, "#[test]\nfn parses() {\n    assert_eq!(1, f());\n}\n")
        self.base(tb / "repo", "drop")
        _ = self.git("-C", tb / "repo", "config", "diff.noprefix", "true")
        out = self.tcrun(tb)
        self.ok(
            "test_check: diff.noprefix does not cut the paths",
            out == "FEWER    tests/parse.rs  1 fewer assertions\n"
            "1 deleted test files, removed tests, "
            "added skips, dropped assertions or edited acceptance tests need a ruling",
            out,
        )

    def test_task_s_table_and_same_line_test(self) -> None:
        """A mapping table read as criteria_check reads it, and a same-line @Test fun.

        The table has `Task(s)`, and a Test file column that is not the third; a
        same-line `@Test fun name()` names its own test.
        """
        tb = self.tcrepo()
        repo = tb / "repo"
        kt = repo / "src/test/kotlin/ParserTest.kt"
        _ = self.write(
            repo / "tests/test_ac.py",
            'def test_ac():\n    assert parse("a") == ["a"]\n',
        )
        _ = self.write(
            kt,
            "class ParserTest {\n    @Test fun parsesEmpty() {\n"
            '        assertEquals(0, parse(""))\n    }\n\n    @Test fun parsesOne() {\n'
            '        assertEquals(1, parse("a"))\n    }\n}\n',
        )
        self.base(repo)
        _ = self.write(
            repo / "tests/test_ac.py", 'def test_ac():\n    assert parse("a")\n'
        )
        _ = self.write(
            kt,
            "class ParserTest {\n    @Test fun parsesEmpty() {\n"
            '        assertEquals(0, parse(""))\n    }\n}\n',
        )
        self.base(repo, "loosen")
        _ = self.write(
            tb / "plans/p1-01-x.md",
            "# p1-01\n| Id | Task(s) | Notes | Test file |\n|---|---|---|---|\n"
            "| AC-P1-1-1 | 1 | see x | `tests/test_ac.py` |\n\n## Task 1 — x\n",
        )
        out = self.tcrun(tb)
        self.ok(
            "test_check: a Task(s) table's Test file column, and a same-line @Test fun",
            grep(out, "^EDITED   tests/test_ac.py")
            and grep(out, "REMOVED  parsesOne  src/test/kotlin/ParserTest.kt", x=True),
            out,
        )

    def test_moved_then_loosened(self) -> None:
        """An acceptance test moved inside the test paths is no edit.

        One loosened after its move is, and one deleted goes to the lead though its
        mapping row names it.
        """
        tb = self.tcrepo()
        repo = tb / "repo"
        text = "import x\n\n\ndef test_ac():\n"
        text += "".join(f'    assert parse("{c}") == ["{c}"]\n' for c in "abcde")
        _ = self.write(repo / "tests/test_ac.py", text)
        _ = self.write(repo / "tests/test_gone.py", "def test_gone():\n    assert 1\n")
        self.base(repo)
        _ = self.git("-C", repo, "mv", "tests/test_ac.py", "tests/test_parse_ac.py")
        self.base(repo, "move")
        _ = self.write(
            tb / "plans/p1-01-x.md",
            "# p1-01\n| Id | Task | Test file |\n|---|---|---|\n"
            "| AC-P1-1-1 | 1 | `tests/test_ac.py` |\n"
            "| AC-P1-1-2 | 1 | `tests/test_gone.py` |\n"
            "\n## Task 1 — x\n",
        )
        out = self.tcrun(tb)
        self.ok(
            "test_check: an acceptance test moved inside the test paths is not edited",
            not grep(out, r"^EDITED\|^DELETED"),
            out,
        )
        moved = repo / "tests/test_parse_ac.py"
        lines = moved.read_text().split("\n")
        _ = self.write(moved, "\n".join(ln.replace('== ["a"]', "", 1) for ln in lines))
        _ = self.git("-C", repo, "rm", "-q", "tests/test_gone.py")
        self.base(repo, "loosen")
        out = self.tcrun(tb, "HEAD~2")
        self.ok(
            "test_check: an acceptance test loosened after its move, or deleted, "
            "goes to the lead",
            grep(out, "^EDITED   tests/test_ac.py")
            and grep(out, "DELETED  tests/test_gone.py", x=True),
            out,
        )


if __name__ == "__main__":
    _ = unittest.main()
