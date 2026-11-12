# SPDX-License-Identifier: MIT
"""The route report as data: `collect()`, `derive()`, `render()`, and the wave edges.

`collect()` returns a round's facts as one JSON-native object, `derive()` computes
every lane state and flag from them, and `render()` prints today's text from the object
alone. `scope_check.edges()` gives each plan's direct edges, the plans its `Depends on`
cell names and the waves an `all` cell waits for; `depends()` closes over them. The
object carries both by plan id, the route's stage strip, and only its enums' values.
"""

import contextlib
import hashlib
import io
import os
import re
import subprocess
import sys
import threading
from collections.abc import Generator
from pathlib import Path
from unittest import mock

from typing_extensions import override

import report_shapes
import scope_check
import support
from dsp_route.common import GitDeadlineError, RouteArgs, git_deadline, parser
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


class Waves(support.Sandbox):
    """Each plan's wave and dependencies in the object, by plan id (AC-P1-2-21)."""

    def test_waves(self) -> None:
        """after, after_waves and waits_for are edges() and depends() by plan id."""
        plan = self.T / "w"
        index = self.write(plan / "plans/p1-00-index.md", INDEX)
        argv = [str(plan), "--phase", "1"]
        waves = collect_json(type(self), argv, use_git=False)["waves"]
        rows = scope_check.plan_table(str(index))
        direct, reach = scope_check.edges(rows), scope_check.depends(rows)

        def ident(stem: str) -> str:
            m = scope_check.PLAN_ID.match(stem)
            return m[0] if m else stem

        want = {
            ident(s): (
                sorted(map(ident, direct[s][0])),
                sorted(direct[s][1]),
                sorted(map(ident, reach[s])),
            )
            for s in rows
        }
        got = {
            i: (w["after"], w["after_waves"], w["waits_for"]) for i, w in waves.items()
        }
        ids = [
            *waves,
            *(o for w in waves.values() for o in w["after"] + w["waits_for"]),
        ]
        self.ok(
            f"waves of {len(got)} plans, by plan id",
            len(got) == len(rows) > 0
            and got == want
            and got["p1-04"][1] == [1]
            and got["p1-05"][1] == [0, 1, 2]
            and all(PLAN_ONLY.fullmatch(i) for i in ids),
            f"{got}\n{want}",
        )


# a plan id and nothing else
PLAN_ONLY = re.compile(r"p\d+-\d+[a-z]?")
# a stage state's letter in a strip of the eight, in STAGES order
LETTER = {"done": "d", "current": "c", "skipped": "s", "not-reached": "n"}
DEC = "decisions/phase1/"
IDX, SEAMS, ARB, FRAMING = (
    f"{DEC}00-index.md",
    f"{DEC}00-seams.md",
    f"{DEC}00-arbiter.md",
    f"{DEC}00-framing-review.md",
)
SPEC, PLAN, CKPT = "spec/1-a.md", "plans/p1-01-a.md", "lanes/p1-01-a-checkpoint.md"
SECTIONS = ("--sections", "1-")
RUNG_S = (*SECTIONS, "--rung", "S")
# (fixture, its files, its arguments, its strip): planning dirs without git
FILE_STAGES: list[tuple[str, tuple[str, ...], tuple[str, ...], str]] = [
    ("harvest only", (), (), "cnnnnnnn"),
    ("+ index", (IDX,), (), "dcnnnnnn"),
    ("+ seams", (IDX, SEAMS), (), "ddcnnnnn"),
    ("+ arbiter", (IDX, SEAMS, ARB), (), "dddcnnnn"),
    ("+ spec", (IDX, SEAMS, ARB, SPEC), SECTIONS, "ddddcnnn"),
    ("+ plan", (IDX, SEAMS, ARB, SPEC, PLAN), SECTIONS, "dddddcnn"),
    ("+ checkpoint", (IDX, SEAMS, ARB, SPEC, PLAN, CKPT), SECTIONS, "ddddddcn"),
    ("rung S, no review, no exec", (IDX, SPEC, PLAN), RUNG_S, "ddnddcnn"),
    ("rung S, a checkpoint, no review", (IDX, SPEC, PLAN, CKPT), RUNG_S, "ddsdddcn"),
    ("rung S, framing review", (IDX, FRAMING, SPEC, PLAN), RUNG_S, "dddddcnn"),
    ("no --sections, no reconcile", (IDX, SEAMS, ARB, PLAN), (), "ddddscnn"),
]
# (main pushed: none, after the merge, before it; its strip) of an exec-complete route
GIT_STAGES = (("none", "dddddddc"), ("pushed", "dddddddd"), ("stale", "dddddddc"))
STAGE_FIXTURES = 15


