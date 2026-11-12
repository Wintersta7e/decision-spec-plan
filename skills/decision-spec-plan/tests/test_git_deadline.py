# SPDX-License-Identifier: MIT
"""`common.git` under a deadline: a block of git calls bounded in wall time.

The deadline is absolute for its block, raises before a spawn once passed, turns a git
that outlives it into `GitDeadlineError`, and is local to its thread. Unset, git runs
as before, stdin included.
"""

import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from typing_extensions import override

import support
from dsp_route import common

MAX_SPAWNS = 3  # 0.5 s at 0.2 s per git: two finish, the third is killed
WALL_MAX_S = 1.5  # a 0.2 s deadline on a 2 s git
SLOW_CALLS = 3  # the calls the thread with the long deadline makes


def spawns(log: Path) -> int:
    """The number of git spawns the shim logged."""
    return len(log.read_text().splitlines()) if log.exists() else 0


class GitDeadlineAPI(support.Sandbox):
    """`git_deadline`, `GIT_DEADLINE` and `GitDeadlineError`, run in process."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """A repository with one commit."""
        super().setUpClass()
        cls.R: Path = cls.init_repo(cls.T / "r")
        cls.SHA: str = cls.rev(cls.R)

    def head(self) -> tuple[int, str]:
        """`git rev-parse HEAD` in R, through `common.git`."""
        return common.git(self.R, "rev-parse", "HEAD")

    def test_unset_runs_as_before(self) -> None:
        """No deadline: git answers, and stdin reaches it with or without one."""
        got = self.head()
        self.ok(
            "unset: git runs and no deadline is set",
            got == (0, self.SHA) and common.GIT_DEADLINE.get() is None,
            got,
        )
        args = ("cat-file", "--batch-check=%(objectname)")
        unset = common.git(self.R, *args, stdin="HEAD\n")
        with common.git_deadline(30):
            inside = common.git(self.R, *args, stdin="HEAD\n")
        self.ok(
            "stdin reaches git, unset and under a deadline",
            unset == (0, self.SHA) and inside == (0, self.SHA),
            f"{unset} {inside}",
        )

    def test_passed_deadline_spawns_nothing(self) -> None:
        """A block's calls stop at its deadline; a call past it spawns no git."""
        env, log = self.git_shim(self.T / "slow", sleep=0.2)
        raised = again = False
        with mock.patch.dict(os.environ, env), common.git_deadline(0.5):
            for _ in range(20):
                try:
                    _ = self.head()
                except common.GitDeadlineError:
                    raised = True
                    break
            n = spawns(log)
            try:
                _ = self.head()
            except common.GitDeadlineError:
                again = True
            extra = spawns(log) - n
        self.ok(
            f"deadline 0.5 s at 0.2 s per git: {n} spawns, then GitDeadlineError",
            raised and 0 < n <= MAX_SPAWNS,
            log.read_text() if log.exists() else "no log",
        )
        self.ok(
            f"a call past the deadline raises and adds {extra} spawns",
            again and extra == 0,
        )

    def test_timeout_becomes_gitdeadline(self) -> None:
        """A git that outlives the deadline is stopped, raised as GitDeadlineError."""
        env, log = self.git_shim(self.T / "slower", sleep=2)
        err: BaseException | None = None
        start = time.monotonic()
        with mock.patch.dict(os.environ, env), common.git_deadline(0.2):
            try:
                _ = self.head()
            except common.GitDeadlineError as e:
                err = e
        wall = time.monotonic() - start
        self.ok(
            f"a 2 s git under a 0.2 s deadline: GitDeadlineError after {wall:.2f} s, "
            f"{spawns(log)} spawns",
            isinstance(err, TimeoutError) and wall < WALL_MAX_S and spawns(log) > 0,
            repr(err),
        )

    def test_reset_and_threads(self) -> None:
        """The deadline ends with its block and stays in its own thread."""
        with common.git_deadline(30):
            pass
        self.ok(
            "after the block: no deadline, git runs",
            common.GIT_DEADLINE.get() is None and self.head() == (0, self.SHA),
        )
        env, _log = self.git_shim(self.T / "threads", sleep=0.2)
        short: list[str] = []
        long: list[str] = []
        seen: list[float | None] = []

        def run(seconds: float, calls: int, out: list[str]) -> None:
            with common.git_deadline(seconds):
                for _ in range(calls):
                    try:
                        out.append(self.head()[1])
                    except common.GitDeadlineError:
                        out.append("deadline")
                        return

        with mock.patch.dict(os.environ, env):
            threads = [
                threading.Thread(target=run, args=(0.3, 10, short)),
                threading.Thread(target=run, args=(30, SLOW_CALLS, long)),
            ]
            for t in threads:
                t.start()
            with common.git_deadline(0.01):
                third = threading.Thread(
                    target=lambda: seen.append(common.GIT_DEADLINE.get())
                )
                third.start()
                third.join()
            for t in threads:
                t.join()
        self.ok(
            f"threads: the 0.3 s one ends at GitDeadlineError after {len(short) - 1} "
            f"calls, the 30 s one makes all {len(long)}",
            short[-1:] == ["deadline"] and long == [self.SHA] * SLOW_CALLS,
            f"{short} {long}",
        )
        self.ok(
            "a thread started inside a block has no deadline",
            seen == [None],
            seen,
        )


if __name__ == "__main__":
    _ = unittest.main()
