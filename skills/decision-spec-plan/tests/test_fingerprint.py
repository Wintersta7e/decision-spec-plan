# SPDX-License-Identifier: MIT
"""`route_state.py --fingerprint`: one digest of a repository's git state (F109)."""

import re
import unittest
from typing import TYPE_CHECKING

import support

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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

    def remote(self, name: str) -> tuple["Path", "Path"]:
        """A repository with a bare file remote, and a second clone pushing to it."""
        repo = self.init_repo(self.T / name)
        bare, other = self.T / f"{name}-remote.git", self.T / f"{name}-other"
        _ = self.git("init", "-q", "--bare", "-b", "main", bare)
        _ = self.git("-C", repo, "remote", "add", "origin", bare)
        _ = self.git("-C", repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        _ = self.git("clone", "-q", bare, other)
        return repo, other

    def test_fetch_ignored(self) -> None:
        """A fetch moves only `refs/remotes/`, no hunter's slip: the digest holds."""
        repo, other = self.remote("fetch")
        before = self.digest(repo)
        _ = self.git("-C", other, "commit", "-q", "--allow-empty", "-m", "b")
        _ = self.git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/main")
        _ = self.git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/new")
        _ = self.git("-C", repo, "fetch", "-q", "origin")
        self.ok("a fetch's move and new ref", self.digest(repo) == before)
        _ = self.git("-C", repo, "update-ref", "refs/x/main", "HEAD")
        self.ok("any other ref still counts", self.digest(repo) != before)

    def test_push_counts(self) -> None:
        """A pushed existing commit leaves its only trace in a remote-tracking ref."""
        repo, _ = self.remote("push")
        before = self.digest(repo)
        _ = self.git("-C", repo, "push", "-q", "origin", "HEAD:refs/heads/x")
        pushed = self.digest(repo)
        self.ok("a push changes it", pushed != before)
        _ = self.git("-C", repo, "update-ref", "refs/remotes/origin/y", "HEAD")
        self.ok("a manual update-ref changes it", self.digest(repo) != pushed)

    def test_not_a_repository(self) -> None:
        """A directory that is no git repository exits 2."""
        (self.T / "plain").mkdir()
        for args in (("--fingerprint", self.T / "plain"), ("--fingerprint",)):
            r = self.py(support.RS, *args, merge=True)
            self.ok(f"exit 2  {args}", r.code == USAGE_EXIT and "usage" in r.out, r.out)


if __name__ == "__main__":
    _ = unittest.main()
