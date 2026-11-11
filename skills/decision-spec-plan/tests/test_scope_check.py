# SPDX-License-Identifier: MIT
"""scope_check.py: files plans change at once, unasked, unplanned or unimplemented.

Files two plans of one wave change at once (--waves), planned files that cite no ask or
are not to be touched (--asks), changed files no plan lists (--diff), and promised files
no task implements (--list).
"""

import unittest
from pathlib import Path
from typing import ClassVar

import support
from support import grep

# scope_check.py's exit code when there is nothing to check
NOTHING_TO_CHECK = 2


class ScopeWaves(support.Sandbox):
    """--waves: a file two plans of one wave change at once, unless one waits.

    Three lanes of one wave edited the same UI files and left seven seam defects.
    """

    no_hooks: ClassVar[bool] = False

    def plan(self, w: Path, stem: str, *files: str) -> None:
        """A plan stem in w whose File structure table lists files."""
        text = f"# {stem}\n## File structure\n| File | Change |\n|---|---|\n"
        text += "".join(f"| `{f}` | x |\n" for f in files)
        _ = self.write(w / f"{stem}.md", text + "## Task 1\n")

    def test_waves(self) -> None:
        """A shared file of plans that run at once, not of a plan that waits."""
        plans = self.T / "plans"
        self.plan(plans, "p1-01-a", "src/app.js", "src/a.js")
        self.plan(plans, "p1-02-b", "src/app.js", "src/b.js")
        self.plan(plans, "p1-03-c", "src/a.js")
        self.plan(plans, "p1-04-d", "src/app.js")
        self.plan(plans, "p1-05-e", "src/e.js")
        _ = self.write(
            plans / "p1-00-index.md",
            "# Phase 1 — plan index\n## The plan set\n"
            "| Plan | Section | Wave | Depends on |\n"
            "|---|---|---|---|\n| `p1-01-a` | §1 | 1 | — |\n"
            "| `p1-02-b` | §2 | 1 | — |\n"
            "| `p1-03-c` | §3 | 1 | p1-01 |\n| `p1-04-d` | §4 | 2 | all |\n",
        )
        r = self.py("scope_check.py", plans, "--waves", plans / "p1-00-index.md")
        self.ok(
            "scope_check --waves: a shared file of plans that run at once, "
            "not of a plan that waits",
            r.code == 1
            and grep(r.out, "^wave 1 *src/app.js  p1-01-a, p1-02-b$")
            and not grep(r.out, "src/a.js")
            and grep(r.out, "^1 files changed")
            and grep(r.out, "not in the index's plan set: p1-05-e.md"),
            f"exit {r.code}: {r.out}",
        )
        r = self.py(
            "scope_check.py",
            plans,
            "--waves",
            plans / "p1-00-index.md",
            "--glob",
            "p1-0[134]-*.md",
        )
        self.ok(
            "scope_check --waves: exit 0 with no shared file",
            r.code == 0 and grep(r.out, "^0 files changed"),
            r.out,
        )
        # `all` and `all of wave 1` wait for the earlier wave, not for the plan beside
        # them
        plans = self.T / "plans-all"
        self.plan(plans, "p1-01-a", "src/a.js")
        self.plan(plans, "p1-02-c", "src/app.js")
        self.plan(plans, "p1-03-d", "src/app.js")
        _ = self.write(
            plans / "p1-00-index.md",
            "| Plan | Wave | Depends on |\n|---|---|---|\n| `p1-01-a` | 1 | — |\n"
            "| `p1-02-c` | 2 | all of wave 1 |\n| `p1-03-d` | 2 | all |\n",
        )
        r = self.py("scope_check.py", plans, "--waves", plans / "p1-00-index.md")
        self.ok(
            "scope_check --waves: all (of wave 1) does not wait for its own wave",
            r.code == 1 and grep(r.out, "^wave 2 *src/app.js  p1-02-c, p1-03-d$"),
            f"exit {r.code}: {r.out}",
        )
        # the Plan column may hold plan ids (`p1-02`), as every other doc names a plan
        _ = self.write(
            plans / "p1-00-index.md",
            "| Plan | Wave | Depends on |\n|---|---|---|\n| p1-01 | 1 | — |\n"
            "| `p1-02` | 2 | p1-01 |\n| p1-03 | 2 | all |\n",
        )
        r = self.py("scope_check.py", plans, "--waves", plans / "p1-00-index.md")
        self.ok(
            "scope_check --waves: a Plan column of plan ids",
            r.code == 1
            and grep(r.out, "^wave 2 *src/app.js  p1-02-c, p1-03-d$")
            and not grep(r.out, "not in the index"),
            f"exit {r.code}: {r.out}",
        )


