# SPDX-License-Identifier: MIT
"""push_guard.py's checks past the gate log.

The seven-sins verdict a `--sins on` route needs on a gated push (F70), and the CI
harness log a route that names one needs (F90).
"""

import json
import unittest

from typing_extensions import override

import support
from support import RS, Result, grep, grep_file

HELD = 2  # the exit code of a held push


def gate_logs(cls: type[support.Route]) -> None:
    """The gate logs the gate-log section leaves: main red, dirty, then green."""
    lanes, main = cls.P / "lanes", cls.MAIN
    _ = cls.write(lanes / "red-gate.log", f"sha={main} dirty=0\n...\nexit=1\n")
    _ = cls.write(lanes / "dirty-gate.log", f"sha={main} dirty=3\n...\nexit=0\n")
    _ = cls.write(lanes / "wave1-int-gate.log", f"sha={main} dirty=0\nok\nexit=0\n")


class SinsReview(support.Route):
    """A rung alone asks no review; --sins on also asks a seven-sins verdict.

    --sins on is L's phase end, or the user asked: a gated push then also needs a
    seven-sins verdict (failure-modes F70).
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Leave the gate logs of the gate-log section."""
        super().setUpClass()
        gate_logs(cls)

    def act(self, *extra: str, phase: str = "1", repo: bool = True) -> Result:
        """`--activate` of phase, with --repo R and its sections unless not repo."""
        args: list[object] = [self.P, "--phase", phase]
        if repo:
            args += ["--repo", self.R, "--sections", "1-"]
        return self.py(RS, *args, "--activate", *extra, session="s1")

    def verdict(self, *lines: str) -> None:
        """The review verdict file, one review header before each line."""
        # printf '# pre-push review\n%s\n' "$@": the format repeats for each line
        _ = self.write(
            self.P / "reviews/w2-verdict.md",
            "".join(f"# pre-push review\n{line}\n" for line in lines),
        )

    def test_sins_verdict(self) -> None:
        """A --sins on route's gated push needs a verdict covering what it sends."""
        self.announces_sins()
        self.covers_fixes_and_bases()
        self.counts_slices()
        self.keeps_rung_and_args()

    def announces_sins(self) -> None:
        """--rung L records the rung alone; --sins on is recorded and announced."""
        repo = self.R
        r = self.act("--rung", "L")
        self.ok(
            "activate --rung L: rung in the marker, no review announced",
            grep_file(self.MK(repo), '"rung": "L"') and not grep(r.out, "sins"),
            r.out,
        )
        _ = self.guard(0, repo, "git push origin main")
        r = self.act("--rung", "L", "--sins", "on")
        self.ok(
            "activate --sins on: in the marker, announced",
            grep_file(self.MK(repo), '"sins": "on"')
            and grep(r.out, "sins on: push_guard.py"),
            r.out,
        )

    def covers_fixes_and_bases(self) -> None:
        """A verdict covers its commits and the fixes it lists, none below its base."""
        repo, plan, root, main = self.R, self.P, self.T, self.MAIN
        (plan / "reviews").mkdir()
        _ = self.git("-C", repo, "update-ref", "refs/remotes/origin/main", main)
        one = self.rev(repo, "main~1")
        tree = self.rev(repo, "main^{tree}")
        rev = self.git("-C", repo, "commit-tree", tree, "-p", main, "-m", "reviewed")
        fix = self.git("-C", repo, "commit-tree", tree, "-p", rev, "-m", "fix")
        ung = self.git("-C", repo, "commit-tree", tree, "-p", main, "-m", "ungated")
        _ = self.git("-C", repo, "update-ref", "refs/heads/rel", fix)
        _ = self.git("-C", repo, "update-ref", "refs/heads/ung", ung)
        _ = self.write(plan / "lanes/rel-gate.log", f"sha={fix} dirty=0\nok\nexit=0\n")
        _ = self.guard(2, repo, "git push origin main")
        self.verdict(f"reviewed={main} base={one} blocking=1")
        _ = self.guard(2, repo, "git push origin main")
        self.verdict(f"reviewed={main} base={one} blocking=0")
        _ = self.guard(0, repo, "git push origin main")
        _ = self.guard(0, repo, "git push origin HEAD:main")
        self.verdict(f"reviewed={main[:12]} base={one[:12]} blocking=0")
        _ = self.guard(2, repo, "git push origin main")
        # a fix committed after the review: covered only when listed on after=
        self.verdict(f"reviewed={rev} base={main} blocking=0")
        _ = self.guard(2, repo, "git push origin rel")
        self.verdict(f"reviewed={rev} base={main} blocking=0", f"after={fix}")
        _ = self.guard(0, repo, "git push origin rel")
        self.verdict(f"reviewed={main} base={one} blocking=0", f"after={rev},{fix}")
        _ = self.guard(0, repo, "git push origin rel")
        _ = self.git(
            "-C", repo, "worktree", "add", "-q", "--detach", root / "dw", "rel"
        )
        _ = self.guard(
            0, root / "dw", "git push origin HEAD"
        )  # a detached HEAD names no branch
        _ = self.git("-C", repo, "worktree", "remove", root / "dw")
        # the remote's tip behind the base: commits older than the base would go out
        # unreviewed
        _ = self.git("-C", repo, "update-ref", "refs/remotes/origin/rel", one)
        self.verdict(f"reviewed={rev} base={one} blocking=0", f"after={fix}")
        _ = self.guard(0, repo, "git push origin rel")
        self.verdict(f"reviewed={rev} base={main} blocking=0", f"after={fix}")
        _ = self.guard(2, repo, "git push origin rel")
        _ = self.guard(2, repo, "git push origin rel:rel")
        _ = self.guard(0, repo, "git push origin rel:other")
        _ = self.git("-C", repo, "update-ref", "-d", "refs/remotes/origin/rel")
        # a branch the remote lacks: its base must be on the remote, under any of its
        # refs; a remote with no tracking refs (a URL) is never known to hold it
        self.verdict(f"reviewed={fix} base={rev} blocking=0")
        _ = self.guard(2, repo, "git push origin rel")
        self.verdict(f"reviewed={rev} base={main} blocking=0", f"after={fix}")
        _ = self.guard(2, repo, f"git push {root}/elsewhere.git rel")
        _ = self.guard(0, repo, "git push 'origin' \"rel:other2\"")

    def counts_slices(self) -> None:
        """A review over more than 30 commits counts only as slices of at most 30."""
        repo, plan, main = self.R, self.P, self.MAIN
        tree = self.rev(repo, "main^{tree}")
        # a phase-end review's 31 commits
        c = main
        chain: list[str] = []
        for i in range(1, 32):
            c = self.git("-C", repo, "commit-tree", tree, "-p", c, "-m", f"c{i}")
            chain.append(c)
        c14, c15 = chain[13], chain[14]
        _ = self.git("-C", repo, "update-ref", "refs/heads/wide", c)
        _ = self.write(plan / "lanes/wide-gate.log", f"sha={c} dirty=0\nexit=0\n")
        self.verdict(f"reviewed={c} base={main} blocking=0")
        _ = self.guard(2, repo, "git push origin wide")
        self.verdict(
            f"reviewed={c} base={main} blocking=0", f"slices={main}..{c15} {c15}..{c}"
        )
        _ = self.guard(0, repo, "git push origin wide")
        self.verdict(
            f"reviewed={c} base={main} blocking=0", f"slices={main}..{c14} {c15}..{c}"
        )
        _ = self.guard(2, repo, "git push origin wide")
        self.verdict(f"reviewed={c} base={main} blocking=0", f"slices={main}..{c}")
        _ = self.guard(2, repo, "git push origin wide")
        # one lane's merge of 31 commits splits along the lane's own history
        lm = self.git(
            "-C", repo, "commit-tree", tree, "-p", main, "-p", c, "-m", "merge lane"
        )
        _ = self.git("-C", repo, "update-ref", "refs/heads/wide", lm)
        _ = self.write(plan / "lanes/wide-gate.log", f"sha={lm} dirty=0\nexit=0\n")
        self.verdict(
            f"reviewed={lm} base={main} blocking=0", f"slices={main}..{c15} {c15}..{c}"
        )
        _ = self.guard(0, repo, "git push origin wide")
        _ = self.git("-C", repo, "update-ref", "-d", "refs/heads/wide")
        self.rm(plan / "lanes/wide-gate.log", plan / "reviews/w2-verdict.md")

    def keeps_rung_and_args(self) -> None:
        """A skip is asked; re-activations keep --sins, the rung and the args."""
        repo = self.R
        _ = self.guard("ask", repo, "DSP_SKIP_REVIEW=1 git push origin main")
        _ = self.guard(2, repo, "DSP_SKIP_REVIEW=1 git push origin ung")
        _ = self.guard("ask", repo, "DSP_SKIP_PUSH_GUARD=1 git push origin ung")
        _ = self.act("--rung", "S")
        _ = self.guard(
            2, repo, "git push origin main"
        )  # --sins on is kept across re-activations
        _ = self.act("--rung", "S", "--sins", "off")
        _ = self.guard(0, repo, "git push origin main")
        _ = self.act()
        _ = self.guard(0, repo, "git push origin main")
        m = self.marker()
        self.ok(
            "a re-activation of the phase without --rung keeps its rung",
            m.get("rung") == "S",
            json.dumps(m),
        )
        _ = self.act(phase="2")
        self.ok(
            "a new phase without --rung has none", not grep_file(self.MK(repo), "rung")
        )
        _ = self.act()
        # execution.md's `--activate --sins on` names neither --repo nor --sections:
        # both kept
        before = self.marker()["args"]
        _ = self.act("--sins", "off", repo=False)
        after = self.marker()["args"]
        self.ok(
            "a re-activation keeps --repo, --sections and --main",
            after == before,
            f"{before} -> {after}",
        )


