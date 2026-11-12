# SPDX-License-Identifier: MIT
"""The route report as data: `collect()`, `derive()`, `render()`, and the wave edges.

`collect()` returns a round's facts as one JSON-native object, `derive()` computes
every lane state and flag from them, and `render()` prints today's text from the object
alone. `scope_check.edges()` gives each plan's direct edges, the plans its `Depends on`
cell names and the waves an `all` cell waits for; `depends()` closes over them.
"""

import contextlib
import hashlib
import io
import os
import sys
from pathlib import Path
from unittest import mock

from typing_extensions import override

import report_shapes
import scope_check
import support
from dsp_route.common import RouteArgs, parser
from report_shapes import GOLDEN, collect_json, mask
from support import RS, ev

# the seven golden shapes, each rendered without and with --all
QUIET_RUNS = 14
# (id, basis, state, gate) of each lane, its merged_how, the gate logs' states, the
# flag kinds: what shapes 2-4 were built to hold
OBJECTS: dict[
    str,
    tuple[
        list[tuple[str, str, str, str | None]],
        list[str | None],
        list[str],
        list[str],
    ],
] = {
    "2-merged": (
        [
            ("p1-01-a", "merged", "merged", None),
            ("p1-02-a", "merged", "merged", None),
            ("p1-03-a", "merged", "merged", None),
            ("p1-04", "planned", "queued", None),
        ],
        ["ancestor", "patch", "record"],
        [],
        ["base-drift"],
    ),
    "3-open": (
        [(f"p1-0{n}-a", "open", "running", "none") for n in (1, 2, 3)],
        [None, None, None],
        [],
        ["no-final-sha", "checkpoint-long", "rulings-large"],
    ),
    "4-gates": (
        [
            ("p1-01-a", "open", "red", "red"),
            ("p1-02-a", "open", "ready", "green"),
            ("p1-03-a", "open", "gating", "no-exit"),
            ("p1-04-a", "open", "running", "dirty"),
        ],
        [None, None, None, None],
        ["red", "red", "green", "no-exit", "green"],
        ["gate-red", "gate-red", "gate-no-exit"],
    ),
}


class _Loud(io.StringIO):
    """A stream that fails on any write: collect() must print nothing."""

    @override
    def write(self, s: str, /) -> int:
        """Fail with what was written."""
        msg = f"collect() wrote {s!r}"
        raise AssertionError(msg)


def _args(argv: list[str]) -> RouteArgs:
    """Return the route arguments the CLI parses from argv."""
    return parser().parse_args(argv, namespace=RouteArgs())


def _spawns(log: Path) -> int:
    """Return how many git spawns a shim's log holds."""
    return len(log.read_text().splitlines()) if log.exists() else 0


def _snapshot(*roots: Path) -> dict[str, tuple[int, int, str]]:
    """Return (size, mtime_ns, SHA-1) of every file under roots."""
    out: dict[str, tuple[int, int, str]] = {}
    for root in roots:
        for d, _, files in os.walk(root):
            for f in files:
                p = Path(d) / f
                st = p.stat()
                digest = hashlib.sha1(p.read_bytes(), usedforsecurity=False)
                out[str(p)] = (st.st_size, st.st_mtime_ns, digest.hexdigest())
    return out