class Stages(support.Sandbox):
    """Each stage's state from a route's files, git and rung (AC-P1-2-20)."""

    def exec_route(self, root: Path, push: str) -> list[str]:
        """Return the arguments of a route whose one plan id's lane is merged.

        push: main never pushed (none), pushed after the merge, or before it (stale).
        """
        r = self.init_repo(root / "r", commits=("base",))
        if push != "none":
            _ = self.git("init", "-q", "--bare", root / "o.git")
            _ = self.git("-C", r, "remote", "add", "origin", root / "o.git")
        if push == "stale":
            _ = self.git("-C", r, "push", "-q", "-u", "origin", "main")
        _ = self.git("-C", r, "switch", "-q", "-c", "p1-01-a")
        _ = self.write(r / "f1", "lane\n")
        _ = self.git("-C", r, "add", "f1")
        _ = self.git("-C", r, "commit", "-q", "-m", "p1-01-a")
        sha = self.rev(r)
        _ = self.git("-C", r, "switch", "-q", "main")
        _ = self.git("-C", r, "merge", "-q", "--no-ff", "-m", "merge", "p1-01-a")
        if push == "pushed":
            _ = self.git("-C", r, "push", "-q", "-u", "origin", "main")
        plan = r / ".plan"
        for f in (IDX, SEAMS, ARB, SPEC, PLAN):
            _ = self.write(plan / f, "x\n")
        _ = self.write(plan / CKPT, f"Final SHA: {sha}\n")
        _ = self.write(
            plan / "plans/p1-00-index.md",
            "| Plan | Wave | Depends on |\n|---|---|---|\n| p1-01-a | 1 | — |\n",
        )
        return [
            str(plan),
            "--phase",
            "1",
            "--repo",
            str(r),
            "--main",
            "main",
            *SECTIONS,
        ]

    def test_stages(self) -> None:
        """The eight states of every fixture, in STAGES order."""
        from dsp_route import report

        cases: list[tuple[str, list[str], bool, str]] = []
        for n, (label, files, extra, want) in enumerate(FILE_STAGES):
            plan = self.T / f"f{n}"
            plan.mkdir(parents=True)
            for f in files:
                _ = self.write(plan / f, "x\n")
            cases.append((label, [str(plan), "--phase", "1", *extra], False, want))
        for push, want in GIT_STAGES:
            argv = self.exec_route(self.T / push, push)
            cases.append((f"exec complete, push {push}", argv, True, want))
        cases.append(("exec complete, no git", cases[-3][1], False, "ddddddcn"))
        got: dict[str, str] = {}
        names: set[tuple[str, ...]] = set()
        for label, argv, use_git, _ in cases:
            stages = collect_json(type(self), argv, use_git=use_git)["stages"]
            names.add(tuple(s["name"] for s in stages))
            got[label] = "".join(LETTER.get(s["state"], "?") for s in stages)
        want = {label: w for label, _, _, w in cases}
        self.ok(
            f"stage strips of {len(cases)} fixtures",
            len(cases) == STAGE_FIXTURES and got == want and names == {report.STAGES},
            {k: (got[k], w) for k, w in want.items() if got[k] != w},
        )


class Enums(report_shapes.Shapes):
    """Every enum value the object emits is its constant's, and every one is emitted.

    Over the seven golden shapes and the route holding every lane state (AC-P1-2-19).
    """

    def test_enums(self) -> None:
        """Stage names and states, lane states, bases and gates, flag kinds."""
        from dsp_route import report

        states = [collect_json(type(self), s["argv"]) for s in GOLDEN.values()]
        states.append(
            collect_json(
                type(self), report_shapes.lane_states(type(self), self.T / "ls")
            )
        )
        stages = [s for x in states for s in x["stages"]]
        lanes = [ln for x in states for ln in x["lanes"]]
        emitted: dict[str, tuple[tuple[str, ...], set[str]]] = {
            "STAGES": (report.STAGES, {s["name"] for s in stages}),
            "STAGE_STATES": (report.STAGE_STATES, {s["state"] for s in stages}),
            "LANE_STATES": (report.LANE_STATES, {ln["state"] for ln in lanes}),
            "LANE_BASES": (report.LANE_BASES, {ln["basis"] for ln in lanes}),
            "GATE_STATES": (
                report.GATE_STATES,
                {g for ln in lanes if (g := ln["gate"]) is not None},
            ),
            "FLAG_KINDS": (
                report.FLAG_KINDS,
                {f["kind"] for x in states for f in x["flags"]},
            ),
        }
        for name, (values, got) in emitted.items():
            self.ok(
                f"{name}: {len(values)} values, {len(got & set(values))} emitted",
                len(values) > 0 and got == set(values),
                f"not emitted {sorted(set(values) - got)}, "
                f"not in {name} {sorted(got - set(values))}",
            )


# one lane merged by ancestry and ten open ones
DEADLINE_LANES = 11
# 1.0 s over a 0.2 s git: five spawns finish, the sixth is stopped
DEADLINE_SPAWNS = 6