class ScopeAsksDiff(support.Sandbox):
    """--asks and --diff: no file planned without an ask, or changed without a plan.

    --asks: every planned file cites an ask or a user ruling and none is a file not to
    touch; --diff: every file a range changed is in a plan (unasked changes, F89).
    """

    no_hooks: ClassVar[bool] = False

    def commit(self, repo: Path, msg: str) -> None:
        """A commit of what is staged in repo, with message msg."""
        _ = self.git("-C", repo, "commit", "-q", "-m", msg)

    def test_asks_and_diff(self) -> None:
        """Rows with no ask or not to touch, and changed files no plan lists."""
        tmp = self.T
        asks = tmp / "asks"
        (asks / "plans").mkdir(parents=True)
        (asks / "repo/src/core").mkdir(parents=True)
        _ = self.write(
            asks / "00-index.md",
            "# Phase 1 — the decision round\n## The asks\n| Ask | Verbatim | Source |\n"
            '|---|---|---|\n| **Ask1** | "port the adapter" | review thread |\n'
            "### Do not touch\n- `pom.xml` — no version bump (the reviewer)\n"
            "## The decisions\n| **D1** | names Ask7 without defining it |\n",
        )
        _ = self.write(
            asks / "00-arbiter.md", "## The user rulings\n### U2 — keep the old test\n"
        )
        _ = self.write(
            asks / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n### `src/core/`\n| File | Change | Ask |\n"
            "|---|---|---|\n| `Adapter.java` | new | Ask1 |\n"
            "| `OldTest.java` | keep | U2 |\n"
            "| `Extra.java` | refactor | — |\n| `Other.java` | tidy | Ask7 |\n"
            "| `pom.xml` | dependency | Ask1 |\n## Task 1\n",
        )
        _ = self.write(
            asks / "plans/p1-02-b.md",
            "# p1-02-b\n## File structure\n| `src/b.js` | new | Ask1 |\n## Task 1\n",
        )
        r = self.py(
            "scope_check.py",
            asks / "plans",
            "--asks",
            asks / "00-index.md",
            asks / "00-arbiter.md",
        )
        self.ok(
            "scope_check --asks: a row with no ask, an undefined ask "
            "and a file not to touch",
            r.code == 1
            and grep(r.out, "p1-01-a.md  src/core/Extra.java  (no ask)$")
            and grep(r.out, "src/core/Other.java  (no ask)$")
            and grep(r.out, "src/core/pom.xml  (do not touch)$")
            and not grep(r.out, r"Adapter.java\|OldTest.java\|src/b.js")
            and grep(r.out, "^3 of 6 planned files"),
            f"exit {r.code}: {r.out}",
        )
        r = self.py(
            "scope_check.py",
            asks / "plans",
            "--asks",
            asks / "00-index.md",
            "--glob",
            "p1-02-*.md",
        )
        self.ok(
            "scope_check --asks: exit 0 when every row cites an ask",
            r.code == 0 and grep(r.out, "^0 of 1 planned files"),
            r.out,
        )
        _ = self.git("init", "-q", "-b", "main", asks / "repo")
        self.touch(asks / "repo/src/core/Adapter.java")
        self.touch(asks / "repo/src/core/Stray.java")
        _ = self.git("-C", asks / "repo", "commit", "-q", "--allow-empty", "-m", "base")
        _ = self.git("-C", asks / "repo", "add", "src")
        self.commit(asks / "repo", "lane")
        r = self.py(
            "scope_check.py",
            asks / "plans",
            "--diff",
            "HEAD~1..HEAD",
            "--repo",
            asks / "repo",
        )
        self.ok(
            "scope_check --diff: a changed file no plan lists",
            r.code == 1
            and grep(r.out, "^   src/core/Stray.java$")
            and not grep(r.out, "Adapter")
            and grep(r.out, "^1 of 2 changed files"),
            f"exit {r.code}: {r.out}",
        )
        r = self.py(
            "scope_check.py",
            asks / "plans",
            "--diff",
            "HEAD..HEAD",
            "--repo",
            asks / "repo",
        )
        self.ok(
            "scope_check --diff: an empty range fails",
            r.code == NOTHING_TO_CHECK and grep(r.out, "^0 of 0 changed files"),
            r.out,
        )
        self.extensionless(tmp / "extless")
        self.renamed_away(tmp / "diffr")

    def extensionless(self, extless: Path) -> None:
        """A file with no extension and a dotfile can be planned, and kept untouched."""
        (extless / "plans").mkdir(parents=True)
        _ = self.init_repo(extless / "repo", commits=("base",))
        _ = self.write(extless / "repo/Makefile", "all:\n")
        _ = self.write(extless / "repo/Dockerfile", "FROM scratch\n")
        _ = self.write(extless / "repo/.gitignore", "*.log\n")
        _ = self.git("-C", extless / "repo", "add", "-A", ".")
        self.commit(extless / "repo", "build")
        _ = self.write(
            extless / "plans/p1-01-build.md",
            "# p1-01\n## File structure\n| File | Why |\n|---|---|\n"
            "| `Makefile` | build (Ask1) |\n"
            "| `Dockerfile` | image (Ask1) |\n| `.gitignore` | logs (Ask1) |\n"
            "## Task 1\n"
            "Create `Makefile`, `Dockerfile` and `.gitignore`.\n",
        )
        r = self.py(
            "scope_check.py",
            extless / "plans",
            "--diff",
            "HEAD~1..HEAD",
            "--repo",
            extless / "repo",
        )
        self.ok(
            "scope_check --diff: Makefile, Dockerfile and .gitignore can be planned",
            r.code == 0 and grep(r.out, "^0 of 3 changed files"),
            f"exit {r.code}: {r.out}",
        )
        _ = self.write(
            extless / "00-index.md",
            "| **Ask1** | x |\n### Do not touch\n- `Makefile` — the build stays\n",
        )
        r = self.py(
            "scope_check.py", extless / "plans", "--asks", extless / "00-index.md"
        )
        self.ok(
            "scope_check --asks: a Makefile not to touch",
            r.code == 1 and grep(r.out, "Makefile  (do not touch)$"),
            f"exit {r.code}: {r.out}",
        )

    def renamed_away(self, diffr: Path) -> None:
        """A rename onto a planned path still deletes an unplanned file.

        A path with a space is one path.
        """
        (diffr / "plans").mkdir(parents=True)
        (diffr / "repo/src").mkdir(parents=True)
        _ = self.write(
            diffr / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n| `src/new.py` | new |\n## Task 1\n",
        )
        _ = self.git("init", "-q", "-b", "main", diffr / "repo")
        _ = self.write(diffr / "repo/src/old.py", "keep\n")
        _ = self.git("-C", diffr / "repo", "add", "src")
        self.commit(diffr / "repo", "base")
        _ = self.git("-C", diffr / "repo", "mv", "src/old.py", "src/new.py")
        self.commit(diffr / "repo", "move")
        _ = self.write(diffr / "repo/src/my notes.py", "x\n")
        _ = self.git("-C", diffr / "repo", "add", "src")
        self.commit(diffr / "repo", "notes")
        r = self.py(
            "scope_check.py",
            diffr / "plans",
            "--diff",
            "HEAD~2..HEAD",
            "--repo",
            diffr / "repo",
        )
        self.ok(
            "scope_check --diff: a renamed-away file and a path with a space",
            r.code == 1
            and grep(r.out, "   src/old.py", x=True)
            and grep(r.out, "   src/my notes.py", x=True)
            and grep(r.out, "^2 of 3 changed files"),
            f"exit {r.code}: {r.out}",
        )

    def test_asks_each_served_or_deferred(self) -> None:
        """An ask no plan row serves.

        One round reported "finished" at 52.9M with an ask unbuilt and --asks green
        (F89).
        """
        root = self.T / "served"
        (root / "plans").mkdir(parents=True)
        _ = self.write(
            root / "00-index.md",
            "## The asks\n| **Ask1** | a |\n| **Ask2** | b |\n| **Ask3** | c |\n"
            "| **Ask4** | d |\n",
        )
        _ = self.write(
            root / "00-arbiter.md",
            "### U5 — Ask3 waits\nThe user deferred it to the next round.\n"
            "### U6 — Ask4 by a config switch\n",
        )
        _ = self.write(
            root / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n| `src/a.py` | new | Ask1 |\n"
            "| `src/d.py` | switch | U6 |\n## Task 1\n",
        )
        r = self.py(
            "scope_check.py",
            root / "plans",
            "--asks",
            root / "00-index.md",
            root / "00-arbiter.md",
        )
        self.ok(
            "scope_check --asks: an ask no row serves and no U<n> defers",
            r.code == 1
            and grep(r.out, "^   Ask2  (no plan row serves it")
            and not grep(r.out, r"^   Ask[134] ")
            and grep(r.out, "^1 of 4 asks no plan row serves")
            and grep(r.out, "^0 of 2 planned files"),
            f"exit {r.code}: {r.out}",
        )

    def test_asks_reads_the_rows_live_plans_wrote(self) -> None:
        """Rows of extensions a project's plans listed and --asks never checked."""
        root = self.T / "exts"
        (root / "plans").mkdir(parents=True)
        _ = self.write(root / "00-index.md", "| **Ask1** | x |\n")
        _ = self.write(
            root / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n| `vitest.config.mts` | rule | — |\n"
            "| `tsup.config.cts` | build | — |\n| `docs/SRS.adoc` | embed | — |\n"
            "| `docs/flow.puml` | new | — |\n## Task 1\n",
        )
        r = self.py("scope_check.py", root / "plans", "--asks", root / "00-index.md")
        self.ok(
            "scope_check --asks: .mts, .cts, .adoc and .puml rows need an ask",
            r.code == 1 and grep(r.out, "^4 of 4 planned files"),
            f"exit {r.code}: {r.out}",
        )

    def test_diff_reads_every_row_the_plan_wrote(self) -> None:
        """Every changed file in a plan row of any shape counts as planned.

        Live: one integrator's --diff flagged 55 of 123 changed files and was overridden
        on all six lanes; every file was in a plan row the check could not read — an
        extension not in --ext, a directory row, a `<domain>` template, a test beside
        its planned file.
        """
        root = self.T / "rows"
        (root / "plans").mkdir(parents=True)
        _ = self.write(
            root / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n| File | Change | Ask |\n|---|---|---|\n"
            # a template in a description cell, anchored to no directory, covers nothing
            "| `src/api/calls/` | one `<domain>.ts` per block | Ask1 |\n"
            "| `vitest.config.mts` | rule | Ask1 |\n"
            "| `docs/srs/SRS.adoc` | embed | Ask1 |\n"
            "| `docs/srs/diagrams/flow.puml` | new | Ask1 |\n"
            "| `src/hubs/users/Dialog.tsx` | guard | Ask1 |\n"
            "| `src/gen/<domain>.ts` | one per domain | Ask1 |\n## Task 1\n",
        )
        repo = self.init_repo(root / "repo", commits=("base",))
        planned = (
            "src/api/calls/rights.ts",
            "src/api/calls/shared.ts",
            "vitest.config.mts",
            "docs/srs/SRS.adoc",
            "docs/srs/diagrams/flow.puml",
            "src/hubs/users/Dialog.tsx",
            "src/hubs/users/__tests__/copy.test.tsx",
            "src/hubs/users/Dialog.test.tsx",
            "src/gen/cache.ts",
        )
        stray = (
            "src/hubs/users/model.ts",
            "src/other/__tests__/x.test.ts",
            "src/api/callsX.ts",
        )
        for f in planned + stray:
            _ = self.write(repo / f, "x\n")
        _ = self.git("-C", repo, "add", "src", "docs", "vitest.config.mts")
        self.commit(repo, "lane")
        r = self.py(
            "scope_check.py", root / "plans", "--diff", "HEAD~1..HEAD", "--repo", repo
        )
        flagged = [ln.strip() for ln in r.out.splitlines() if ln.startswith("   ")]
        self.ok(
            "scope_check --diff: rows of any extension, directories, templates "
            "and tests beside a planned file are planned; the rest is not",
            r.code == 1
            and sorted(flagged) == sorted(stray)
            and grep(r.out, "^3 of 12 changed"),
            f"exit {r.code}: {r.out}",
        )


