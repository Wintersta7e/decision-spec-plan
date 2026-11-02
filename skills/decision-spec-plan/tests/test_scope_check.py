"""scope_check.py: files two plans of one wave change at once (--waves), planned files that cite
no ask or are not to be touched (--asks), changed files no plan lists (--diff), and promised files
no task implements (--list)."""

import unittest

import support
from support import grep


class ScopeWaves(support.Sandbox):
    """--waves: a file two plans of one wave change at once, unless one waits for the other (three
    lanes of one wave edited the same UI files and left seven seam defects)."""

    no_hooks = False

    def plan(self, w, stem, *files):
        text = f"# {stem}\n## File structure\n| File | Change |\n|---|---|\n"
        text += "".join(f"| `{f}` | x |\n" for f in files)
        self.write(w / f"{stem}.md", text + "## Task 1\n")

    def test_waves(self):
        W = self.T / "plans"
        self.plan(W, "p1-01-a", "src/app.js", "src/a.js")
        self.plan(W, "p1-02-b", "src/app.js", "src/b.js")
        self.plan(W, "p1-03-c", "src/a.js")
        self.plan(W, "p1-04-d", "src/app.js")
        self.plan(W, "p1-05-e", "src/e.js")
        self.write(
            W / "p1-00-index.md",
            "# Phase 1 — plan index\n## The plan set\n| Plan | Section | Wave | Depends on |\n"
            "|---|---|---|---|\n| `p1-01-a` | §1 | 1 | — |\n| `p1-02-b` | §2 | 1 | — |\n"
            "| `p1-03-c` | §3 | 1 | p1-01 |\n| `p1-04-d` | §4 | 2 | all |\n",
        )
        r = self.py("scope_check.py", W, "--waves", W / "p1-00-index.md")
        self.ok(
            "scope_check --waves: a shared file of plans that run at once, not of a plan that waits",
            r.code == 1
            and grep(r.out, "^wave 1 *src/app.js  p1-01-a, p1-02-b$")
            and not grep(r.out, "src/a.js")
            and grep(r.out, "^1 files changed")
            and grep(r.out, "not in the index's plan set: p1-05-e.md"),
            f"exit {r.code}: {r.out}",
        )
        r = self.py(
            "scope_check.py",
            W,
            "--waves",
            W / "p1-00-index.md",
            "--glob",
            "p1-0[134]-*.md",
        )
        self.ok(
            "scope_check --waves: exit 0 with no shared file",
            r.code == 0 and grep(r.out, "^0 files changed"),
            r.out,
        )
        # `all` and `all of wave 1` wait for the earlier wave, not for the plan beside them
        W = self.T / "plans-all"
        self.plan(W, "p1-01-a", "src/a.js")
        self.plan(W, "p1-02-c", "src/app.js")
        self.plan(W, "p1-03-d", "src/app.js")
        self.write(
            W / "p1-00-index.md",
            "| Plan | Wave | Depends on |\n|---|---|---|\n| `p1-01-a` | 1 | — |\n"
            "| `p1-02-c` | 2 | all of wave 1 |\n| `p1-03-d` | 2 | all |\n",
        )
        r = self.py("scope_check.py", W, "--waves", W / "p1-00-index.md")
        self.ok(
            "scope_check --waves: all (of wave 1) does not wait for its own wave",
            r.code == 1 and grep(r.out, "^wave 2 *src/app.js  p1-02-c, p1-03-d$"),
            f"exit {r.code}: {r.out}",
        )
        # the Plan column may hold plan ids (`p1-02`), as every other doc names a plan
        self.write(
            W / "p1-00-index.md",
            "| Plan | Wave | Depends on |\n|---|---|---|\n| p1-01 | 1 | — |\n"
            "| `p1-02` | 2 | p1-01 |\n| p1-03 | 2 | all |\n",
        )
        r = self.py("scope_check.py", W, "--waves", W / "p1-00-index.md")
        self.ok(
            "scope_check --waves: a Plan column of plan ids",
            r.code == 1
            and grep(r.out, "^wave 2 *src/app.js  p1-02-c, p1-03-d$")
            and not grep(r.out, "not in the index"),
            f"exit {r.code}: {r.out}",
        )