@contextlib.contextmanager
def spawns() -> Generator[list[float | None], None, None]:
    """The timeout of each `subprocess.run` inside the block, filled as it exits.

    git() passes the time left on its deadline, so one with none left, or none at all,
    started after the deadline. Taken in this process: the shim's own stamp trails a
    spawn by however long the host takes to schedule it.
    """
    left: list[float | None] = []
    with mock.patch.object(subprocess, "run", wraps=subprocess.run) as run:
        try:
            yield left
        finally:
            left.extend(c.kwargs.get("timeout") for c in run.call_args_list)


class Deadline(support.Sandbox):
    """The git deadline bounds collect(); a report it cuts short caches nothing.

    AC-P1-2-23. Nothing on collect()'s path may catch the deadline's error, which is
    an OSError: this is the guard.
    """

    def route(self, root: Path) -> list[str]:
        """Return the arguments of an activated route of DEADLINE_LANES lanes."""
        r = self.init_repo(root / "r", commits=("base",))
        plan = r / ".plan"
        for n in range(1, DEADLINE_LANES + 1):
            name = "p1-01-m" if n == 1 else f"p1-{n:02d}"
            _ = self.git("-C", r, "switch", "-q", "-c", name, "main")
            _ = self.write(r / f"f{n}", f"lane {n}\n")
            _ = self.git("-C", r, "add", f"f{n}")
            _ = self.git("-C", r, "commit", "-q", "-m", name)
            _ = self.write(
                plan / f"lanes/{name}-checkpoint.md", f"Final SHA: {self.rev(r)}\n"
            )
            _ = self.git("-C", r, "switch", "-q", "main")
        _ = self.git("-C", r, "merge", "-q", "--no-ff", "-m", "merge", "p1-01-m")
        argv = [str(plan), "--phase", "1", "--repo", str(r), "--main", "main"]
        act = self.py(RS, *argv, "--activate", session="d1", cwd=self.T, merge=True)
        self.ok("the route is activated", act.code == 0, act.out)
        return argv

    def test_deadline(self) -> None:
        """No deadline: a full state; 1.0 s: the error, no late spawn, no cache.

        A deadline already passed: the error before any spawn, no cache.
        """
        from dsp_route import report

        argv = self.route(self.T / "d")
        merged = support.Route.MK(argv[4], argv[0]).with_suffix(".merged")
        shim_env, log = self.git_shim(self.T / "shim", sleep=0.2)
        a = _args(argv)
        out: dict[float, str] = {}

        def run(seconds: float) -> None:
            try:
                with git_deadline(seconds):
                    s = report.collect(a)
            except GitDeadlineError:
                out[seconds] = "deadline"
                return
            lanes = s["lanes"] if s else []
            checked = sum(ln["git"] for ln in lanes)
            out[seconds] = f"{len(lanes)} lanes, {checked} checked"

        with mock.patch.dict(os.environ, {**self.env, **shim_env}, clear=True):
            full = report.collect(a, write_cache=True)
            lanes = full["lanes"] if full else []
            self.ok(
                f"control: {len(lanes)} lanes, all checked, the cache written",
                len(lanes) == DEADLINE_LANES
                and all(ln["git"] for ln in lanes)
                and merged.exists(),
                lanes,
            )
            merged.unlink()
            log.unlink()
            err: GitDeadlineError | None = None
            with spawns() as left:
                try:
                    with git_deadline(1.0):
                        _ = report.collect(a, write_cache=True)
                except GitDeadlineError as e:
                    err = e
            lines = log.read_text().splitlines() if log.exists() else []
            late = [t for t in left if t is None or t <= 0]
            self.ok(
                f"deadline 1.0 s: GitDeadlineError after {len(lines)} spawns, "
                f"{len(late)} late, no cache",
                err is not None
                and 0 < len(lines) <= DEADLINE_SPAWNS
                and not late
                and not merged.exists(),
                f"{err!r}\n{lines}\n{left}",
            )
            err = None
            with spawns() as left:
                try:
                    with git_deadline(0.0):
                        _ = report.collect(a, write_cache=True)
                except GitDeadlineError as e:
                    err = e
            self.ok(
                f"deadline passed: GitDeadlineError after {len(left)} spawns, no cache",
                err is not None and not left and not merged.exists(),
                f"{err!r}\n{left}",
            )
            threads = [threading.Thread(target=run, args=(s,)) for s in (1.0, 30.0)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        full_text = f"{DEADLINE_LANES} lanes, {DEADLINE_LANES} checked"
        self.ok(
            f"two threads at once: 1.0 s {out.get(1.0)}, 30 s {out.get(30.0)}",
            out == {1.0: "deadline", 30.0: full_text},
            out,
        )
