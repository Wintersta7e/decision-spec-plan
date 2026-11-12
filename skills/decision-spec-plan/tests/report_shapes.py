# SPDX-License-Identifier: MIT
"""Seven route shapes the report's text is pinned over, and the helpers that read them.

Each shape is one repository with its planning dir and a route activated on it. Every
commit carries the same identity and date, so the SHAs are literal, and every planning
file is three days old, so every age prints `3d`. Not a test module: the classes that
build on `Shapes` live in the test files.
"""

import datetime as dt
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from typing_extensions import override

import support
from support import RS

DATE = "2026-01-01T00:00:00+0000"
GOLDEN_DIR = support.TESTS / "golden"
# the two masks, and nothing else: the header holds the sandbox path and the clock, a
# fresh file's flag the seconds the run took
HEADER = re.compile(r"route state · .*")
WRITTEN = re.compile(r"written \d+s ago")
AGED_S = 3 * 86400
FRESH_FILE_S = 61


class Shape(TypedDict):
    """One shape: CLI arguments (no `--all`), session, planning dir, marker repo."""

    argv: list[str]
    session: str
    plan: str
    repo: str


# {"<n>-<slug>": its shape}, filled by Shapes.setUpClass
GOLDEN: dict[str, Shape] = {}


def mask(text: str) -> str:
    """Return a report's text with its header line and fresh-file seconds masked."""
    first, nl, rest = text.partition("\n")
    if HEADER.fullmatch(first):
        first = "route state · <masked>"
    return WRITTEN.sub("written <n>s ago", first + nl + rest)


def last_file(shape: Shape) -> Path:
    """Return the hook's per-session `.last` file of a shape's route."""
    marker = support.Route.MK(shape["repo"], shape["plan"])
    return marker.with_name(f"{marker.stem}.{shape['session']}.last")


def merged_file(shape: Shape) -> Path:
    """Return the merged-result cache file of a shape's route."""
    return support.Route.MK(shape["repo"], shape["plan"]).with_suffix(".merged")


def _index(b0: str, rows: str = "") -> str:
    """Return a decision index naming main at b0 as its base, plus rows."""
    return f"# Phase 1\n> **Base**: `main` at `{b0}`\n\n{rows}"


Builder = Callable[[type["Shapes"], Path], tuple[list[str], list[str]]]


class Shapes(support.Sandbox):
    """The seven shapes under T/g<n>, each activated by session g<n>."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Build and activate every shape, then age every planning file three days."""
        super().setUpClass()
        cls.env["GIT_AUTHOR_DATE"] = cls.env["GIT_COMMITTER_DATE"] = DATE
        GOLDEN.clear()
        builders: dict[str, Builder] = {
            "1-empty": _empty,
            "2-merged": _merged,
            "3-open": _open,
            "4-gates": _gates,
            "5-drift": _drift,
            "6-rung-s": _rung_s,
            "7-odd": _odd,
        }
        for key, build in builders.items():
            n = key.split("-", 1)[0]
            root = cls.T / f"g{n}"
            argv, extra = build(cls, root)
            r = cls.py(
                RS, *argv, *extra, "--activate", session=f"g{n}", cwd=cls.T, merge=True
            )
            if r.code != 0:
                msg = f"shape {key}: --activate failed: {r.out}"
                raise AssertionError(msg)
            GOLDEN[key] = {
                "argv": argv,
                "session": f"g{n}",
                "plan": str(root / "r/.plan"),
                "repo": str(root / "r"),
            }
        aged = dt.datetime.now(dt.UTC).timestamp() - AGED_S
        for shape in GOLDEN.values():
            for d, _, files in os.walk(shape["plan"]):
                for f in files:
                    os.utime(Path(d) / f, (aged, aged))
        cls.freshen()

    @classmethod
    def freshen(cls) -> None:
        """Set shape 7's fresh spec file FRESH_FILE_S old: `1m`, and still flagged."""
        cls.touch(Path(GOLDEN["7-odd"]["plan"]) / "spec/3-c.md", -FRESH_FILE_S)

    @classmethod
    def unthrottle(cls) -> None:
        """Remove the hook's throttle stamps, so its next run reports again."""
        for f in (cls.HOME / ".claude/dsp-routes").glob("*.checked"):
            f.unlink()

    @classmethod
    def base(cls, root: Path, index_rows: str = "") -> tuple[Path, Path, str]:
        """Return (repo, planning dir, base SHA) of a new repository under root."""
        r = cls.init_repo(root / "r", commits=("base",))
        plan = r / ".plan"
        b0 = cls.rev(r)
        _ = cls.write(plan / "decisions/phase1/00-index.md", _index(b0, index_rows))
        return r, plan, b0

    @classmethod
    def lane(cls, r: Path, name: str, n: int) -> str:
        """Return the SHA of a lane branch off main with one commit writing f<n>."""
        _ = cls.git("-C", r, "switch", "-q", "-c", name, "main")
        _ = cls.write(r / f"f{n}", f"lane {n}\n")
        _ = cls.git("-C", r, "add", f"f{n}")
        _ = cls.git("-C", r, "commit", "-q", "-m", name)
        sha = cls.rev(r)
        _ = cls.git("-C", r, "switch", "-q", "main")
        return sha

    @classmethod
    def commit(cls, repo: Path, name: str, text: str, message: str) -> str:
        """Return the SHA of a commit in repo writing text to name."""
        _ = cls.write(repo / name, text)
        _ = cls.git("-C", repo, "add", name)
        _ = cls.git("-C", repo, "commit", "-q", "-m", message)
        return cls.rev(repo)

    @classmethod
    def plans(cls, plan: Path, stems: list[str], table: str = "") -> None:
        """Write a plan and a valid manifest per stem, and the plan index's table."""
        for s in stems:
            _ = cls.write(plan / f"plans/{s}.md", f"# {s}\n\n- [ ] Task 1\n")
            _ = cls.write(plan / f"manifests/{s}.json", f'{{"plan": "{s}"}}\n')
        if table:
            _ = cls.write(plan / "plans/p1-00-index.md", f"# Phase 1 plans\n\n{table}")