class CiHarness(support.Route):
    """A suite CI runs that the local gate does not.

    A gated push also needs that harness's log (F90).
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Leave the gate logs, and the route at rung S with sins off."""
        super().setUpClass()
        gate_logs(cls)
        # the sins section leaves the route at rung S, sins off
        _ = cls.activate_route("--rung", "S", "--sins", "off")

    def activate_ci(self, *extra: str, merge: bool = False) -> Result:
        """`route_state.py --activate` of phase 1 on R, plus extra."""
        return self.py(
            RS,
            self.P,
            "--phase",
            "1",
            "--repo",
            self.R,
            "--sections",
            "1-",
            "--activate",
            *extra,
            session="s1",
            merge=merge,
        )

    def test_ci_harness(self) -> None:
        """A route naming a CI harness holds a push until that harness's log passes."""
        repo, plan, main = self.R, self.P, self.MAIN
        r = self.activate_ci("--ci-harness", "it-3db")
        self.ok(
            "activate --ci-harness: in the marker, announced",
            grep_file(self.MK(repo), '"ci_harness": "it-3db"')
            and grep(r.out, "CI harness it-3db: push_guard.py"),
            r.out,
        )
        stdin = json.dumps(
            {"tool_input": {"command": "git push origin main"}, "cwd": str(repo)}
        )
        r = self.py(support.GUARD, input=stdin, merge=True)
        self.ok(
            "guard: a commit gated locally only is held, with the harness log's "
            "command",
            r.code == HELD
            and grep(r.out, "^  not passed by the CI harness: main = ")
            and grep(r.out, "gate.py .* --harness it-3db -- "),
            r.out,
        )
        # the branch push that starts the CI run cannot carry its log
        _ = self.guard(0, repo, "git push origin main:refs/heads/ci-run")
        _ = self.guard(2, repo, "git push origin main:refs/heads/main")
        _ = self.guard(2, repo, "git push origin main:refs/tags/v9")
        # ...a bare name is read against the remote's refs, which may hold a tag of that
        # name
        _ = self.guard(2, repo, "git push origin main:ci-run")
        _ = self.guard(2, repo, "git push origin main:heads/main")
        _ = self.guard(2, repo, "git push origin main:refs/remotes/origin/x")
        _ = self.activate_ci("--main", "refs/heads/main")
        _ = self.guard(2, repo, "git push origin main:refs/heads/main")
        _ = self.activate_ci("--main", "main")
        log = plan / "lanes/ci-it-3db-gate.log"
        _ = self.write(log, f"sha={main} dirty=0\nharness=it-3db\nok\nexit=1\n")
        _ = self.guard(2, repo, "git push origin main")
        _ = self.write(log, f"sha={main} dirty=0\nharness=other\nok\nexit=0\n")
        _ = self.guard(2, repo, "git push origin main")
        _ = self.write(log, f"sha={main} dirty=0\nharness=it-3db\nok\nexit=0\n")
        _ = self.guard(0, repo, "git push origin main")
        _ = self.activate_ci()
        self.ok(
            "a re-activation keeps the CI harness",
            grep_file(self.MK(repo), '"ci_harness": "it-3db"'),
        )
        log.unlink()
        _ = self.guard(2, repo, "git push origin main")
        _ = self.activate_ci("--ci-harness", "none")
        _ = self.guard(0, repo, "git push origin main")
        self.ok(
            "--ci-harness none clears it", not grep_file(self.MK(repo), "ci_harness")
        )
        # CI on a runner this host is not: activation says so until the route names a
        # harness or none (live: Windows CI was "the only test" and no harness was ever
        # set)
        _ = self.write(
            repo / ".github/workflows/ci.yml",
            "jobs:\n  t:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n"
            "        os: [ubuntu-latest, windows-latest]\n",
        )
        self.edit_marker(lambda m: m.pop("ci_none", None))
        r = self.activate_ci(merge=True)
        self.ok(
            "activate: CI on another OS asks for a harness",
            r.code == 1
            and grep(r.out, "CI runs on windows-latest")
            and grep(r.out, "--ci-harness none"),
            r.out,
        )
        _ = self.activate_ci("--ci-harness", "none")
        r = self.activate_ci(merge=True)
        self.ok(
            "--ci-harness none is remembered as the answer",
            r.code == 0 and not grep(r.out, "CI runs on"),
            r.out,
        )
        self.rm(repo / ".github")


if __name__ == "__main__":
    _ = unittest.main()
