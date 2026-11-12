# SPDX-License-Identifier: MIT
"""The merged-result cache beside a route's marker: `<marker stem>.merged`.

A lane proven merged is kept with the main tip it was proven against, so a warm report
spends one ancestry check per distinct main instead of each lane's checks. An unmerged
lane, a rewritten main, a removed record and a malformed file are recomputed; the text
is the same warm and cold; only a report with a marker writes the file, and concurrent
writers never leave it torn.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple, cast

import support
from support import PY, RS, ev

KINDS = ("ancestor", "patch", "record")
LANES = 40  # WarmCallCount's 4 batches of 10
MAINS = 4  # one main tip per batch's report, then main moves once more
SMALL = 10  # ConcurrentWriters' one batch
ROUNDS = 5
WRITERS = 8
READ = '"tool_name":"Read"'

Entries = dict[str, dict[str, str | None]]


class Fixture(NamedTuple):
    """A built route: its repository, planning dir, cache file and merges by kind."""

    repo: Path
    plan: Path
    merged: Path
    kinds: dict[str, int]


def text(out: str) -> str:
    """A report's text without its first line, the header with its clock."""
    return out.partition("\n")[2]


def cached(path: Path) -> tuple[object, Entries]:
    """The cache file's `v` and lanes; (None, {}) when it is absent or not JSON."""
    try:
        data = cast("dict[str, object]", json.loads(path.read_text()))
    except (OSError, ValueError):
        return None, {}
    return data.get("v"), cast("Entries", data.get("lanes") or {})


def _settle(plan: Path) -> None:
    """Every planning file an hour old, so no `written Ns ago` flag differs."""
    for f in plan.rglob("*"):
        if f.is_file():
            support.Sandbox.touch(f, -3600)


def _lane(t: type[support.Sandbox], repo: Path, n: int, base: str) -> tuple[str, str]:
    """Lane `p1-NN-x` off base: a branch with one commit writing fNN; (name, SHA)."""
    name = f"p1-{n:02d}-x"
    _ = t.git("-C", repo, "switch", "-q", "-c", name, base)
    _ = t.write(repo / f"f{n:02d}", f"lane {n}\n")
    _ = t.git("-C", repo, "add", f"f{n:02d}")
    _ = t.git("-C", repo, "commit", "-q", "-m", name)
    sha = t.rev(repo)
    _ = t.git("-C", repo, "switch", "-q", "main")
    return name, sha


def _merge(
    t: type[support.Sandbox], plan: Path, kind: str, lane: tuple[int, str, str]
) -> None:
    """One lane merged into main by kind, its checkpoint written."""
    repo, (n, name, sha) = plan.parent, lane
    if kind == "ancestor":
        _ = t.git("-C", repo, "merge", "-q", "--no-ff", "-m", f"merge {name}", name)
    elif kind == "patch":
        _ = t.git("-C", repo, "cherry-pick", sha)
    else:
        # other content than the lane's, so its patch is not on main: only the record
        _ = t.write(repo / f"f{n:02d}", f"main {n}\n")
        _ = t.git("-C", repo, "add", f"f{n:02d}")
        _ = t.git("-C", repo, "commit", "-q", "-m", f"record {name}")
        _ = t.write(
            plan / "lanes/wave1-integration.md",
            f"Merged {name} {sha} → {t.rev(repo)}\n",
            "a",
        )
    _ = t.write(plan / f"lanes/{name}-checkpoint.md", f"Final SHA: {sha}\n")


def _worktree_lanes(t: type[support.Sandbox], root: Path, plan: Path, n: int) -> None:
    """Lane n+1 merged then moved past its SHA in its worktree; lane n+2 open in one."""
    repo = plan.parent
    for i, merged in ((n + 1, True), (n + 2, False)):
        name, sha = _lane(t, repo, i, t.rev(repo, "main"))
        if merged:
            _ = t.git("-C", repo, "merge", "-q", "--no-ff", "-m", f"merge {name}", name)
        wt = root / f"wt{i}"
        _ = t.git("-C", repo, "worktree", "add", "-q", wt, name)
        if merged:
            _ = t.write(wt / "more", "more\n")
            _ = t.git("-C", wt, "add", "more")
            _ = t.git("-C", wt, "commit", "-q", "-m", "more")
        _ = t.write(plan / f"lanes/{name}-checkpoint.md", f"Final SHA: {sha}\n")