class ShapeData(report_shapes.Shapes):
    """The object of the golden shapes and of a route holding every lane state."""

    def test_object(self) -> None:
        """Shapes 2-4: each lane's basis, state and gate, the logs' states, flags."""
        from dsp_route import report

        for key, (want, how, logs, kinds) in OBJECTS.items():
            s = collect_json(type(self), GOLDEN[key]["argv"])
            lanes = [
                (ln["id"], ln["basis"], ln["state"], ln["gate"]) for ln in s["lanes"]
            ]
            git = s["git"]
            got = (
                lanes,
                [g["merged_how"] for g in git["lanes"].values()] if git else [],
                [report.gate_state(g) for g in s["gate_logs"]],
                [f["kind"] for f in s["flags"]],
            )
            self.ok(
                f"shape {key}: {len(lanes)} lanes",
                s["version"] == report.VERSION
                and len(lanes) > 0
                and got == (want, how, logs, kinds),
                got,
            )

    def test_separable(self) -> None:
        """No git spawn without git; older git facts laid over newer file facts."""
        from dsp_route import report

        argv = report_shapes.lane_states(type(self), self.T / "ls")
        env, log = self.git_shim(self.T / "shim")
        free = collect_json(type(self), argv, use_git=False, env=env)
        none = _spawns(log)
        older = collect_json(type(self), argv, env=env)
        some = _spawns(log) - none
        self.ok(
            f"git spawns: {none} without git, {some} with it",
            none == 0 and free["git"] is None and some > 0,
            free["git"],
        )
        plan, repo = Path(argv[0]), argv[4]
        _ = self.write(
            plan / "lanes/p1-04-a-checkpoint.md",
            f"Final SHA: {self.rev(repo, 'main~1')}\n",
        )
        fs = collect_json(type(self), argv, use_git=False)
        mixed = report.derive({**fs, "git": older["git"]})

        def states(s: report.State) -> dict[str, tuple[str, str, str | None]]:
            return {
                ln["id"]: (ln["basis"], ln["state"], ln["gate"]) for ln in s["lanes"]
            }

        got, was = states(mixed), states(older)
        want = {**was, "p1-04-a": ("unchecked", "running", None)}
        self.ok(
            f"older git over newer files: {len(got)} lanes, p1-04-a unchecked",
            len(got) == len(report.LANE_STATES) + 3 and got == want,
            f"{got}\n{was}",
        )
        for key, shape in GOLDEN.items():
            s = collect_json(type(self), shape["argv"])
            self.ok(
                f"derive(s) == s, shape {key} of {len(GOLDEN)}", report.derive(s) == s
            )

    def test_quiet(self) -> None:
        """collect() prints nothing; render() is report()'s text."""
        from dsp_route import report

        n = 0
        with mock.patch.dict(os.environ, self.env, clear=True):
            for key, shape in GOLDEN.items():
                for show_all in (False, True):
                    a = _args([*shape["argv"], *(["--all"] if show_all else [])])
                    if key == "7-odd":
                        self.freshen()
                    with (
                        mock.patch.object(sys, "stdout", _Loud()),
                        mock.patch.object(sys, "stderr", _Loud()),
                    ):
                        state = report.collect(a)
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        _ = report.report(a)
                    text = report.render(state, show_all=show_all) if state else ""
                    n += mask(text) == mask(buf.getvalue().removesuffix("\n"))
        self.ok(
            f"render() is report()'s text: {n} of {QUIET_RUNS}",
            n == 2 * len(GOLDEN) == QUIET_RUNS,
        )