class ScopeUnimplemented(support.Sandbox):
    """A truncated plan, and a file named only inside a longer path, are unimplemented.

    A plan cut off after its File structure table, and a file named only inside a longer
    path (`data.rs` holds `a.rs`; another plan's `ui/mod.rs` is not `src/mod.rs`), are
    unimplemented; a bare name under a directory heading still counts (F25).
    """

    no_hooks: ClassVar[bool] = False

    def test_unimplemented(self) -> None:
        """Promised files no task names are listed; files a task names are not."""
        unimpl = self.T / "unimpl"
        _ = self.write(
            unimpl / "p1-01-a.md",
            "# p1-01-a\n## File structure\n| `src/a.rs` | a |\n"
            "| `src/mod.rs` | module |\n"
            "| `src/data.rs` | data |\n## Task 1\nCreate `src/data.rs`.\n",
        )
        _ = self.write(
            unimpl / "p1-02-b.md",
            "# p1-02-b\n## File structure\n### `core/`\n| `seg.rs` | segment |\n"
            "| `ui/mod.rs` | module |\n## Task 1\nEdit `ui/mod.rs`, write `seg.rs`.\n",
        )
        _ = self.write(
            unimpl / "p1-03-c.md",
            "# p1-03-c\n## File structure\n| `web/app.ts` | app |\n",
        )
        r = self.py("scope_check.py", unimpl, "--list")
        self.ok(
            "scope_check: a truncated plan and a name inside a longer path "
            "are unimplemented",
            r.code == 1
            and grep(r.out, "^3 promised files")
            and grep(r.out, "   src/a.rs", x=True)
            and grep(r.out, "   src/mod.rs", x=True)
            and grep(r.out, "   web/app.ts", x=True)
            and not grep(r.out, "^   (src/data.rs|ui/mod.rs|core/seg.rs)$", E=True),
            f"exit {r.code}: {r.out}",
        )


if __name__ == "__main__":
    _ = unittest.main()