class ScopeAsksDiff(support.Sandbox):
    """--asks: every planned file cites an ask or a user ruling and none is a file not to touch;
    --diff: every file a range changed is in a plan (unasked changes, F89)."""

    no_hooks = False

    def commit(self, repo, msg):
        self.git("-C", repo, "commit", "-q", "-m", msg)

    def test_asks_and_diff(self):
        T = self.T
        A = T / "asks"
        (A / "plans").mkdir(parents=True)
        (A / "repo/src/core").mkdir(parents=True)
        self.write(
            A / "00-index.md",
            "# Phase 1 — the decision round\n## The asks\n| Ask | Verbatim | Source |\n"
            '|---|---|---|\n| **Ask1** | "port the adapter" | review thread |\n'
            "### Do not touch\n- `pom.xml` — no version bump (the reviewer)\n"
            "## The decisions\n| **D1** | names Ask7 without defining it |\n",
        )
        self.write(
            A / "00-arbiter.md", "## The user rulings\n### U2 — keep the old test\n"
        )
        self.write(
            A / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n### `src/core/`\n| File | Change | Ask |\n"
            "|---|---|---|\n| `Adapter.java` | new | Ask1 |\n| `OldTest.java` | keep | U2 |\n"
            "| `Extra.java` | refactor | — |\n| `Other.java` | tidy | Ask7 |\n"
            "| `pom.xml` | dependency | Ask1 |\n## Task 1\n",
        )
        self.write(
            A / "plans/p1-02-b.md",
            "# p1-02-b\n## File structure\n| `src/b.js` | new | Ask1 |\n## Task 1\n",
        )
        r = self.py(
            "scope_check.py",
            A / "plans",
            "--asks",
            A / "00-index.md",
            A / "00-arbiter.md",
        )
        self.ok(
            "scope_check --asks: a row with no ask, an undefined ask and a file not to touch",
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
            A / "plans",
            "--asks",
            A / "00-index.md",
            "--glob",
            "p1-02-*.md",
        )
        self.ok(
            "scope_check --asks: exit 0 when every row cites an ask",
            r.code == 0 and grep(r.out, "^0 of 1 planned files"),
            r.out,
        )
        self.git("init", "-q", "-b", "main", A / "repo")
        self.touch(A / "repo/src/core/Adapter.java")
        self.touch(A / "repo/src/core/Stray.java")
        self.git("-C", A / "repo", "commit", "-q", "--allow-empty", "-m", "base")
        self.git("-C", A / "repo", "add", "src")
        self.commit(A / "repo", "lane")
        r = self.py(
            "scope_check.py",
            A / "plans",
            "--diff",
            "HEAD~1..HEAD",
            "--repo",
            A / "repo",
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
            "scope_check.py", A / "plans", "--diff", "HEAD..HEAD", "--repo", A / "repo"
        )
        self.ok(
            "scope_check --diff: an empty range fails",
            r.code == 2 and grep(r.out, "^0 of 0 changed files"),
            r.out,
        )
        # a build file with no extension and a dotfile are files a plan can list, and not touch
        X = T / "extless"
        (X / "plans").mkdir(parents=True)
        self.init_repo(X / "repo", commits=("base",))
        self.write(X / "repo/Makefile", "all:\n")
        self.write(X / "repo/Dockerfile", "FROM scratch\n")
        self.write(X / "repo/.gitignore", "*.log\n")
        self.git("-C", X / "repo", "add", "-A", ".")
        self.commit(X / "repo", "build")
        self.write(
            X / "plans/p1-01-build.md",
            "# p1-01\n## File structure\n| File | Why |\n|---|---|\n| `Makefile` | build (Ask1) |\n"
            "| `Dockerfile` | image (Ask1) |\n| `.gitignore` | logs (Ask1) |\n## Task 1\n"
            "Create `Makefile`, `Dockerfile` and `.gitignore`.\n",
        )
        r = self.py(
            "scope_check.py",
            X / "plans",
            "--diff",
            "HEAD~1..HEAD",
            "--repo",
            X / "repo",
        )
        self.ok(
            "scope_check --diff: Makefile, Dockerfile and .gitignore can be planned",
            r.code == 0 and grep(r.out, "^0 of 3 changed files"),
            f"exit {r.code}: {r.out}",
        )
        self.write(
            X / "00-index.md",
            "| **Ask1** | x |\n### Do not touch\n- `Makefile` — the build stays\n",
        )
        r = self.py("scope_check.py", X / "plans", "--asks", X / "00-index.md")
        self.ok(
            "scope_check --asks: a Makefile not to touch",
            r.code == 1 and grep(r.out, "Makefile  (do not touch)$"),
            f"exit {r.code}: {r.out}",
        )
        # a rename onto a planned path still deletes an unplanned file, and a path with a space is
        # one path
        D = T / "diffr"
        (D / "plans").mkdir(parents=True)
        (D / "repo/src").mkdir(parents=True)
        self.write(
            D / "plans/p1-01-a.md",
            "# p1-01-a\n## File structure\n| `src/new.py` | new |\n## Task 1\n",
        )
        self.git("init", "-q", "-b", "main", D / "repo")
        self.write(D / "repo/src/old.py", "keep\n")
        self.git("-C", D / "repo", "add", "src")
        self.commit(D / "repo", "base")
        self.git("-C", D / "repo", "mv", "src/old.py", "src/new.py")
        self.commit(D / "repo", "move")
        self.write(D / "repo/src/my notes.py", "x\n")
        self.git("-C", D / "repo", "add", "src")
        self.commit(D / "repo", "notes")
        r = self.py(
            "scope_check.py",
            D / "plans",
            "--diff",
            "HEAD~2..HEAD",
            "--repo",
            D / "repo",
        )
        self.ok(
            "scope_check --diff: a renamed-away file and a path with a space",
            r.code == 1
            and grep(r.out, "   src/old.py", x=True)
            and grep(r.out, "   src/my notes.py", x=True)
            and grep(r.out, "^2 of 3 changed files"),
            f"exit {r.code}: {r.out}",
        )