class MonitorUse(support.Sandbox):
    """A reader of the object on a live route writes nothing; a CLI report does."""

    def commit(self, repo: Path, name: str, message: str) -> str:
        """Return the SHA of a commit in repo writing name."""
        _ = self.write(repo / name, f"{message}\n")
        _ = self.git("-C", repo, "add", name)
        _ = self.git("-C", repo, "commit", "-q", "-m", message)
        return self.rev(repo)

    def test_monitor_use(self) -> None:
        """collect() on a route its hook and CLI report keep changes no file."""
        root = self.T / "m"
        r = self.init_repo(root / "r", commits=("base",))
        _ = self.commit(r, "g", "g")
        plan = r / ".plan"
        shas: dict[int, str] = {}
        for n in (1, 2, 3):
            _ = self.git("-C", r, "switch", "-q", "-c", f"p1-0{n}-a", "main")
            shas[n] = self.commit(r, f"f{n}", f"p1-0{n}-a")
            _ = self.git("-C", r, "switch", "-q", "main")
            _ = self.write(
                plan / f"lanes/p1-0{n}-a-checkpoint.md", f"Final SHA: {shas[n]}\n"
            )
        _ = self.git("-C", r, "merge", "-q", "--no-ff", "-m", "merge 1", "p1-01-a")
        wt = root / "wt-02"
        _ = self.git("-C", r, "worktree", "add", "-q", wt, "p1-02-a")
        self.stat_dirty(wt / "g")
        argv = [str(plan), "--phase", "1", "--repo", str(r), "--main", "main"]
        act = self.py(RS, *argv, "--activate", session="m1", cwd=self.T, merge=True)
        self.ok("the route is activated", act.code == 0, act.out)
        _ = self.py(RS, *argv)
        for f in (self.HOME / ".claude/dsp-routes").glob("*.checked"):
            f.unlink()
        _ = self.hook_out(ev("PostToolUse", "m1", '"tool_name":"Read"'))
        marker = support.Route.MK(r, plan)
        merged = marker.with_suffix(".merged")
        self.ok(
            "the hook kept its .last, the CLI its cache",
            marker.with_name(f"{marker.stem}.m1.last").exists() and merged.exists(),
        )
        # the cache is now stale: it lacks p1-03
        _ = self.git("-C", r, "merge", "-q", "--no-ff", "-m", "merge 3", "p1-03-a")
        roots = (plan, r / ".git", self.HOME / ".claude/dsp-routes")
        before, index = _snapshot(*roots), self.index_state(wt)
        _ = collect_json(type(self), argv)
        after, index_after = _snapshot(*roots), self.index_state(wt)
        self.ok(
            f"collect() changed none of {len(before)} files, nor the lane's index",
            len(before) > 0
            and before == after
            and index == index_after
            and not index_after[3],
            {k: (v, after.get(k)) for k, v in before.items() if after.get(k) != v},
        )
        _ = self.py(RS, *argv)
        self.ok(
            "control: a CLI report rewrites the stale cache",
            _snapshot(merged.parent).get(str(merged)) != before.get(str(merged)),
        )


INDEX = """# Phase 1 plans

| Plan | Wave | Depends on |
|---|---|---|
| p1-01-a | 0 | — |
| p1-02-b | 1 | p1-01 |
| p1-03-c | 1 | p1-01, p1-02 |
| p1-04-d | 2 | all of wave 1 |
| p1-05-e | 3 | all |
| p1-06-f | — | all |
"""


class WaveEdges(support.Sandbox):
    """Named plans, named waves, every earlier wave, and a row with no wave."""

    def test_edges(self) -> None:
        """Each row's direct edges, and the closure depends() builds on them."""
        index = self.write(self.T / "plans/p1-00-index.md", INDEX)
        rows = scope_check.plan_table(str(index))
        got = scope_check.edges(rows)
        self.ok(
            f"edges of every row: {len(got)} rows",
            len(got) > 0
            and got
            == {
                "p1-01-a": (set(), set()),
                "p1-02-b": ({"p1-01-a"}, set()),
                "p1-03-c": ({"p1-01-a", "p1-02-b"}, set()),
                "p1-04-d": (set(), {1}),
                "p1-05-e": (set(), {0, 1, 2}),
                "p1-06-f": (set(), set()),
            },
            got,
        )
        # what depends() returned on this index before it was built on edges()
        reach = scope_check.depends(rows)
        self.ok(
            f"depends() unchanged: {len(reach)} rows",
            len(reach) > 0
            and reach
            == {
                "p1-01-a": set(),
                "p1-02-b": {"p1-01-a"},
                "p1-03-c": {"p1-01-a", "p1-02-b"},
                "p1-04-d": {"p1-01-a", "p1-02-b", "p1-03-c"},
                "p1-05-e": {"p1-01-a", "p1-02-b", "p1-03-c", "p1-04-d"},
                "p1-06-f": set(),
            },
            reach,
        )