def _repo_argv(r: Path, plan: Path, *extra: str) -> list[str]:
    """Return the CLI arguments of a route on r's phase 1, plus extra."""
    return [str(plan), "--phase", "1", "--repo", str(r), *extra]


def _empty(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """Rung M, one decision: no spec, plans or lanes yet."""
    r, plan, _ = cls.base(root, "| D1 | a |\n")
    dec = plan / "decisions/phase1"
    _ = cls.write(dec / "D1-a.md", "# D1 a\n\n> **Read 00-arbiter.md first.**\n\nA.\n")
    _ = cls.write(dec / "00-arbiter.md", "# Arbiter\n\nD1 settled.\n")
    return _repo_argv(r, plan, "--sections", "1-"), ["--rung", "M"]


def _merged(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """Three lanes merged by ancestry, patch and record; a fourth plan unstarted."""
    r, plan, _ = cls.base(root)
    lanes = plan / "lanes"
    shas = {n: cls.lane(r, f"p1-0{n}-a", n) for n in (1, 2, 3)}
    _ = cls.git("-C", r, "merge", "-q", "--no-ff", "-m", "merge p1-01-a", "p1-01-a")
    _ = cls.git("-C", r, "cherry-pick", shas[2])
    # other content than the lane's, so its patch is not on main: only the record
    sq = cls.commit(r, "f3", "main 3\n", "squash p1-03-a")
    _ = cls.write(
        lanes / "wave1-integration.md",
        f"# Wave 1\n\nMerged p1-03-a {shas[3]} → {sq[:9]}\n",
    )
    for n, sha in shas.items():
        _ = cls.write(
            lanes / f"p1-0{n}-a-checkpoint.md", f"- [x] Task 1\n\nFinal SHA: {sha}\n"
        )
    cls.plans(
        plan,
        ["p1-01-a", "p1-02-a", "p1-03-a", "p1-04-x"],
        "| Plan | Wave | Depends on |\n|---|---|---|\n"
        "| p1-01-a | 1 | — |\n| p1-02-a | 1 | — |\n"
        "| p1-03-a | 2 | p1-01 |\n| p1-04-x | 3 | all |\n",
    )
    return _repo_argv(r, plan), []


def _open(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """Three open lanes: uncommitted work, a branch past its SHA, an odd checkpoint."""
    r, plan, _ = cls.base(root)
    lanes = plan / "lanes"
    s1 = cls.lane(r, "p1-01-a", 1)
    s2 = cls.lane(r, "p1-02-a", 2)
    s3 = cls.lane(r, "p1-03-a", 3)
    _ = cls.git("-C", r, "worktree", "add", "-q", root / "wt-01", "p1-01-a")
    _ = cls.write(root / "wt-01/f1", "changed\n")
    _ = cls.git("-C", r, "worktree", "add", "-q", root / "wt-02", "p1-02-a")
    _ = cls.commit(root / "wt-02", "g2", "more\n", "p1-02-a more")
    _ = cls.write(lanes / "p1-01-a-checkpoint.md", f"Final SHA: {s1}\n")
    _ = cls.write(lanes / "p1-02-a-checkpoint.md", f"Final SHA: {s2}\n")
    # no `Final SHA:` line, 40 lines, and a rulings file past 12 KB
    _ = cls.write(
        lanes / "p1-03-a-checkpoint.md",
        f"lane p1-03-a at {s3}\n" + "".join(f"- [x] step {i}\n" for i in range(39)),
    )
    _ = cls.write(lanes / "p1-03-a-rulings.md", "x" * 13_000)
    _ = cls.write(
        plan / "route-budget.json",
        '{"budgets": [{"label": "phase 1", "estimate": 4.0, "phase": "1", '
        '"at": "2026-01-02T03:04:05", "session": "g3", "groups": 2}]}\n',
    )
    return _repo_argv(r, plan), []


def _gates(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """Four open lanes whose gate logs are red, green, unfinished and dirty."""
    r, plan, _ = cls.base(root)
    lanes = plan / "lanes"
    logs = {
        1: {"gate": "dirty=0\nrunning\nexit=1\n"},
        2: {
            "gate": "dirty=0\nok\nexit=0\n",
            "gate-pg": "dirty=0\nharness=pg\nexit=1\n",
        },
        3: {"gate": "dirty=0\nrunning\n"},
        4: {"gate": "dirty=2\nok\nexit=0\n"},
    }
    for n, kinds in logs.items():
        name = f"p1-0{n}-a"
        sha = cls.lane(r, name, n)
        _ = cls.write(lanes / f"{name}-checkpoint.md", f"Final SHA: {sha}\n")
        for kind, body in kinds.items():
            _ = cls.write(lanes / f"{name}-{kind}.log", f"sha={sha} {body}")
    return _repo_argv(r, plan), []


def _drift(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """The base moved here and upstream; assumed refs moved, merged and gone."""
    origin = cls.init_repo(root / "origin", commits=("base",))
    r = root / "r"
    _ = cls.git("clone", "-q", origin, r)
    b0 = cls.rev(r)
    _ = cls.git("-C", r, "switch", "-q", "-c", "feat")
    f0 = cls.commit(r, "feat", "feat\n", "feat")
    _ = cls.git("-C", r, "switch", "-q", "-c", "api", "main")
    a0 = cls.commit(r, "api", "api\n", "api")
    _ = cls.commit(r, "api", "api 2\n", "api endpoint")
    _ = cls.git("-C", r, "switch", "-q", "main")
    for ref in ("feat", "api"):
        _ = cls.git("-C", r, "merge", "-q", "--no-ff", "-m", f"merge {ref}", ref)
    _ = cls.git("-C", origin, "commit", "-q", "--allow-empty", "-m", "later")
    _ = cls.git("-C", r, "fetch", "-q")
    plan = r / ".plan"
    _ = cls.write(
        plan / "decisions/phase1/00-index.md",
        _index(b0) + f"> **Assumes**: `api` at `{a0}` — its endpoints\n"
        f"> **Assumes**: `feat` at `{f0}`\n"
        f"> **Assumes**: `gone` at `{b0}`\n",
    )
    return _repo_argv(r, plan), []


def _rung_s(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """Rung S without --repo: the index rows are the decisions; one lane, unchecked."""
    r, plan, _ = cls.base(root, "| D1 | a |\n| D2 | b |\n")
    cls.plans(plan, ["p1-01-a"])
    _ = cls.write(plan / "lanes/p1-01-a-checkpoint.md", f"Final SHA: {cls.rev(r)}\n")
    return [str(plan), "--phase", "1"], ["--rung", "S"]


def _odd(cls: type[Shapes], root: Path) -> tuple[list[str], list[str]]:
    """A missing --main, a pending and a fresh section, long handoff, bad manifests."""
    r, plan, _ = cls.base(root)
    _ = cls.write(plan / "spec/1-a.md", "# 1 a\n\nText.\n")
    _ = cls.write(plan / "spec/3-c.md", "# 3 c\n\nStill being written.\n")
    _ = cls.write(plan / "HANDOFF.md", "# Handoff\n" + "x" * (41_000 - 10))
    _ = cls.write(plan / "plans/p1-01-a.md", "# p1-01-a\n")
    _ = cls.write(plan / "plans/p1-02-a.md", "# p1-02-a\n")
    _ = cls.write(plan / "manifests/p1-02-a.json", "{not json\n")
    return _repo_argv(r, plan, "--main", "nope", "--sections", "1-3"), []