class ScopeUnimplemented(support.Sandbox):
    """A plan cut off after its File structure table, and a file named only inside a longer path
    (`data.rs` holds `a.rs`; another plan's `ui/mod.rs` is not `src/mod.rs`), are unimplemented; a
    bare name under a directory heading still counts (F25)."""

    no_hooks = False

    def test_unimplemented(self):
        U = self.T / "unimpl"
        self.write(
            U / "p1-01-a.md",
            "# p1-01-a\n## File structure\n| `src/a.rs` | a |\n| `src/mod.rs` | module |\n"
            "| `src/data.rs` | data |\n## Task 1\nCreate `src/data.rs`.\n",
        )
        self.write(
            U / "p1-02-b.md",
            "# p1-02-b\n## File structure\n### `core/`\n| `seg.rs` | segment |\n"
            "| `ui/mod.rs` | module |\n## Task 1\nEdit `ui/mod.rs`, write `seg.rs`.\n",
        )
        self.write(
            U / "p1-03-c.md", "# p1-03-c\n## File structure\n| `web/app.ts` | app |\n"
        )
        r = self.py("scope_check.py", U, "--list")
        self.ok(
            "scope_check: a truncated plan and a name inside a longer path are unimplemented",
            r.code == 1
            and grep(r.out, "^3 promised files")
            and grep(r.out, "   src/a.rs", x=True)
            and grep(r.out, "   src/mod.rs", x=True)
            and grep(r.out, "   web/app.ts", x=True)
            and not grep(r.out, "^   (src/data.rs|ui/mod.rs|core/seg.rs)$", E=True),
            f"exit {r.code}: {r.out}",
        )


if __name__ == "__main__":
    unittest.main()
