# SPDX-License-Identifier: MIT
"""git's own pre-push hook: --activate installs it, and it reads what git sends.

The hook reads the exact refs and commits git sends; the repository's own hook keeps
running after it, and a push outside Claude Code passes.
"""

import re
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from typing_extensions import override

import support
from support import RS, Result, grep

CLAUDE = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "pp1"}


class PrePushHook(support.Sandbox):
    """The pre-push hook on repository r3, which has a bare origin."""

    # git's hooks must run here: no global core.hooksPath
    no_hooks: ClassVar[bool] = False

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Create r3 at one commit, its bare origin and its planning dir."""
        super().setUpClass()
        # the repository the gate.py section leaves: one commit, a bare origin, no gate
        # logs
        cls.R3: Path = cls.T / "r3"
        cls.P3: Path = cls.R3 / ".plan"
        _ = cls.git("init", "-q", "--bare", cls.T / "r3.git")
        _ = cls.git("init", "-q", "-b", "main", cls.R3)
        _ = cls.write(cls.R3 / "f", "a\n")
        _ = cls.git("-C", cls.R3, "add", "f")
        _ = cls.git("-C", cls.R3, "commit", "-q", "-m", "one")
        _ = cls.git("-C", cls.R3, "remote", "add", "origin", cls.T / "r3.git")
        (cls.P3 / "lanes").mkdir(parents=True)

    def activate(
        self, *extra: object, repo: Path | None = None, plan: Path | None = None
    ) -> Result:
        """`route_state.py --activate` of phase 1 on repo (default r3), plus extra."""
        return self.py(
            RS,
            plan or self.P3,
            "--phase",
            "1",
            "--repo",
            repo or self.R3,
            "--activate",
            *extra,
            session="pp1",
            merge=True,
        )

    def gate(self, name: str, *argv: str) -> None:
        """`gate.py` run as gate name on r3 with argv."""
        _ = self.py("gate.py", self.P3, name, "--repo", self.R3, *argv, merge=True)

    def push3(
        self, want: int, rx: str, *args: str, env: Mapping[str, str] | None = None
    ) -> None:
        """A real push from Claude Code exits want, rx (grep -E) in its output."""
        r = self.run_(
            ["git", "push", "-q", "origin", *args],
            cwd=self.R3,
            env={**CLAUDE, **(env or {})},
            merge=True,
        )
        self.ok(
            f"pre-push {want}  {' '.join(args)}",
            r.code == want and (rx == "-" or grep(r.out, rx, E=True)),
            f"got {r.code}: {r.out[:600]}",
        )

    def outside(self, refspec: str) -> bool:
        """A push from a terminal: no CLAUDECODE (the sandbox never has it)."""
        return (
            self.run_(["git", "push", "-q", "origin", refspec], cwd=self.R3).code == 0
        )

    def test_pre_push_hook(self) -> None:
        """The hook installed, chained, deferred to, moved and ended, in that order."""
        hooks = self.R3 / ".git/hooks"
        self.installs_and_holds(hooks)
        self.ci_harness()
        self.guard_defers_to_the_hook()
        self.moved_guard_and_ended_route(hooks)
        self.hooks_path_elsewhere()

    def installs_and_holds(self, hooks: Path) -> None:
        """--activate installs the hook; it holds each ref git sends no gate passed."""
        root, r3 = self.T, self.R3
        ran = root / "orig-ran"
        _ = self.write(
            hooks / "pre-push", f'#!/bin/sh\ncat >/dev/null\necho ran >>"{ran}"\n'
        )
        self.chmod_x(hooks / "pre-push")
        r = self.activate()
        text = (hooks / "pre-push").read_text()
        self.ok(
            "activate installs the pre-push hook, the repository's own kept as "
            "pre-push.dsp-orig",
            "decision-spec-plan pre-push" in text
            and (hooks / "pre-push").stat().st_mode & 0o111 != 0
            and support.grep_file(hooks / "pre-push.dsp-orig", "echo ran")
            and grep(r.out, "pre-push hook installed"),
            r.out,
        )
        _ = self.activate()
        self.ok(
            "a re-activation keeps the chained hook",
            support.grep_file(hooks / "pre-push.dsp-orig", "echo ran"),
        )
        self.push3(1, "not gated: refs/heads/main = .*no gate log", "main")
        held = self.git(
            "-C",
            root / "r3.git",
            "rev-parse",
            "-q",
            "--verify",
            "refs/heads/main",
            check=False,
        )
        self.ok("a held push left the remote untouched", held.code != 0)
        self.ok("the chained hook runs only after the guard passes", not ran.exists())
        self.ok(
            "a push outside Claude Code passes", self.outside("main:refs/heads/human")
        )
        self.ok(
            "the repository's own pre-push hook still runs",
            ran.exists() and ran.stat().st_size > 0,
        )
        self.gate("w1", "--", "echo built")
        self.push3(0, "-", "main")
        # every ref git sends is read, --all included: a branch no gate passed is named
        _ = self.git("-C", r3, "checkout", "-q", "-b", "side")
        _ = self.git("-C", r3, "commit", "-q", "--allow-empty", "-m", "side")
        _ = self.git("-C", r3, "checkout", "-q", "main")
        self.push3(1, "not gated: refs/heads/side", "--all")
        self.push3(1, "not gated: refs/heads/side", "HEAD~0:refs/heads/x", "side")
        r = self.run_(
            ["git", "push", "-q", "origin", "side"],
            cwd=r3,
            env={**CLAUDE, "DSP_SKIP_PUSH_GUARD": "1"},
            merge=True,
        )
        self.ok("pre-push: DSP_SKIP_PUSH_GUARD=1 skips it", r.code == 0, r.out)
        self.push3(0, "-", ":side")

    def ci_harness(self) -> None:
        """The branch push that starts the CI run needs only the full gate."""
        _ = self.activate("--ci-harness", "e2e")
        _ = self.git("-C", self.R3, "commit", "-q", "--allow-empty", "-m", "three")
        self.gate("w2", "--", "true")
        self.push3(0, "-", "main:refs/heads/ci-run")
        self.push3(1, "not passed by the CI harness: refs/heads/main", "main")
        self.gate("w2", "--harness", "e2e", "--", "true")
        self.push3(0, "-", "main")
        _ = self.activate("--ci-harness", "none")

    def guard_defers_to_the_hook(self) -> None:
        """With the hook in place, the command guard holds only what skips it."""
        root, r3 = self.T, self.R3
        _ = self.guard(0, r3, "git push origin side")
        _ = self.guard(0, r3, "git push")
        _ = self.guard(0, r3, "git fetch . side:main && git push origin main")
        _ = self.guard(2, r3, "git push --no-verify origin main")
        _ = self.guard(
            2, r3, "git config core.hooksPath /dev/null && git push origin side"
        )
        _ = self.guard(2, r3, "rm .git/hooks/pre-push; git push origin side")
        _ = self.guard(2, r3, "CLAUDECODE= git push origin side")
        # git reads an unambiguous abbreviation of a long option as the option
        _ = self.guard(2, r3, "git push --no-verif origin main")
        _ = self.guard(2, r3, "git push --no-veri origin main")
        # a bypass is read as the shell sets it, quotes removed: the hook would honour
        # it unasked
        _ = self.guard("ask", r3, 'DSP_SK""IP_PUSH_GUARD=1 git push origin side')
        _ = self.guard(2, r3, 'DSP_SK""IP_PUSH_GUARD=1 git push origin side', "a1")
        # and whatever runs the push: a Makefile's push reaches the hook with the
        # variable set
        _ = self.guard("ask", r3, "DSP_SKIP_PUSH_GUARD=1 make release")
        _ = self.guard(2, r3, "export DSP_SKIP_REVIEW=1; make release", "a1")
        # set by any command, not only NAME=value; naming one to a read-only command is
        # not a bypass
        _ = self.guard("ask", r3, "printf -v DSP_SKIP_PUSH_GUARD 1; make release")
        _ = self.guard(2, r3, "printf -vDSP_SKIP_REVIEW 1; make release", "a1")
        _ = self.guard(2, r3, "read DSP_SKIP_REVIEW <<<1; make release", "a1")
        _ = self.guard(2, r3, 'bash -c "DSP_SKIP_REVIEW=1 make release"', "a1")
        # a NAME=value word sets it for any command that passes it on (`make`, `env`) or
        # writes it out (`echo … >env.sh`); one test decides both skipping and asking
        _ = self.guard(
            2,
            r3,
            "echo export DSP_SKIP_PUSH_GUARD=1 >env.sh; . ./env.sh; make release",
            "a1",
        )
        _ = self.guard(2, r3, "DSP_SKIP_REVIEW=1 bash deploy.sh", "a1")
        _ = self.guard(0, r3, "grep -rn DSP_SKIP_PUSH_GUARD .", "a1")
        # the name in text the shell sets nothing from is no bypass: a search, a log
        # query, a commit message, a comment
        _ = self.guard(0, r3, "grep -rn DSP_SKIP_PUSH_GUARD=1 .; git push origin side")
        _ = self.guard(0, r3, "git log --oneline --grep DSP_SKIP_REVIEW", "a1")
        _ = self.guard(0, r3, 'git commit -m "docs: DSP_SKIP_REVIEW=1 now asks"', "a1")
        _ = self.guard(0, r3, "git push origin side # DSP_SKIP_REVIEW=1", "a1")
        # an alias's body runs in the shell that defines it
        _ = self.guard(
            2, r3, "alias gp='DSP_SKIP_REVIEW=1 git push'; gp origin side", "a1"
        )
        # any spelling that may set the guard's variable is asked as a guard skip, not a
        # review skip: git's hook honours it whatever the text looked like
        for cmd in (
            "X=1; export DSP_SKIP_PUSH_GUARD=$X; git push origin side",
            "DSP_SKIP_PUSH_GUARD=${FORCE:-1} git push origin side",
        ):
            r = self.guard("ask", r3, cmd)
            self.ok(f"asked as a guard skip  {cmd}", "the push guard" in r.out, r.out)
        # a command the walk cannot follow still has its bypass read (`~` after a
        # computed HOME)
        _ = self.guard(2, r3, "HOME=$(pwd); cd ~; DSP_SKIP_REVIEW=1 make release", "a1")
        _ = self.guard("ask", r3, "HOME=$(pwd); cd ~; DSP_SKIP_REVIEW=1 make release")
        _ = self.git("-C", r3, "config", "core.hooksPath", f"{root}/no-hooks")
        _ = self.guard(2, r3, "git push origin side")
        _ = self.git("-C", r3, "config", "--unset", "core.hooksPath")

    def moved_guard_and_ended_route(self, hooks: Path) -> None:
        """A hook whose guard moved holds; one whose route ended lets every push go."""
        root, r3 = self.T, self.R3
        # a hook whose guard moved (a plugin upgrade, an uninstall) is no hook to defer
        # to, and it holds a route's pushes instead of letting them through
        hook = hooks / "pre-push"
        _ = hook.write_text(
            re.sub(
                r"^guard=.*",
                f"guard={root}/gone/push_guard.py",
                hook.read_text(),
                flags=re.MULTILINE,
            )
        )
        _ = self.guard(2, r3, "git push origin side")
        self.push3(1, "its guard .* is gone", "side")
        self.ok(
            "a moved guard still lets a push outside Claude Code through",
            self.outside("side:refs/heads/human2"),
        )
        _ = self.activate()
        _ = self.guard(0, r3, "git push origin side")
        # the route ended (its marker deleted): the hook lets every push through
        support.Route.MK(r3).unlink()
        self.push3(0, "-", "side")

    def hooks_path_elsewhere(self) -> None:
        """A repository whose hooks live elsewhere keeps the command guard alone."""
        r4 = self.T / "r4"
        _ = self.git("init", "-q", "-b", "main", r4)
        _ = self.git("-C", r4, "config", "core.hooksPath", ".husky")
        (r4 / ".plan").mkdir()
        r = self.activate(repo=r4, plan=r4 / ".plan")
        self.ok(
            "activate with core.hooksPath: no hook written, says so",
            not (r4 / ".git/hooks/pre-push").exists()
            and not (r4 / ".husky/pre-push").exists()
            and grep(r.out, "core.hooksPath is set"),
            r.out,
        )


if __name__ == "__main__":
    _ = unittest.main()
