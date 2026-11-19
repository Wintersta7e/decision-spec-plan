# SPDX-License-Identifier: MIT
"""`route_state.py --fingerprint`: one digest of a repository's git state (F109)."""

import re
import unittest
from typing import TYPE_CHECKING

import support

if TYPE_CHECKING:
    from collections.abc import Callable

DIGEST = re.compile(r"[0-9a-f]{64}")
USAGE_EXIT = 2


class Fingerprint(support.Sandbox):
    """The digest is stable, and a change to any part it covers changes it."""

    def digest(self, repo: object) -> str:
        """The fingerprint route_state.py prints for repo; a failed check for none."""
        r = self.py(support.RS, "--fingerprint", repo)
        self.ok(f"a digest of {repo}", r.code == 0 and DIGEST.fullmatch(r.out), r.out)
        return r.out

    def test_each_part_changes_it(self) -> None:
        """HEAD, refs, stash, status, the local config and its files, info, hooks."""
        repo = self.init_repo(self.T / "fp")
        _ = self.write(repo / ".gitignore", "*.log\n")
        _ = self.write(repo / "a.txt", "a\n")
        _ = self.git("-C", repo, "add", ".")
        _ = self.git("-C", repo, "commit", "-q", "-m", "a")
        hooks = self.T / "no-hooks"  # the sandbox's core.hooksPath
        self.addCleanup(self.git, "config", "--global", "core.hooksPath", hooks)
        # the global config is outside the hash: only the resolved path tells
        other_hooks = ("config", "--global", "core.hooksPath", self.T / "other-hooks")
        dot_git = repo / ".git"
        config = ("-C", repo, "config")
        steps: list[tuple[str, Callable[[], object]]] = [
            (
                "a commit",
                lambda: self.git(
                    "-C", repo, "commit", "-q", "--allow-empty", "-m", "b"
                ),
            ),
            ("a branch", lambda: self.git("-C", repo, "branch", "x")),
            ("a change", lambda: self.write(repo / "a.txt", "b\n")),
            ("a stash", lambda: self.git("-C", repo, "stash", "-q")),
            ("an untracked file", lambda: self.write(repo / "u.txt", "u\n")),
            ("an ignored file", lambda: self.write(repo / "x.log", "x\n")),
            ("a config write", lambda: self.git("-C", repo, "config", "a.b", "c")),
            ("a hook", lambda: self.write(hooks / "pre-commit", "#!/bin/sh\n")),
            (
                "a hook's bytes",
                lambda: self.write(hooks / "pre-commit", "#!/bin/sh\n:\n"),
            ),
            ("the hooks dir's path", lambda: self.git(*other_hooks)),
            ("an include", lambda: self.git(*config, "include.path", "inc.cfg")),
            ("an included value", lambda: self.write(dot_git / "inc.cfg", "[a]c=d\n")),
            (
                "an included file's bytes",
                lambda: self.write(dot_git / "inc.cfg", "#\n", "a"),
            ),
            (
                "a config.worktree",
                lambda: self.write(dot_git / "config.worktree", "#\n"),
            ),
            (
                "worktree config",
                lambda: self.git(*config, "extensions.worktreeConfig", "1"),
            ),
            ("a worktree value", lambda: self.git(*config, "--worktree", "a.e", "f")),
            ("an info file", lambda: self.write(dot_git / "info" / "note", "n\n")),
            (
                "an info file's bytes",
                lambda: self.write(dot_git / "info" / "note", "m\n"),
            ),
        ]
        seen = [self.digest(repo)]
        self.ok("stable", self.digest(repo) == seen[0])
        for what, change in steps:
            _ = change()
            seen.append(self.digest(repo))
            self.ok(f"{what} changes it", seen[-1] not in seen[:-1], seen)

    def test_not_a_repository(self) -> None:
        """A directory that is no git repository exits 2."""
        (self.T / "plain").mkdir()
        for args in (("--fingerprint", self.T / "plain"), ("--fingerprint",)):
            r = self.py(support.RS, *args, merge=True)
            self.ok(f"exit 2  {args}", r.code == USAGE_EXIT and "usage" in r.out, r.out)


if __name__ == "__main__":
    _ = unittest.main()
