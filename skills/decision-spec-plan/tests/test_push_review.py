"""push_guard.py's checks past the gate log: the seven-sins verdict a `--sins on` route needs on a
gated push (F70), and the CI harness log a route that names one needs (F90)."""

import json
import unittest

import support
from support import RS, grep, grep_file


def gate_logs(cls):
    """The gate logs the gate-log section leaves: main red, dirty, then green."""
    lanes, main = cls.P / "lanes", cls.MAIN
    cls.write(lanes / "red-gate.log", f"sha={main} dirty=0\n...\nexit=1\n")
    cls.write(lanes / "dirty-gate.log", f"sha={main} dirty=3\n...\nexit=0\n")
    cls.write(lanes / "wave1-int-gate.log", f"sha={main} dirty=0\nok\nexit=0\n")


class SinsReview(support.Route):
    """A rung alone asks no review; --sins on (L's phase end, or the user asked): a gated push
    also needs a seven-sins verdict (failure-modes F70)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        gate_logs(cls)

    def act(self, *extra, phase="1", repo=True):
        args = [self.P, "--phase", phase]
        if repo:
            args += ["--repo", self.R, "--sections", "1-"]
        return self.py(RS, *args, "--activate", *extra, session="s1")

    def verdict(self, *lines):
        # printf '# pre-push review\n%s\n' "$@": the format repeats for each line
        self.write(
            self.P / "reviews/w2-verdict.md",
            "".join(f"# pre-push review\n{line}\n" for line in lines),
        )

    def test_sins_verdict(self):
        R, P, T, MAIN = self.R, self.P, self.T, self.MAIN
        r = self.act("--rung", "L")
        self.ok(
            "activate --rung L: rung in the marker, no review announced",
            grep_file(self.MK(R), '"rung": "L"') and not grep(r.out, "sins"),
            r.out,
        )
        self.guard(0, R, "git push origin main")
        r = self.act("--rung", "L", "--sins", "on")
        self.ok(
            "activate --sins on: in the marker, announced",
            grep_file(self.MK(R), '"sins": "on"')
            and grep(r.out, "sins on: push_guard.py"),
            r.out,
        )
        (P / "reviews").mkdir()
        self.git("-C", R, "update-ref", "refs/remotes/origin/main", MAIN)
        ONE = self.rev(R, "main~1")
        TREE = self.rev(R, "main^{tree}")
        REV = self.git("-C", R, "commit-tree", TREE, "-p", MAIN, "-m", "reviewed")
        FIX = self.git("-C", R, "commit-tree", TREE, "-p", REV, "-m", "fix")
        UNG = self.git("-C", R, "commit-tree", TREE, "-p", MAIN, "-m", "ungated")
        self.git("-C", R, "update-ref", "refs/heads/rel", FIX)
        self.git("-C", R, "update-ref", "refs/heads/ung", UNG)
        self.write(P / "lanes/rel-gate.log", f"sha={FIX} dirty=0\nok\nexit=0\n")
        self.guard(2, R, "git push origin main")
        self.verdict(f"reviewed={MAIN} base={ONE} blocking=1")
        self.guard(2, R, "git push origin main")
        self.verdict(f"reviewed={MAIN} base={ONE} blocking=0")
        self.guard(0, R, "git push origin main")
        self.guard(0, R, "git push origin HEAD:main")
        self.verdict(f"reviewed={MAIN[:12]} base={ONE[:12]} blocking=0")
        self.guard(2, R, "git push origin main")
        # a fix committed after the review: covered only when listed on after=
        self.verdict(f"reviewed={REV} base={MAIN} blocking=0")
        self.guard(2, R, "git push origin rel")
        self.verdict(f"reviewed={REV} base={MAIN} blocking=0", f"after={FIX}")
        self.guard(0, R, "git push origin rel")
        self.verdict(f"reviewed={MAIN} base={ONE} blocking=0", f"after={REV},{FIX}")
        self.guard(0, R, "git push origin rel")
        self.git("-C", R, "worktree", "add", "-q", "--detach", T / "dw", "rel")
        self.guard(
            0, T / "dw", "git push origin HEAD"
        )  # a detached HEAD names no branch
        self.git("-C", R, "worktree", "remove", T / "dw")
        # the remote's tip behind the base: commits older than the base would go out unreviewed
        self.git("-C", R, "update-ref", "refs/remotes/origin/rel", ONE)
        self.verdict(f"reviewed={REV} base={ONE} blocking=0", f"after={FIX}")
        self.guard(0, R, "git push origin rel")
        self.verdict(f"reviewed={REV} base={MAIN} blocking=0", f"after={FIX}")
        self.guard(2, R, "git push origin rel")
        self.guard(2, R, "git push origin rel:rel")
        self.guard(0, R, "git push origin rel:other")
        self.git("-C", R, "update-ref", "-d", "refs/remotes/origin/rel")
        # a branch the remote lacks: its base must be on the remote, under any of its refs; a
        # remote with no tracking refs (a URL) is never known to hold it
        self.verdict(f"reviewed={FIX} base={REV} blocking=0")
        self.guard(2, R, "git push origin rel")
        self.verdict(f"reviewed={REV} base={MAIN} blocking=0", f"after={FIX}")
        self.guard(2, R, f"git push {T}/elsewhere.git rel")
        self.guard(0, R, "git push 'origin' \"rel:other2\"")
        # a phase-end review over more than 30 commits counts only as slices of at most 30
        C = MAIN
        C14 = C15 = ""
        for i in range(1, 32):
            C = self.git("-C", R, "commit-tree", TREE, "-p", C, "-m", f"c{i}")
            if i == 15:
                C15 = C
            if i == 14:
                C14 = C
        self.git("-C", R, "update-ref", "refs/heads/wide", C)
        self.write(P / "lanes/wide-gate.log", f"sha={C} dirty=0\nexit=0\n")
        self.verdict(f"reviewed={C} base={MAIN} blocking=0")
        self.guard(2, R, "git push origin wide")
        self.verdict(
            f"reviewed={C} base={MAIN} blocking=0", f"slices={MAIN}..{C15} {C15}..{C}"
        )
        self.guard(0, R, "git push origin wide")
        self.verdict(
            f"reviewed={C} base={MAIN} blocking=0", f"slices={MAIN}..{C14} {C15}..{C}"
        )
        self.guard(2, R, "git push origin wide")
        self.verdict(f"reviewed={C} base={MAIN} blocking=0", f"slices={MAIN}..{C}")
        self.guard(2, R, "git push origin wide")
        # one lane's merge of 31 commits splits along the lane's own history
        LM = self.git(
            "-C", R, "commit-tree", TREE, "-p", MAIN, "-p", C, "-m", "merge lane"
        )
        self.git("-C", R, "update-ref", "refs/heads/wide", LM)
        self.write(P / "lanes/wide-gate.log", f"sha={LM} dirty=0\nexit=0\n")
        self.verdict(
            f"reviewed={LM} base={MAIN} blocking=0", f"slices={MAIN}..{C15} {C15}..{C}"
        )
        self.guard(0, R, "git push origin wide")
        self.git("-C", R, "update-ref", "-d", "refs/heads/wide")
        self.rm(P / "lanes/wide-gate.log", P / "reviews/w2-verdict.md")
        self.guard("ask", R, "DSP_SKIP_REVIEW=1 git push origin main")
        self.guard(2, R, "DSP_SKIP_REVIEW=1 git push origin ung")
        self.guard("ask", R, "DSP_SKIP_PUSH_GUARD=1 git push origin ung")
        self.act("--rung", "S")
        self.guard(
            2, R, "git push origin main"
        )  # --sins on is kept across re-activations
        self.act("--rung", "S", "--sins", "off")
        self.guard(0, R, "git push origin main")
        self.act()
        self.guard(0, R, "git push origin main")
        m = self.marker()
        self.ok(
            "a re-activation of the phase without --rung keeps its rung",
            m.get("rung") == "S",
            json.dumps(m),
        )
        self.act(phase="2")
        self.ok(
            "a new phase without --rung has none", not grep_file(self.MK(R), "rung")
        )
        self.act()
        # execution.md's `--activate --sins on` names neither --repo nor --sections: both kept
        before = self.marker()["args"]
        self.act("--sins", "off", repo=False)
        after = self.marker()["args"]
        self.ok(
            "a re-activation keeps --repo, --sections and --main",
            after == before,
            f"{before} -> {after}",
        )


class CiHarness(support.Route):
    """A suite CI runs that the local gate does not: a gated push also needs that harness's log
    (F90)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        gate_logs(cls)
        # the sins section leaves the route at rung S, sins off
        cls.activate_route("--rung", "S", "--sins", "off")

    def activate_ci(self, *extra, merge=False):
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

    def test_ci_harness(self):
        R, P, MAIN = self.R, self.P, self.MAIN
        r = self.activate_ci("--ci-harness", "it-3db")
        self.ok(
            "activate --ci-harness: in the marker, announced",
            grep_file(self.MK(R), '"ci_harness": "it-3db"')
            and grep(r.out, "CI harness it-3db: push_guard.py"),
            r.out,
        )
        stdin = json.dumps(
            {"tool_input": {"command": "git push origin main"}, "cwd": str(R)}
        )
        r = self.py(support.GUARD, input=stdin, merge=True)
        self.ok(
            "guard: a commit gated locally only is held, with the harness log's command",
            r.code == 2
            and grep(r.out, "^  not passed by the CI harness: main = ")
            and grep(r.out, "gate.py .* --harness it-3db -- "),
            r.out,
        )
        # the branch push that starts the CI run cannot carry its log
        self.guard(0, R, "git push origin main:refs/heads/ci-run")
        self.guard(2, R, "git push origin main:refs/heads/main")
        self.guard(2, R, "git push origin main:refs/tags/v9")
        # ...a bare name is read against the remote's refs, which may hold a tag of that name
        self.guard(2, R, "git push origin main:ci-run")
        self.guard(2, R, "git push origin main:heads/main")
        self.guard(2, R, "git push origin main:refs/remotes/origin/x")
        self.activate_ci("--main", "refs/heads/main")
        self.guard(2, R, "git push origin main:refs/heads/main")
        self.activate_ci("--main", "main")
        log = P / "lanes/ci-it-3db-gate.log"
        self.write(log, f"sha={MAIN} dirty=0\nharness=it-3db\nok\nexit=1\n")
        self.guard(2, R, "git push origin main")
        self.write(log, f"sha={MAIN} dirty=0\nharness=other\nok\nexit=0\n")
        self.guard(2, R, "git push origin main")
        self.write(log, f"sha={MAIN} dirty=0\nharness=it-3db\nok\nexit=0\n")
        self.guard(0, R, "git push origin main")
        self.activate_ci()
        self.ok(
            "a re-activation keeps the CI harness",
            grep_file(self.MK(R), '"ci_harness": "it-3db"'),
        )
        log.unlink()
        self.guard(2, R, "git push origin main")
        self.activate_ci("--ci-harness", "none")
        self.guard(0, R, "git push origin main")
        self.ok("--ci-harness none clears it", not grep_file(self.MK(R), "ci_harness"))
        # CI on a runner this host is not: activation says so until the route names a harness or
        # none (live: Windows CI was "the only test" and no harness was ever set)
        self.write(
            R / ".github/workflows/ci.yml",
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
        self.activate_ci("--ci-harness", "none")
        r = self.activate_ci(merge=True)
        self.ok(
            "--ci-harness none is remembered as the answer",
            r.code == 0 and not grep(r.out, "CI runs on"),
            r.out,
        )
        self.rm(R / ".github")


if __name__ == "__main__":
    unittest.main()
