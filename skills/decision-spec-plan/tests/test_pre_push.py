"""git's own pre-push hook: --activate installs it, and it reads the exact refs and commits git
sends; the repository's own hook keeps running after it, a push outside Claude Code passes."""

import re
import unittest

import support
from support import RS, grep

CLAUDE = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "pp1"}


class PrePushHook(support.Sandbox):
    # git's hooks must run here: no global core.hooksPath
    no_hooks = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the repository the gate.py section leaves: one commit, a bare origin, no gate logs
        cls.R3 = cls.T / "r3"
        cls.P3 = cls.R3 / ".plan"
        cls.git("init", "-q", "--bare", cls.T / "r3.git")
        cls.git("init", "-q", "-b", "main", cls.R3)
        cls.write(cls.R3 / "f", "a\n")
        cls.git("-C", cls.R3, "add", "f")
        cls.git("-C", cls.R3, "commit", "-q", "-m", "one")
        cls.git("-C", cls.R3, "remote", "add", "origin", cls.T / "r3.git")
        (cls.P3 / "lanes").mkdir(parents=True)

    def activate(self, *extra, repo=None, plan=None):
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

    def gate(self, name, *argv):
        self.py("gate.py", self.P3, name, "--repo", self.R3, *argv, merge=True)

    def push3(self, want, rx, *args, env=None):
        """A real push from a Claude Code shell exits want, rx (grep -E) in its output."""
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

    def outside(self, refspec):
        """A push from a terminal: no CLAUDECODE (the sandbox never has it)."""
        return (
            self.run_(["git", "push", "-q", "origin", refspec], cwd=self.R3).code == 0
        )

    def test_pre_push_hook(self):
        T, R3 = self.T, self.R3
        hooks = R3 / ".git/hooks"
        ran = T / "orig-ran"
        self.write(
            hooks / "pre-push", f'#!/bin/sh\ncat >/dev/null\necho ran >>"{ran}"\n'
        )
        self.chmod_x(hooks / "pre-push")
        r = self.activate()
        text = (hooks / "pre-push").read_text()
        self.ok(
            "activate installs the pre-push hook, the repository's own kept as pre-push.dsp-orig",
            "decision-spec-plan pre-push" in text
            and (hooks / "pre-push").stat().st_mode & 0o111 != 0
            and support.grep_file(hooks / "pre-push.dsp-orig", "echo ran")
            and grep(r.out, "pre-push hook installed"),
            r.out,
        )
        self.activate()
        self.ok(
            "a re-activation keeps the chained hook",
            support.grep_file(hooks / "pre-push.dsp-orig", "echo ran"),
        )
        self.push3(1, "not gated: refs/heads/main = .*no gate log", "main")
        held = self.git(
            "-C",
            T / "r3.git",
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
        self.git("-C", R3, "checkout", "-q", "-b", "side")
        self.git("-C", R3, "commit", "-q", "--allow-empty", "-m", "side")
        self.git("-C", R3, "checkout", "-q", "main")
        self.push3(1, "not gated: refs/heads/side", "--all")
        self.push3(1, "not gated: refs/heads/side", "HEAD~0:refs/heads/x", "side")
        r = self.run_(
            ["git", "push", "-q", "origin", "side"],
            cwd=R3,
            env={**CLAUDE, "DSP_SKIP_PUSH_GUARD": "1"},
            merge=True,
        )
        self.ok("pre-push: DSP_SKIP_PUSH_GUARD=1 skips it", r.code == 0, r.out)
        self.push3(0, "-", ":side")
        # the CI harness: the branch push that starts the CI run needs only the full gate
        self.activate("--ci-harness", "e2e")
        self.git("-C", R3, "commit", "-q", "--allow-empty", "-m", "three")
        self.gate("w2", "--", "true")
        self.push3(0, "-", "main:refs/heads/ci-run")
        self.push3(1, "not passed by the CI harness: refs/heads/main", "main")
        self.gate("w2", "--harness", "e2e", "--", "true")
        self.push3(0, "-", "main")
        self.activate("--ci-harness", "none")
        # with the hook in place the command guard leaves the push to it, holding only what
        # skips it
        self.guard(0, R3, "git push origin side")
        self.guard(0, R3, "git push")
        self.guard(0, R3, "git fetch . side:main && git push origin main")
        self.guard(2, R3, "git push --no-verify origin main")
        self.guard(2, R3, "git config core.hooksPath /dev/null && git push origin side")
        self.guard(2, R3, "rm .git/hooks/pre-push; git push origin side")
        self.guard(2, R3, "CLAUDECODE= git push origin side")
        # git reads an unambiguous abbreviation of a long option as the option
        self.guard(2, R3, "git push --no-verif origin main")
        self.guard(2, R3, "git push --no-veri origin main")
        # a bypass is read as the shell sets it, quotes removed: the hook would honour it unasked
        self.guard("ask", R3, 'DSP_SK""IP_PUSH_GUARD=1 git push origin side')
        self.guard(2, R3, 'DSP_SK""IP_PUSH_GUARD=1 git push origin side', "a1")
        # and whatever runs the push: a Makefile's push reaches the hook with the variable set
        self.guard("ask", R3, "DSP_SKIP_PUSH_GUARD=1 make release")
        self.guard(2, R3, "export DSP_SKIP_REVIEW=1; make release", "a1")
        # set by any command, not only NAME=value; naming one to a read-only command is not a
        # bypass
        self.guard("ask", R3, "printf -v DSP_SKIP_PUSH_GUARD 1; make release")
        self.guard(2, R3, "read DSP_SKIP_REVIEW <<<1; make release", "a1")
        self.guard(2, R3, 'bash -c "DSP_SKIP_REVIEW=1 make release"', "a1")
        # NAME= next to the name is a set wherever it stands; one test decides both skipping and
        # asking
        self.guard("ask", R3, "grep -rn DSP_SKIP_PUSH_GUARD=1 .; git push origin side")
        self.guard(
            2,
            R3,
            "echo export DSP_SKIP_PUSH_GUARD=1 >env.sh; . ./env.sh; make release",
            "a1",
        )
        self.guard(2, R3, "DSP_SKIP_REVIEW=1 bash deploy.sh", "a1")
        self.guard(0, R3, "grep -rn DSP_SKIP_PUSH_GUARD .", "a1")
        self.git("-C", R3, "config", "core.hooksPath", f"{T}/no-hooks")
        self.guard(2, R3, "git push origin side")
        self.git("-C", R3, "config", "--unset", "core.hooksPath")
        # a hook whose guard moved (a plugin upgrade, an uninstall) is no hook to defer to, and
        # it holds a route's pushes instead of letting them through
        hook = hooks / "pre-push"
        hook.write_text(
            re.sub(
                r"^guard=.*",
                f"guard={T}/gone/push_guard.py",
                hook.read_text(),
                flags=re.MULTILINE,
            )
        )
        self.guard(2, R3, "git push origin side")
        self.push3(1, "its guard .* is gone", "side")
        self.ok(
            "a moved guard still lets a push outside Claude Code through",
            self.outside("side:refs/heads/human2"),
        )
        self.activate()
        self.guard(0, R3, "git push origin side")
        # the route ended (its marker deleted): the hook lets every push through
        support.Route.MK(R3).unlink()
        self.push3(0, "-", "side")
        # a repository whose hooks live elsewhere (core.hooksPath) keeps the command guard alone
        R4 = T / "r4"
        self.git("init", "-q", "-b", "main", R4)
        self.git("-C", R4, "config", "core.hooksPath", ".husky")
        (R4 / ".plan").mkdir()
        r = self.activate(repo=R4, plan=R4 / ".plan")
        self.ok(
            "activate with core.hooksPath: no hook written, says so",
            not (R4 / ".git/hooks/pre-push").exists()
            and not (R4 / ".husky/pre-push").exists()
            and grep(r.out, "core.hooksPath is set"),
            r.out,
        )


if __name__ == "__main__":
    unittest.main()