def build(
    t: type[support.Sandbox],
    root: Path,
    batches: int,
    per_batch: int,
    *,
    worktrees: bool = False,
) -> Fixture:
    """A route of batches × per_batch lanes, merged each way, a CLI report per batch.

    Session c1 activates it before any lane exists, so that report writes no cache.
    """
    repo = t.init_repo(root / "r")
    plan = repo / ".plan"
    (plan / "lanes").mkdir(parents=True)
    _ = t.py(RS, plan, "--phase", "1", "--repo", repo, "--activate", session="c1")
    kinds: dict[str, int] = dict.fromkeys(KINDS, 0)
    n = 0
    for _batch in range(batches):
        base = t.rev(repo, "main")
        made = [(n + i, *_lane(t, repo, n + i, base)) for i in range(1, per_batch + 1)]
        n += per_batch
        for i, lane in enumerate(made):
            kind = KINDS[i % len(KINDS)]
            _merge(t, plan, kind, lane)
            kinds[kind] += 1
        _settle(plan)
        _ = t.py(RS, plan, "--phase", "1", "--repo", repo)
    if worktrees:
        _worktree_lanes(t, root, plan, n)
        kinds["ancestor"] += 1
        _settle(plan)
    common = Path(
        t.git("-C", repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    (marker,) = common.glob("dsp-route-*.json")
    return Fixture(repo, plan, marker.with_name(marker.stem + ".merged"), kinds)


def _restore(path: Path, saved: bytes | None) -> None:
    """Path back to saved bytes, or removed when it had none."""
    if saved is None:
        path.unlink(missing_ok=True)
    else:
        _ = path.write_bytes(saved)


class WarmCallCount(support.Sandbox):
    """AC-P1-2-5: a warm report spawns B + 4 git calls, one per distinct cached main."""

    def test_warm_call_count(self) -> None:
        """Cold, warm and no-checkpoint spawn counts of a 40-lane route."""
        f = build(type(self), self.T / "w", 4, 10)
        _ = self.git("-C", f.repo, "commit", "-q", "--allow-empty", "-m", "later")
        env, log = self.git_shim(self.T / "shim")

        def count() -> int:
            _ = self.write(log, "")
            _ = self.py(RS, f.plan, "--phase", "1", "--repo", f.repo, env=env)
            return len(log.read_text().splitlines())

        saved = f.merged.read_bytes() if f.merged.exists() else None
        self.rm(f.merged, f.merged.with_name("dsp-cherry.json"))
        cold = count()
        _restore(f.merged, saved)
        warm = count()
        saved = f.merged.read_bytes() if f.merged.exists() else None
        aside = f.plan / "aside"
        aside.mkdir()
        for c in (f.plan / "lanes").glob("*-checkpoint.md"):
            _ = c.rename(aside / c.name)
        b = count()
        for c in aside.glob("*-checkpoint.md"):
            _ = c.rename(f.plan / "lanes" / c.name)
        _restore(f.merged, saved)
        _, entries = cached(f.merged)
        mains = {e.get("main") for e in entries.values()}
        d = 2 + f.kinds["patch"] + 2 * f.kinds["record"]
        self.ok(
            f"cold {cold}, warm {warm}, B {b}, cold-B {cold - b} (derived {d}), "
            f"{len(mains)} distinct mains, {len(entries)} cached lanes",
            b > 0
            and f.merged.exists()
            and len(entries) == LANES
            and len(mains) == MAINS
            and warm == b + MAINS
            and cold == b + d,
        )


class Invalidation(support.Sandbox):
    """AC-P1-2-6: a removed record, a malformed file and a rewritten main recompute."""

    def test_invalidation(self) -> None:
        """Each change gives the cold text, and the cache follows it."""
        f = build(type(self), self.T / "i", 4, 10)

        def run() -> str:
            return text(self.py(RS, f.plan, "--phase", "1", "--repo", f.repo).out)

        def cold() -> str:
            self.rm(f.merged)
            return run()

        integration = f.plan / "lanes/wave1-integration.md"
        first, *rest = integration.read_text().splitlines(keepends=True)
        lane = first.split()[2]
        _ = self.write(integration, "".join(rest))
        self.touch(integration, -3600)
        warm = run()
        _, entries = cached(f.merged)
        self.ok(
            f"record removed: lane recomputed, {len(entries)} cached lanes",
            f.merged.exists() and lane not in entries and warm == cold(),
            warm,
        )
        want = cold()
        for bad in ("{", '{"v": 2, "lanes": {}}'):
            _ = self.write(f.merged, bad)
            got = run()
            v, entries = cached(f.merged)
            self.ok(
                f"cache {bad!r}: read as empty, rewritten with {len(entries)} lanes",
                got == want and v == 1 and len(entries) == LANES - 1,
                got,
            )
        root = self.git("-C", f.repo, "rev-list", "--max-parents=0", "main")
        _ = self.git("-C", f.repo, "reset", "-q", "--hard", root)
        warm = run()
        v, entries = cached(f.merged)
        self.ok(
            f"main rewritten: {len(entries)} cached lanes",
            v == 1 and not entries and warm == cold(),
            warm,
        )


class WarmEqualsCold(support.Sandbox):
    """AC-P1-2-7 (Lane 0 half): the CLI and the hook print the same warm and cold."""

    def test_warm_equals_cold(self) -> None:
        """Default, --all and the hook's `.last`, each cold then warm."""
        f = build(type(self), self.T / "e", 2, 5, worktrees=True)
        registry = self.HOME / ".claude/dsp-routes"

        def pair(*extra: str) -> bool:
            args = (RS, f.plan, "--phase", "1", "--repo", f.repo, *extra)
            self.rm(f.merged)
            c = text(self.py(*args).out)
            return bool(c) and text(self.py(*args).out) == c

        def hook() -> bytes:
            self.rm(*registry.glob("*.checked"), *f.merged.parent.glob("*.last"))
            _ = self.hook_out(ev("PostToolUse", "c1", READ))
            return b"".join(
                p.read_bytes() for p in sorted(f.merged.parent.glob("*.last"))
            )

        default, every = pair(), pair("--all")
        self.rm(f.merged)
        hc = hook()
        hw = hook()
        same = bool(hc) and hc == hw
        self.ok(
            f"3 comparisons, warm == cold: default {default}, --all {every}, "
            f"hook {same}",
            f.merged.exists() and default and every and same,
        )


class OnlyReportsWrite(support.Sandbox):
    """AC-P1-2-8 (rule half): only a route's report writes the cache; the stale file.

    The stale file is `dsp-cherry.json`, an older version's cache of unmerged answers.
    """

    def test_only_reports_write(self) -> None:
        """No marker, no file; the CLI and the hook write it, dsp-cherry.json goes."""
        f = build(type(self), self.T / "o", 1, 4)
        self.rm(f.merged)
        gitdir = f.merged.parent
        other = f.repo / ".plan2"
        _ = shutil.copytree(f.plan / "lanes", other / "lanes")
        _ = self.py(RS, other, "--phase", "1", "--repo", f.repo)
        self.ok("no marker: no cache file", not list(gitdir.glob("*.merged")))
        stale = self.write(gitdir / "dsp-cherry.json", "{}")
        _ = self.py(RS, f.plan, "--phase", "1", "--repo", f.repo)
        self.ok(
            "the CLI report writes the cache and drops dsp-cherry.json",
            f.merged.exists() and not stale.exists(),
        )
        self.rm(f.merged, *(self.HOME / ".claude/dsp-routes").glob("*.checked"))
        _ = self.hook_out(ev("PostToolUse", "c1", READ))
        self.ok("the hook's report writes the cache", f.merged.exists())
        helped = self.py(RS, "--help")
        self.ok(
            "--help names no dsp-cherry.json",
            helped.code == 0 and helped.out and "dsp-cherry" not in helped.out,
            helped.out,
        )


class ConcurrentWriters(support.Sandbox):
    """AC-P1-2-9: 8 reports at once never leave a torn or partial cache."""

    def test_concurrent_writers(self) -> None:
        """5 rounds of 8 CLI reports, the file polled while they run."""
        f = build(type(self), self.T / "c", 1, SMALL)
        argv = [PY, str(RS), str(f.plan), "--phase", "1", "--repo", str(f.repo)]
        torn = rounds = 0
        bad: list[str] = []
        for r in range(ROUNDS):
            self.rm(f.merged)
            procs = [
                subprocess.Popen(argv, env=self.env, stdout=subprocess.DEVNULL)
                for _ in range(WRITERS)
            ]
            while any(p.poll() is None for p in procs):
                try:
                    _ = cast("object", json.loads(f.merged.read_text()))
                except FileNotFoundError:
                    pass
                except ValueError:
                    torn += 1
                time.sleep(0.002)
            v, entries = cached(f.merged)
            tmps = list(f.merged.parent.glob("*.tmp"))
            if v != 1 or len(entries) != SMALL or tmps:
                bad.append(f"round {r}: v {v}, {len(entries)} lanes, tmp {tmps}")
            rounds += 1
        self.ok(
            f"{rounds} rounds, {torn} torn reads",
            rounds == ROUNDS and torn == 0 and not bad,
            bad,
        )
