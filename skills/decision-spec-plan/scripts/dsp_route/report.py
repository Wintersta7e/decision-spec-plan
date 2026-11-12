# SPDX-License-Identifier: MIT
"""The route report: one screen of a round's state (route_state.py's docstring).

Printed by the script and injected into the lead's context by the hook.
"""

import contextlib
import dataclasses
import json
import os
import pathlib
import re
import time
from collections.abc import Iterable, Mapping
from typing import TypedDict

from .common import (
    PLAN_ID,
    RouteArgs,
    StrPath,
    ago,
    as_dict,
    default_branch,
    git,
    load_json,
    marker_path,
    parse_json,
)

FRESH_S = 120
HANDOFF_MAX = 40_000
# the route's handoff (bootstrap.md), or the project's session handoff where it keeps
# one
HANDOFFS = ("HANDOFF.md", "SESSION-HANDOFF.md")
CHECKPOINT_MAX = 35
RULINGS_MAX = 12_000
# the pending names a line lists before it counts the rest
PENDING_MAX = 8
# the head of a gate log, where its `sha=` and `harness=` lines are read
GATE_HEAD = 20
# The merged-result cache, `<marker stem>.merged` beside the route's marker: each lane
# commit proven merged, with the main tip it was proven against. A cherry walks main's
# trees since the lane's base, 4-5 s each on a slow drive; a lane once merged stays
# merged while that tip stays an ancestor of main. Not `dsp-route*.json`, which
# push_guard.py reads as route markers.
MERGED_V = 1
FULL_SHA = re.compile(r"[0-9a-f]{40}")
# `as` and `record`: the integrator's main SHA and record file, for a `record` merge
MergedLane = TypedDict(
    "MergedLane", {"main": str, "how": str, "as": str | None, "record": str | None}
)
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
FINAL_SHA = re.compile(
    r"^\W*Final SHA:\W*([0-9a-f]{7,40})\b", re.MULTILINE | re.IGNORECASE
)
MERGED = re.compile(
    r"^\W*Merged\s+\W*([\w.-]+?)\W+([0-9a-f]{7,40})\W+(?:→|->)\W*([0-9a-f]{7,40})\b",
    re.MULTILINE,
)
# The decision index's header: `> **Base**: `main` at `<sha>`` and one `> **Assumes**:
# `<ref>` at `<sha>`` per unmerged branch the round builds on (templates.md §1).
BASE = re.compile(
    r"^>?\s*\*\*(Base|Assumes)\*\*:\s*`([^`]+)`\s+at\s+`([0-9a-f]{7,40})`", re.MULTILINE
)


# (log, sha, dirty, exit code or None, CI harness or None) of a gate log
GateLog = tuple[pathlib.Path, str, str, str | None, str | None]
# (path, HEAD) of a branch's worktree
Worktree = tuple[str | None, str | None]

# The report's data object (`collect`); bumped when a key changes meaning or type.
VERSION = 1
# the enums of its derived facts, in display order; other modules import them
LANE_STATES = ("queued", "running", "gating", "ready", "red", "merged")
LANE_BASES = ("planned", "no-sha", "unchecked", "unknown", "open", "merged")
GATE_STATES = ("green", "red", "dirty", "no-exit", "none")
FLAG_KINDS = (
    "main-missing",
    "handoff-large",
    "file",
    "base-drift",
    "no-manifest",
    "manifest-invalid",
    "no-final-sha",
    "sha-unknown",
    "lane-moved-past-merge",
    "checkpoint-long",
    "rulings-large",
    "gate-no-exit",
    "gate-red",
)
# an open lane's state by its gate
BY_GATE = {
    "red": "red",
    "no-exit": "gating",
    "green": "ready",
    "dirty": "running",
    "none": "running",
}
# the decision round's files the `decisions` line says are there or not
FIXED = ("00-dispatch", "00-framing-review", "00-seams", "00-arbiter", "spec-returns")


class FileFact(TypedDict):
    """One artefact read: its path as the text prints it, size, age and last line.

    `kind` is decision, spec, reconcile, plan, checkpoint or wave; `problems` are
    already filtered by `fresh`; `mtime` is the stat that gave `age_s`.
    """

    path: str
    kind: str
    bytes: int
    age_s: float
    mtime: float
    last_line: str
    problems: list[str]


class HandoffFact(TypedDict):
    """A handoff that exists, and its size."""

    name: str
    bytes: int


class DecisionFacts(TypedDict):
    """The phase's decision index and D files: {id: path}, ids as strings."""

    index: bool
    index_ids: list[str]
    files: dict[str, str]
    pending: list[str]
    markers: int
    headers: int
    fixed: dict[str, bool]


class SpecFacts(TypedDict):
    """The --sections range (last None: open-ended) and the sections present."""

    first: int
    last: int | None
    sections: list[int]


class ManifestFact(TypedDict):
    """A plan's manifest file and whether it parses: ok, missing or invalid."""

    name: str
    state: str


class PlanFacts(TypedDict):
    """The plan index's ids, the plan files by id, and their manifests."""

    index_ids: list[str]
    files: dict[str, str]
    pending: list[str]
    manifests: dict[str, ManifestFact]


class RulingsFact(TypedDict):
    """A lane's rulings file and its size."""

    name: str
    bytes: int


class CheckpointFact(TypedDict):
    """A lane checkpoint: id (the stem less `-checkpoint`), plan id, SHA as written."""

    id: str
    plan: str
    path: str
    sha: str | None
    final_sha_line: bool
    lines: int
    rulings: RulingsFact | None


class GateLogFact(TypedDict):
    """What push_guard.py reads of a gate log; dirty and exit None when absent."""

    log: str
    sha: str
    dirty: int | None
    exit: int | None
    harness: str | None


class RecordFact(TypedDict):
    """The integrator's record of a lane it rebased or squashed."""

    lane_sha: str
    main_sha: str
    file: str


class WorktreeFact(TypedDict):
    """A lane branch's worktree: its path and HEAD."""

    path: str | None
    head: str | None


class LaneCheck(TypedDict):
    """An open lane's commits since main, their trailers, its uncommitted lines.

    uncommitted is None when its worktree is not at the lane's commit.
    """

    commits: int | None
    trailers: dict[str, int]
    uncommitted: int | None


class GitLane(TypedDict):
    """What git says of a lane's checkpoint SHA (`sha`): commit None, not in the repo.

    branch_ahead is None without a worktree or when it sits at the commit.
    """

    sha: str
    commit: str | None
    merged_how: str | None
    merged_as: str | None
    record: str | None
    worktree: WorktreeFact | None
    branch_ahead: int | None
    check: LaneCheck | None


class GitFacts(TypedDict):
    """The git half of the object; main_missing is the --main given that is not."""

    as_of: float
    repo: str
    main: str
    main_missing: str | None
    main_sha: str | None
    lane_worktrees: int
    drift: list[str]
    pushed: bool | None
    lanes: dict[str, GitLane]


class Lane(TypedDict):
    """A lane as derived: its state, basis and gate (LANE_STATES, ...)."""

    id: str
    plan: str
    state: str
    basis: str
    gate: str | None
    gate_exit: int | None
    gate_dirty: int | None
    git: bool


class Flag(TypedDict):
    """A flag: its kind, subject, and its line as the text prints it."""

    kind: str
    subject: str
    line: str


class Stage(TypedDict):
    """A route stage and its state."""

    name: str
    state: str


class State(TypedDict):
    """The route report as data: file facts, git facts, and what derive() computes.

    JSON-native: string keys, lists, and every list in production order.
    """

    version: int
    planning_dir: str
    phase: str
    generated_at: float
    rung: str | None
    extra: list[str]
    handoffs: list[HandoffFact]
    files: list[FileFact]
    decisions: DecisionFacts
    harvest_files: list[str]
    spec: SpecFacts | None
    reconcile: list[str]
    plans: PlanFacts
    lane_files: bool
    checkpoints: list[CheckpointFact]
    gate_logs: list[GateLogFact]
    records: dict[str, RecordFact]
    integration_files: list[str]
    git: GitFacts | None
    lanes: list[Lane]
    flags: list[Flag]
    stages: list[Stage]


def merged_path(route: pathlib.Path | None) -> pathlib.Path | None:
    """Return the route's merged-result cache file, None without a marker file."""
    if route is None or not route.exists():
        return None
    return route.with_name(route.stem + ".merged")


def _merged_lane(value: object) -> MergedLane | None:
    """Return one cache entry as read, None when it is malformed."""
    e = as_dict(value) or {}
    main, how, as_, record = e.get("main"), e.get("how"), e.get("as"), e.get("record")
    if not (isinstance(main, str) and FULL_SHA.fullmatch(main)):
        return None
    if how == "record" and isinstance(as_, str) and isinstance(record, str):
        return {"main": main, "how": "record", "as": as_, "record": record}
    if how in ("ancestor", "patch") and as_ is None and record is None:
        return {"main": main, "how": str(how), "as": None, "record": None}
    return None


def read_merged(path: pathlib.Path) -> tuple[dict[str, MergedLane], str | None]:
    """Return the cache's entries and its text: ({}, "") absent, ({}, None) unreadable.

    An unparsable file, another version, or one malformed entry reads as empty whole;
    the next report rewrites it.
    """
    try:
        raw = path.read_text(errors="replace")
    except FileNotFoundError:
        return {}, ""
    except OSError:
        return {}, None
    try:
        data = as_dict(parse_json(raw)) or {}
    except ValueError:
        return {}, raw
    lanes = as_dict(data.get("lanes"))
    if data.get("v") != MERGED_V or lanes is None:
        return {}, raw
    entries = {
        k: e
        for k, v in lanes.items()
        if FULL_SHA.fullmatch(k) and (e := _merged_lane(v))
    }
    return (entries if len(entries) == len(lanes) else {}), raw


def write_merged(
    path: pathlib.Path, lanes: Mapping[str, MergedLane], raw: str | None
) -> None:
    """Replace the cache whole with lanes, unless it was unreadable or is unchanged.

    Through a tmp file and a rename, so a concurrent report never reads half of it. A
    failed write never fails the report: the next one recomputes what it lacks.
    """
    if raw is None:
        return
    text = json.dumps({"v": MERGED_V, "lanes": lanes}, indent=1, sort_keys=True) + "\n"
    if text == raw:
        return
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        _ = tmp.write_text(text)
        _ = tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)


def describe(path: pathlib.Path) -> tuple[list[str], int, float, str, float]:
    """Return (problems, size, age, last line, mtime) of one artefact, from one stat."""
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    mtime = path.stat().st_mtime
    age = time.time() - mtime
    problems: list[str] = []
    if not lines:
        problems.append("empty")
    if sum(1 for ln in text.split("\n") if ln.lstrip().startswith("```")) % 2:
        problems.append("unpaired ``` fence")
    if age < FRESH_S:
        problems.append(f"written {int(age)}s ago — still being written?")
    return (
        problems,
        len(text.encode()),
        age,
        (lines[-1].strip() if lines else ""),
        mtime,
    )


def pending(names: Iterable[str]) -> str:
    """Return the first PENDING_MAX names, and how many more there are."""
    names = list(names)
    more = len(names) - PENDING_MAX
    return " ".join(names[:PENDING_MAX]) + (f" +{more}" if more > 0 else "")


def lane_checkpoints(lanes: pathlib.Path, phase: str) -> list[pathlib.Path]:
    """Return every lane checkpoint but another phase's.

    Both `p<P>-<id>-…` and lanes named any other way.
    """
    return [
        c
        for c in sorted(lanes.glob("*-checkpoint.md"))
        if not ((m := re.match(r"p(\d+)-", c.name)) and m[1] != phase)
    ]


def _gate_log(log: pathlib.Path) -> GateLog:
    """Return what push_guard.py reads of one gate log."""
    first, last, harness = "", None, None
    with log.open(errors="replace", newline="\n") as f:
        for n, ln in enumerate(f):
            if n < GATE_HEAD and not first and ln.startswith("sha="):
                first = ln
            if n < GATE_HEAD and not harness and ln.startswith("harness="):
                harness = ln[len("harness=") :].strip()
            if m := re.fullmatch(r"exit=(\d+)\s*", ln):
                last = m[1]
    head = re.fullmatch(r"sha=([0-9a-f]{40}) dirty=(\d+)\s*", first)
    sha, dirty = (head[1], head[2]) if head else ("", "")
    return log, sha, dirty, last, harness


def gate_logs(lanes: pathlib.Path, phase: str) -> list[GateLog]:
    """Return the lines push_guard.py reads of each gate log but another phase's.

    Each as (log, the commit and dirty count of its first `sha=` line within 20 lines,
    its last `exit=` or None, the CI harness its first 20 lines name or None). A harness
    log ran only that suite: no full gate.
    """
    # Line by line: a whole log read at once raised ENOMEM on a large one. Lines end at
    # `\n` only, as push_guard.py reads them: a progress bar's `\r` before `exit=` is no
    # line break.
    return [
        _gate_log(log)
        for log in sorted(lanes.glob("*-gate*.log"))
        if not ((m := re.match(r"p(\d+)-", log.name)) and m[1] != phase)
    ]


def _base_rows(text: str) -> list[tuple[str, str, str]]:
    """Return (kind, ref, sha) of each `Base` and `Assumes` line of a decision index."""
    return [(m[1], m[2], m[3]) for m in BASE.finditer(text)]


def _base_moved(repo: StrPath, ref: str, sha: str, head: str) -> list[str]:
    """Return how far the recorded base and its upstream moved past its SHA."""
    # templates.md records the local main branch, which a fetch never moves: its
    # upstream does
    rc, up = git(
        repo,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{ref}@{{upstream}}^{{commit}}",
    )
    tips = [("base moved", ref, head)]
    if rc == 0 and up != head:
        tips.append(("base moved upstream", f"{ref}@{{upstream}}", up))
    out: list[str] = []
    for label, name, tip in tips:
        if not tip.startswith(sha):
            rc, n = git(repo, "rev-list", "--count", f"{sha}..{tip}")
            out.append(
                f"{label:<34} {name} {n if rc == 0 else '?'} commits past {sha[:9]}"
            )
    return out


def base_drift(repo: StrPath, text: str) -> list[str]:
    """Return what moved under the round since its decision index recorded it (F91).

    The base and the unmerged refs it assumes, as of the last fetch: a round planned on
    them is planned on a past.
    """
    rows = _base_rows(text)
    base_ref = next((ref for kind, ref, _ in rows if kind == "Base"), None)
    out: list[str] = []
    for kind, ref, sha in rows:
        rc, head = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if rc:
            out.append(
                f"{kind.lower() + ' ref gone':<34} {ref} (recorded at {sha[:9]})"
            )
            continue
        if kind == "Base":
            out += _base_moved(repo, ref, sha, head)
            continue
        landed = base_ref and (
            git(repo, "merge-base", "--is-ancestor", head, base_ref)[0] == 0
        )
        if head.startswith(sha):
            if landed:
                out.append(
                    f"{'assumed ref merged':<34} {ref} {sha[:9]} into {base_ref}"
                )
            continue
        out.append(
            f"{'assumed ref moved':<34} {ref} {sha[:9]} → {head[:9]}"
            + (f", merged into {base_ref}" if landed else "")
        )
    return out


def moved_under(repo: StrPath, text: str) -> list[str]:
    """Return what moved under the round that the route did not move itself (F91).

    As of the last fetch: commits the base's upstream has that the local base lacks —
    the route's own merges move only the local one — a base with no upstream past its
    SHA, an assumed ref moved, merged or gone.
    """
    drift = base_drift(repo, text)
    base = next((ref for kind, ref, _ in _base_rows(text) if kind == "Base"), None)
    rc, n = git(repo, "rev-list", "--count", f"{base}..{base}@{{upstream}}")
    if not base or rc:
        return drift
    out = [ln for ln in drift if not ln.startswith("base moved")]
    if int(n):
        out.append(
            f"{'base behind upstream':<34} {base} lacks {n} commits of its upstream"
        )
    return out


def round_moved(planning_dir: StrPath, route: RouteArgs) -> list[str]:
    """Return moved_under of the phase's index, [] with no repository or index."""
    index = (
        pathlib.Path(planning_dir) / "decisions" / f"phase{route.phase}" / "00-index.md"
    )
    if not route.repo or not index.exists():
        return []
    return moved_under(route.repo, index.read_text(errors="replace"))


def _main_branch(a: RouteArgs, repo: str) -> tuple[str, str | None, str | None]:
    """Return the main branch lanes are checked against, its tip, the --main missing.

    On a missing --main the default branch stands in, with no tip.
    """
    main = a.main or default_branch(repo)
    rc, tip = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{main}")
    if rc:
        return default_branch(repo), None, main
    return main, tip, None


def _manifest(
    base: pathlib.Path, p: str, plan_id: str, plan: pathlib.Path
) -> pathlib.Path:
    """Return a plan's manifest: by plan id in the layout, its stem in prompts.md §4."""
    m = base / "manifests" / (plan.stem + ".json")
    if not m.exists() and (base / "manifests" / f"p{p}-{plan_id}.json").exists():
        m = base / "manifests" / f"p{p}-{plan_id}.json"
    return m


def _worktrees(repo: StrPath) -> dict[str, Worktree]:
    """Return {branch: (path, HEAD)} of the repository's worktrees."""
    worktrees: dict[str, Worktree] = {}
    _, wt = git(repo, "worktree", "list", "--porcelain")
    path = head = None
    for line in [*wt.splitlines(), ""]:
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("HEAD "):
            head = line[5:]
        elif line.startswith("branch "):
            worktrees[line.removeprefix("branch refs/heads/")] = (path, head)
    return worktrees


def _merge_records(lanes: pathlib.Path) -> dict[str, tuple[str, str, str]]:
    """Return the integrator's record of each lane it rebased or squashed.

    `Merged <plan-id> <lane> → <main>`, as {plan id: (lane sha, main sha, file)}.
    """
    records: dict[str, tuple[str, str, str]] = {}
    for w in sorted(lanes.glob("wave*-integration*.md")):
        for m in MERGED.finditer(w.read_text(errors="replace")):
            records[m[1]] = (m[2], m[3], w.name)
    return records


@dataclasses.dataclass
class _Cache:
    """One report's merged-result cache: what it read, what it keeps, its checks.

    path is None when the report keeps no cache: no --repo, no marker file, no main
    tip, or a file it cannot read.
    """

    path: pathlib.Path | None
    main: str
    tip: str
    known: dict[str, MergedLane]
    raw: str | None
    # the entries of this report's merged lanes: the next file
    keep: dict[str, MergedLane] = dataclasses.field(default_factory=dict)
    # {cached main: whether it is an ancestor of the tip}, one check each per report
    ancestry: dict[str, bool] = dataclasses.field(default_factory=dict)

    def hit(
        self,
        repo: str,
        full: str,
        plan_id: str,
        records: Mapping[str, tuple[str, str, str]],
    ) -> MergedLane | None:
        """Return the entry that proves a lane merged, None when it proves nothing.

        Valid while its main is the tip or an ancestor of it and, for a `record` merge,
        while the integration files hold the same record.
        """
        e = self.known.get(full)
        if e is None:
            return None
        rec = records.get(plan_id)
        if e["how"] == "record" and not (
            rec
            and full.startswith(rec[0])
            and (rec[1], rec[2]) == (e["as"], e["record"])
        ):
            return None
        main = e["main"]
        if main != self.tip and main not in self.ancestry:
            self.ancestry[main] = (
                git(repo, "merge-base", "--is-ancestor", main, self.tip)[0] == 0
            )
        return e if main == self.tip or self.ancestry[main] else None

    def save(self) -> None:
        """Write the kept entries; drop an older version's cache of unmerged answers."""
        if self.path is None:
            return
        write_merged(self.path, self.keep, self.raw)
        # dsp-cherry.json kept unmerged lanes' answers too, which a later merge leaves
        # wrong
        with contextlib.suppress(OSError):
            self.path.with_name("dsp-cherry.json").unlink(missing_ok=True)


def _cache(route: pathlib.Path | None, main: str, tip: str | None) -> _Cache:
    """Return the report's cache of the route at route (its marker) for main's tip."""
    path = merged_path(route) if tip else None
    known, raw = read_merged(path) if path else ({}, None)
    return _Cache(path if raw is not None else None, main, tip or "", known, raw)


@dataclasses.dataclass(frozen=True)
class _Lanes:
    """What each lane checkpoint is checked against."""

    repo: str
    main: str
    worktrees: dict[str, Worktree]
    records: dict[str, tuple[str, str, str]]
    # each checkpoint SHA's full commit SHA, and every commit on main: one git call
    # each for all lanes the cache does not answer, where one per lane cost a hook
    # 24 s at 47 lanes
    commits: dict[str, str]
    on_main: frozenset[str]
    cache: _Cache
    # {lane id: (full SHA, entry)} of the lanes the cache answered
    hits: dict[str, tuple[str, MergedLane]]


def _commits(repo: str, shas: list[str]) -> dict[str, str]:
    """Return {sha: its full commit SHA} for each sha the repository resolves."""
    if not shas:
        return {}
    rc, out = git(
        repo,
        "cat-file",
        "--batch-check=%(objectname)",
        stdin="".join(f"{s}^{{commit}}\n" for s in shas),
    )
    if rc:
        return {}
    # an unresolved sha prints `<sha>^{commit} missing` (or `ambiguous`)
    return {
        s: line
        for s, line in zip(shas, out.splitlines(), strict=True)
        if " " not in line
    }


def _answered(
    repo: str,
    cache: _Cache,
    found: Mapping[str, str],
    records: Mapping[str, tuple[str, str, str]],
) -> tuple[dict[str, tuple[str, MergedLane]], dict[str, str]]:
    """Return the lanes the cache answers, and the full SHA of every other lane's SHA.

    found is {lane id: its SHA}. A 40-hex SHA is looked up as written; the rest are
    resolved first, all in one batched call, which a report whose every lane hits
    never makes.
    """

    def hits(shas: Mapping[str, str]) -> dict[str, tuple[str, MergedLane]]:
        return {
            lane_id: (full, e)
            for lane_id, full in shas.items()
            if FULL_SHA.fullmatch(full)
            and (e := cache.hit(repo, full, lane_id, records))
        }

    answered = hits(found)
    commits = _commits(repo, sorted({s for n, s in found.items() if n not in answered}))
    resolved = {
        n: commits[s] for n, s in found.items() if n not in answered and s in commits
    }
    return answered | hits(resolved), commits


def _merged(lanes: _Lanes, plan_id: str, full: str) -> MergedLane | None:
    """Return how a lane's commit got onto the main branch, None when it is not on it.

    As the cache keeps it, proven against main's tip.
    """
    repo, tip = lanes.repo, lanes.cache.tip
    if full in lanes.on_main:
        return {"main": tip, "how": "ancestor", "as": None, "record": None}
    # A rebased lane: every commit's patch is already on main.
    rc, cherry = git(repo, "cherry", lanes.main, full)
    if rc == 0 and not any(ln.startswith("+") for ln in cherry.splitlines()):
        return {"main": tip, "how": "patch", "as": None, "record": None}
    rec = lanes.records.get(plan_id)
    if (
        rec
        and full.startswith(rec[0])
        and git(repo, "merge-base", "--is-ancestor", rec[1], lanes.main)[0] == 0
    ):
        return {"main": tip, "how": "record", "as": rec[1], "record": rec[2]}
    return None


def _count(out: str) -> int | None:
    """Return a count git printed, None when it printed none."""
    return int(out) if out.isdigit() else None


def _lane_check(
    repo: str, main: str, full: str, worktree: Worktree | None
) -> LaneCheck:
    """Return what the lead checked by hand on a group's return (F80).

    The lane's commits since the main branch, their trailers, and what its worktree
    left uncommitted; the gate at its SHA is derived from the gate logs.
    """
    commits = _count(git(repo, "rev-list", "--count", f"{main}..{full}")[1])
    trailers = git(repo, "log", "--format=%(trailers:only,unfold)", f"{main}..{full}")[
        1
    ]
    keys: dict[str, int] = {}
    for key in (ln.split(":", 1)[0] for ln in trailers.splitlines() if ":" in ln):
        keys[key] = keys.get(key, 0) + 1
    uncommitted = None
    if worktree and worktree[1] == full:
        changed = git(
            str(worktree[0]), "status", "--porcelain", "--untracked-files=no"
        )[1]
        uncommitted = len(changed.splitlines())
    return {
        "commits": commits,
        "trailers": dict(sorted(keys.items())),
        "uncommitted": uncommitted,
    }


def _git_lane(lanes: _Lanes, lane_id: str, sha: str) -> GitLane:
    """Return what git says of one lane's checkpoint SHA.

    A lane the cache answers takes its commit and how it merged from the entry.
    """
    wt = lanes.worktrees.get(lane_id)
    fact: GitLane = {
        "sha": sha,
        "commit": None,
        "merged_how": None,
        "merged_as": None,
        "record": None,
        "worktree": {"path": wt[0], "head": wt[1]} if wt else None,
        "branch_ahead": None,
        "check": None,
    }
    if hit := lanes.hits.get(lane_id):
        # kept with the main it was proven against, so the next report checks that
        full, entry = hit
    else:
        commit = lanes.commits.get(sha)
        if commit is None:
            return fact
        full, entry = commit, _merged(lanes, lane_id, commit)
    fact["commit"] = full
    if entry:
        lanes.cache.keep[full] = entry
        fact["merged_how"], fact["merged_as"] = entry["how"], entry["as"]
        fact["record"] = entry["record"]
    if wt and wt[1] != full:
        # the branch's commits main lacks, by patch: a lane the integrator rebased and
        # merged has none, though its tip is not the checkpoint's
        fact["branch_ahead"] = _count(
            git(
                lanes.repo,
                "rev-list",
                "--count",
                "--right-only",
                "--cherry-pick",
                f"{lanes.main}...{wt[1]}",
            )[1]
        )
    if entry is None:
        fact["check"] = _lane_check(lanes.repo, lanes.main, full, wt)
    return fact


def _git_facts(
    a: RouteArgs,
    repo: str,
    route: pathlib.Path | None,
    state: State,
    index_text: str | None,
) -> tuple[GitFacts, _Cache]:
    """Return the state's git facts, and the cache the merged lanes are kept in.

    The lanes the cache answers are not checked again; it then keeps every lane proven
    merged, written by the caller.
    """
    as_of = time.time()
    main, tip, missing = _main_branch(a, repo)
    drift = base_drift(repo, index_text) if index_text is not None else []
    cache = _cache(route, main, tip)
    found = {c["id"]: s for c in state["checkpoints"] if (s := c["sha"])}
    records = {
        k: (r["lane_sha"], r["main_sha"], r["file"])
        for k, r in state["records"].items()
    }
    hits, commits = _answered(repo, cache, found, records)
    rest = any(i not in hits for i in found)
    # `--`: main names a revision even where a file of that name exists
    on_main = git(repo, "rev-list", main, "--")[1].split() if rest else []
    lanes = _Lanes(
        repo=repo,
        main=main,
        worktrees=_worktrees(repo),
        records=records,
        commits=commits,
        on_main=frozenset(on_main),
        cache=cache,
        hits=hits,
    )
    facts: GitFacts = {
        "as_of": as_of,
        "repo": repo,
        "main": main,
        "main_missing": missing,
        "main_sha": tip,
        "lane_worktrees": sum(1 for b in lanes.worktrees if b != main),
        "drift": drift,
        "pushed": None,
        "lanes": {i: _git_lane(lanes, i, s) for i, s in found.items()},
    }
    return facts, cache


def _checkpoint_sha(text: str) -> tuple[str | None, bool]:
    """Return a checkpoint's SHA, and whether a `Final SHA:` line gave it."""
    final = [m[1] for m in FINAL_SHA.finditer(text)]
    shas = final or [m[0] for m in SHA.finditer(text)]
    return (shas[-1] if shas else None), bool(final)


def _rel(path: pathlib.Path, base: pathlib.Path) -> str:
    """Return path from the planning dir base, as the text prints it."""
    return str(path.relative_to(base) if path.is_relative_to(base) else path)


def _file(
    path: pathlib.Path, base: pathlib.Path, kind: str, *, fresh: bool
) -> FileFact:
    """Return one artefact's facts; without fresh, no `written …s ago` problem."""
    problems, size, age, last, mtime = describe(path)
    if not fresh:
        problems = [p for p in problems if not p.startswith("written ")]
    return {
        "path": _rel(path, base),
        "kind": kind,
        "bytes": size,
        "age_s": age,
        "mtime": mtime,
        "last_line": last,
        "problems": problems,
    }


def _rung(a: RouteArgs, route: pathlib.Path | None) -> str | None:
    """Return the route's rung: --rung, else its marker's."""
    if a.rung:
        return a.rung
    rung = load_json(route).get("rung") if route else None
    return rung if isinstance(rung, str) else None


def _decision_facts(
    a: RouteArgs,
    base: pathlib.Path,
    rung: str | None,
    files: list[FileFact],
    *,
    fresh: bool,
) -> tuple[str | None, DecisionFacts]:
    """Return the decision index's text (None without one) and the decisions' facts.

    Each D file's facts go to files.
    """
    dec = base / "decisions" / f"phase{a.phase}"
    index = dec / "00-index.md"
    index_text = index.read_text(errors="replace") if index.exists() else None
    wanted = sorted(
        {
            m[1]
            for m in re.finditer(
                r"^\|\s*\*{0,2}D(\d+)\b", index_text or "", re.MULTILINE
            )
        },
        key=int,
    )
    have = {
        m[1]: f for f in sorted(dec.glob("D*.md")) if (m := re.match(r"D(\d+)", f.name))
    }
    # At rung S the index holds the decisions themselves: no D file follows
    # (templates.md §1).
    waiting = [f"D{n}" for n in wanted if n not in have and rung != "S"]
    markers = headers = 0
    for f in have.values():
        files.append(_file(f, base, "decision", fresh=fresh))
        text = f.read_text(errors="replace")
        markers += text.count("> **SUPERSEDED BY")
        headers += "> **Read 00-arbiter.md first.**" in text
    return index_text, {
        "index": index_text is not None,
        "index_ids": wanted,
        "files": {i: _rel(f, base) for i, f in have.items()},
        "pending": waiting,
        "markers": markers,
        "headers": headers,
        "fixed": {n: (dec / (n + ".md")).exists() for n in FIXED},
    }


def _spec_facts(
    a: RouteArgs, base: pathlib.Path, files: list[FileFact], *, fresh: bool
) -> SpecFacts:
    """Return the facts of the --sections range; each section file's go to files."""
    lo, sep, hi = (a.sections or "").replace("–", "-").partition("-")
    first, last = int(lo), (int(hi) if hi else (None if sep else int(lo)))
    spec = [
        f
        for f in sorted(pathlib.Path(a.spec_dir or base / "spec").glob("*.md"))
        if (m := re.match(r"0*(\d+)-", f.name))
        and first <= int(m[1]) <= (last if last is not None else 10**6)
    ]
    files.extend(_file(f, base, "spec", fresh=fresh) for f in spec)
    got = {int(m[1]) for f in spec if (m := re.match(r"0*(\d+)-", f.name))}
    return {"first": first, "last": last, "sections": sorted(got)}


def _manifest_state(m: pathlib.Path) -> str:
    """Return whether a manifest parses: ok, missing or invalid."""
    try:
        _ = parse_json(m.read_text())
    except FileNotFoundError:
        return "missing"
    except ValueError:
        return "invalid"
    return "ok"


def _plan_facts(
    base: pathlib.Path, p: str, files: list[FileFact], *, fresh: bool
) -> PlanFacts:
    """Return the plans' facts and the plan ids the index names; plan files to files."""
    plans_dir = base / "plans"
    pindex = plans_dir / f"p{p}-00-index.md"
    ids = sorted(
        set(re.findall(rf"\bp{p}-(\d+[a-z]?)\b", pindex.read_text(errors="replace")))
        - {"00"}
        if pindex.exists()
        else set[str]()
    )
    plans = {
        m[1]: f
        for f in sorted(plans_dir.glob(f"p{p}-*.md"))
        if (m := re.match(rf"p{p}-(\d+[a-z]?)-", f.name))
        and not f.name.startswith(f"p{p}-00")
    }
    manifests: dict[str, ManifestFact] = {}
    for i, f in plans.items():
        files.append(_file(f, base, "plan", fresh=fresh))
        m = _manifest(base, p, i, f)
        manifests[i] = {"name": m.name, "state": _manifest_state(m)}
    return {
        "index_ids": ids,
        "files": {i: _rel(f, base) for i, f in plans.items()},
        "pending": [f"p{p}-{i}" for i in ids if i not in plans],
        "manifests": manifests,
    }


def _checkpoint_facts(
    base: pathlib.Path, p: str, files: list[FileFact], *, fresh: bool
) -> list[CheckpointFact]:
    """Return each lane checkpoint's facts; its file's go to files. No git."""
    out: list[CheckpointFact] = []
    for c in lane_checkpoints(base / "lanes", p):
        text = c.read_text(errors="replace")
        files.append(_file(c, base, "checkpoint", fresh=fresh))
        lane_id = c.name[: -len("-checkpoint.md")]
        sha, final = _checkpoint_sha(text)
        rulings = c.with_name(lane_id + "-rulings.md")
        plan = PLAN_ID.match(lane_id)
        out.append(
            {
                "id": lane_id,
                "plan": plan[0] if plan else lane_id,
                "path": files[-1]["path"],
                "sha": sha,
                "final_sha_line": final,
                "lines": len(text.splitlines()),
                "rulings": (
                    {"name": rulings.name, "bytes": rulings.stat().st_size}
                    if rulings.exists()
                    else None
                ),
            }
        )
    return out


def _gate_fact(gate: GateLog) -> GateLogFact:
    """Return one gate log's facts, its dirty count and exit code as int."""
    log, sha, dirty, code, harness = gate
    return {
        "log": log.name,
        "sha": sha,
        "dirty": int(dirty) if dirty else None,
        "exit": int(code) if code is not None else None,
        "harness": harness,
    }


def _file_facts(
    a: RouteArgs, rung: str | None, *, fresh: bool, extra: Iterable[str]
) -> tuple[State, str | None]:
    """Return the state's file facts, git None, and the decision index's text.

    No git: files in the text's order, every checkpoint's text read.
    """
    base, p = pathlib.Path(a.planning_dir), a.phase
    generated_at = time.time()
    files: list[FileFact] = []
    index_text, decisions = _decision_facts(a, base, rung, files, fresh=fresh)
    spec = _spec_facts(a, base, files, fresh=fresh) if a.sections else None
    reconcile = sorted((base / "reconcile").glob(f"p{p}-*.md"))
    files.extend(_file(f, base, "reconcile", fresh=fresh) for f in reconcile)
    plans = _plan_facts(base, p, files, fresh=fresh)
    lanes = base / "lanes"
    checkpoints = _checkpoint_facts(base, p, files, fresh=fresh)
    waves = sorted(lanes.glob("wave*-integration.md"))
    files.extend(_file(w, base, "wave", fresh=fresh) for w in waves)
    harvest = sorted((base / "decisions" / f"phase{p}").glob("harvest-*.md"))
    state: State = {
        "version": VERSION,
        "planning_dir": a.planning_dir,
        "phase": p,
        "generated_at": generated_at,
        "rung": rung,
        "extra": list(extra),
        "handoffs": [
            {"name": n, "bytes": (base / n).stat().st_size}
            for n in HANDOFFS
            if (base / n).exists()
        ],
        "files": files,
        "decisions": decisions,
        "harvest_files": [_rel(f, base) for f in harvest],
        "spec": spec,
        "reconcile": [_rel(f, base) for f in reconcile],
        "plans": plans,
        "lane_files": any(lanes.glob(f"p{p}-*")),
        "checkpoints": checkpoints,
        "gate_logs": [_gate_fact(g) for g in gate_logs(lanes, p)],
        "records": {
            k: {"lane_sha": lane, "main_sha": main, "file": file}
            for k, (lane, main, file) in _merge_records(lanes).items()
        },
        "integration_files": [_rel(w, base) for w in waves],
        "git": None,
        "lanes": [],
        "flags": [],
        "stages": [],
    }
    return state, index_text


def gate_state(log: GateLogFact) -> str:
    """Return a gate log's own state: green (exit 0), red, or no-exit."""
    if log["exit"] is None:
        return "no-exit"
    return "green" if log["exit"] == 0 else "red"


def _lane_gate(logs: list[GateLogFact]) -> str:
    """Return an open lane's gate from the full-gate logs at its commit, in order."""
    if any(g["dirty"] == 0 and g["exit"] == 0 for g in logs):
        return "green"
    if not logs:
        return "none"
    code = logs[-1]["exit"]
    if code is None:
        return "no-exit"
    return "red" if code else "dirty"


def _lane(c: CheckpointFact, state: State) -> Lane:
    """Return one checkpoint's lane: its basis, then its gate and state."""
    lane: Lane = {
        "id": c["id"],
        "plan": c["plan"],
        "state": "running",
        "basis": "no-sha",
        "gate": None,
        "gate_exit": None,
        "gate_dirty": None,
        "git": False,
    }
    g = state["git"]
    facts = g["lanes"].get(c["id"]) if g else None
    if c["sha"] is None:
        return lane
    if facts is None or facts["sha"] != c["sha"]:
        lane["basis"] = "unchecked"
        return lane
    lane["git"] = True
    commit = facts["commit"]
    if commit is None:
        lane["basis"] = "unknown"
    elif facts["merged_how"]:
        lane["basis"] = lane["state"] = "merged"
    else:
        # a harness log ran only that suite: no full gate
        logs = [
            x for x in state["gate_logs"] if x["sha"] == commit and not x["harness"]
        ]
        gate = _lane_gate(logs)
        lane["basis"], lane["gate"], lane["state"] = "open", gate, BY_GATE[gate]
        if logs:
            lane["gate_exit"], lane["gate_dirty"] = logs[-1]["exit"], logs[-1]["dirty"]
    return lane


def _flag(kind: str, subject: str, line: str) -> Flag:
    """Return one flag."""
    return {"kind": kind, "subject": subject, "line": line}


def _file_flags(files: Iterable[FileFact]) -> list[Flag]:
    """Return a flag per problem of each file."""
    return [
        _flag("file", f["path"], f"{p:<34} {f['path']}  ends: {f['last_line'][:70]!r}")
        for f in files
        for p in f["problems"]
    ]


def _plan_flags(state: State, by_path: Mapping[str, FileFact]) -> list[Flag]:
    """Return each plan file's problems, then its manifest's flag."""
    out: list[Flag] = []
    for i, rel in state["plans"]["files"].items():
        out += _file_flags([by_path[rel]])
        m = state["plans"]["manifests"][i]
        path = f"manifests/{m['name']}"
        if m["state"] == "missing":
            out.append(_flag("no-manifest", path, f"{'no manifest':<34} {path}"))
        elif m["state"] == "invalid":
            what = "manifest is not valid JSON"
            out.append(_flag("manifest-invalid", path, f"{what:<34} {path}"))
    return out


def _checkpoint_flags(c: CheckpointFact, lane: Lane, g: GitFacts | None) -> list[Flag]:
    """Return a lane checkpoint's own flags, after its file's."""
    out: list[Flag] = []
    path, lane_id = c["path"], c["id"]
    if not c["final_sha_line"]:
        what = "no `Final SHA:` line"
        line = f"{what:<34} {path} (last SHA in the text used)"
        out.append(_flag("no-final-sha", path, line))
    if lane["basis"] == "unknown":
        what = "checkpoint SHA not in the repo"
        out.append(_flag("sha-unknown", lane_id, f"{what:<34} {path} ({c['sha']})"))
    facts = g["lanes"].get(lane_id) if g and lane["basis"] == "merged" else None
    if facts and (ahead := facts["branch_ahead"]):
        what = "lane moved past its merged SHA"
        line = f"{what:<34} {lane_id} ({ahead} commits, F41)"
        out.append(_flag("lane-moved-past-merge", lane_id, line))
    if lane["basis"] == "merged":
        return out
    # A merged lane has no next group to read its checkpoint (F76).
    if c["lines"] > CHECKPOINT_MAX:
        what = f"checkpoint over {CHECKPOINT_MAX} lines"
        line = (
            f"{what:<34} {path} ({c['lines']} — the next group overwrites it with the "
            "lane's state and map)"
        )
        out.append(_flag("checkpoint-long", path, line))
    # Every group reads its lane's rulings file whole; applied rulings belong in the
    # archive, read only for an id the dispatch names (F67).
    if (r := c["rulings"]) and r["bytes"] > RULINGS_MAX:
        what, rel = f"rulings over {RULINGS_MAX // 1000} KB", f"lanes/{r['name']}"
        line = (
            f"{what:<34} {rel} ({r['bytes'] // 1000} KB — between groups, move the "
            f"applied ones to {lane_id}-rulings-archive.md)"
        )
        out.append(_flag("rulings-large", rel, line))
    return out


def _gate_flags(logs: Iterable[GateLogFact]) -> list[Flag]:
    """Return a flag per red or unfinished gate log."""
    out: list[Flag] = []
    for x in logs:
        rel, code, ci = f"lanes/{x['log']}", x["exit"], x["harness"]
        if code is None:
            what = "gate log has no exit= line"
            out.append(_flag("gate-no-exit", x["log"], f"{what:<34} {rel}"))
        elif code:
            what = f"RED harness={ci} exit={code}" if ci else f"RED exit={code}"
            out.append(_flag("gate-red", x["log"], f"{what:<34} {rel}"))
    return out


def _flags(state: State, lanes: list[Lane]) -> list[Flag]:
    """Return the state's flags, in the text's order."""
    out: list[Flag] = []
    g = state["git"]
    if g and (given := g["main_missing"]) is not None:
        what = "--main " + given + " does not exist"
        out.append(_flag("main-missing", given, f"{what:<34} using {g['main']}"))
    for h in state["handoffs"]:
        if h["bytes"] > HANDOFF_MAX:
            line = (
                f"{h['name'] + ' over 40 KB':<34} {h['bytes'] / 1024:.0f} KB — move "
                "closed lanes and settled history to HANDOFF-archive.md (F76)"
            )
            out.append(_flag("handoff-large", h["name"], line))

    def of(kind: str) -> list[FileFact]:
        return [f for f in state["files"] if f["kind"] == kind]

    out += _file_flags(of("decision"))
    index = f"decisions/phase{state['phase']}/00-index.md"
    out += [_flag("base-drift", index, line) for line in (g["drift"] if g else [])]
    out += _file_flags(of("spec")) + _file_flags(of("reconcile"))
    by_path = {f["path"]: f for f in state["files"]}
    out += _plan_flags(state, by_path)
    for c, lane in zip(state["checkpoints"], lanes, strict=False):
        out += _file_flags([by_path[c["path"]]]) + _checkpoint_flags(c, lane, g)
    return out + _gate_flags(state["gate_logs"]) + _file_flags(of("wave"))


def derive(state: State) -> State:
    """Return a new state whose lanes and flags are computed from its facts alone.

    Pure: no I/O, no git, no clock. The input's own lanes, flags and stages are
    recomputed, so derive(derive(s)) == derive(s), and older git facts can be laid
    over newer file facts.
    """
    lanes = [_lane(c, state) for c in state["checkpoints"]]
    started = {c["plan"] for c in state["checkpoints"]}
    for i in state["plans"]["index_ids"]:
        plan = f"p{state['phase']}-{i}"
        if plan not in started:
            lanes.append(
                {
                    "id": plan,
                    "plan": plan,
                    "state": "queued",
                    "basis": "planned",
                    "gate": None,
                    "gate_exit": None,
                    "gate_dirty": None,
                    "git": False,
                }
            )
    return {**state, "lanes": lanes, "flags": _flags(state, lanes), "stages": []}


def _how(lane: GitLane) -> str:
    """Return how a merged lane got onto main, as its state says it."""
    if lane["merged_how"] == "record":
        return f" as {lane['merged_as']} ({lane['record']})"
    return " (by patch)" if lane["merged_how"] == "patch" else ""


def _check_text(check: LaneCheck, lane: Lane) -> str:
    """Return an open lane's check: commits, gate at its SHA, trailers, uncommitted."""
    if lane["gate"] == "green":
        gate = "gate exit=0"
    elif lane["gate"] in (None, "none"):
        gate = "no gate log at this SHA"
    else:
        code = "none yet" if lane["gate_exit"] is None else lane["gate_exit"]
        gate = f"gate exit={code} dirty={lane['gate_dirty']}"
    n = check["commits"]
    trailers = ", ".join(f"{k} ×{v}" for k, v in check["trailers"].items())
    parts = [
        f"{'' if n is None else n} commits",
        gate,
        f"trailers {trailers or 'none'}",
    ]
    if check["uncommitted"]:
        parts.append(f"{check['uncommitted']} uncommitted in its worktree")
    return " · ".join(parts)


def _lane_text(c: CheckpointFact, lane: Lane, g: GitFacts | None) -> str:
    """Return a lane's state as its line prints it."""
    facts = g["lanes"].get(lane["id"]) if g else None
    if lane["basis"] == "no-sha":
        return "no SHA"
    if facts is None or lane["basis"] == "unchecked":
        return f"{c['sha']}"
    if lane["basis"] == "unknown":
        return f"{c['sha']} unknown"
    merged = lane["basis"] == "merged"
    text = f"{c['sha']} {'merged' + _how(facts) if merged else 'not merged'}"
    wt = facts["worktree"]
    if wt and wt["head"] != facts["commit"]:
        ahead = facts["branch_ahead"]
        text += f", branch {'' if ahead is None else ahead} not on main"
    if not merged and (check := facts["check"]) is not None:
        text += " · " + _check_text(check, lane)
    return text


def _summary(state: State) -> list[str]:
    """Return the report's summary lines, after its header."""
    d, pl, g = state["decisions"], state["plans"], state["git"]
    present = " ".join(f"{n} {'yes' if ok else 'no'}" for n, ok in d["fixed"].items())
    out = [
        f"decisions  {len(d['files'])} D files ({len(d['index_ids'])} in the index"
        + (f"; pending {pending(d['pending'])}" if d["pending"] else "")
        + f") · markers {d['markers']}, header in {d['headers']}/{len(d['files'])}"
        + f" · {present}"
    ]
    if (spec := state["spec"]) is not None:
        first, last, got = spec["first"], spec["last"], spec["sections"]
        if last is None:
            out.append(f"spec       {len(got)} sections from §{first}")
        else:
            waiting = [f"§{s}" for s in range(first, last + 1) if s not in got]
            out.append(
                f"spec       {len(got)}/{last - first + 1} sections"
                + (f" (pending {pending(waiting)})" if waiting else "")
            )
    out.append(f"reconcile  {len(state['reconcile'])} files")
    ok = sum(m["state"] == "ok" for m in pl["manifests"].values())
    out.append(
        f"plans      {len(pl['files'])} plans ({len(pl['index_ids'])} in the index"
        + (f"; pending {pending(pl['pending'])}" if pl["pending"] else "")
        + f") · {ok} manifests parse"
    )
    merged = sum(ln["basis"] == "merged" for ln in state["lanes"])
    lanes = f"lanes      {len(state['checkpoints'])} checkpoints "
    lanes += f"({len(pl['index_ids'])} plans)"
    if g:
        lanes += f" · {merged} merged into {g['main']} · "
        lanes += f"{g['lane_worktrees']} lane worktrees"
    out.append(lanes)
    logs = [gate_state(x) for x in state["gate_logs"]]
    out.append(
        f"gates      {logs.count('green')} green · {logs.count('red')} red · "
        f"{logs.count('no-exit')} without exit= · "
        f"{len(state['integration_files'])} integration files"
    )
    return out


def render(state: State, *, show_all: bool) -> str:
    """Return the route report's text of a state, header included, no final newline.

    With show_all, each file's line and every lane's; else the lanes not merged.
    """
    at = time.strftime("%Y-%m-%d %H:%M", time.localtime(state["generated_at"]))
    base = pathlib.Path(state["planning_dir"])
    out = [f"route state · {base} · phase {state['phase']} · {at}"]
    out += _summary(state) + state["extra"]
    lanes = {
        c["path"]: (c, lane)
        for c, lane in zip(state["checkpoints"], state["lanes"], strict=False)
    }
    for f in state["files"]:
        if show_all:
            out.append(
                f"    {f['path']:<48} {f['bytes'] / 1024:6.1f} KB "
                f"{ago(f['age_s']):>5}  {f['last_line'][:60]!r}"
            )
        row = lanes.get(f["path"]) if f["kind"] == "checkpoint" else None
        if row and (show_all or row[1]["basis"] != "merged"):
            c, lane = row
            out.append(f"    {lane['id']:<48} {_lane_text(c, lane, state['git'])}")
    out.append(f"flags      {len(state['flags'])}")
    out += [f"  {x['line']}" for x in state["flags"]]
    return "\n".join(out)


def collect(
    a: RouteArgs,
    *,
    fresh: bool = True,
    extra: Iterable[str] = (),
    use_git: bool = True,
    write_cache: bool = False,
) -> State | None:
    """Return the route report of a round as data, None with no planning dir.

    Prints nothing. File facts first, then git facts (None without --repo or with
    use_git False: then no git spawn at all, the marker lookup included), then derive.
    Only with write_cache, and only after derive returns, does it write the
    merged-result cache.
    """
    base = pathlib.Path(a.planning_dir)
    if not base.is_dir():
        return None
    # Without --repo, --activate wrote the marker in the planning dir's repository.
    route = marker_path(a.repo or base, str(base.resolve())) if use_git else None
    state, index_text = _file_facts(a, _rung(a, route), fresh=fresh, extra=extra)
    cache = None
    if use_git and a.repo:
        state["git"], cache = _git_facts(a, a.repo, route, state, index_text)
    state = derive(state)
    if write_cache and cache is not None:
        cache.save()
    return state


def report(a: RouteArgs, *, fresh: bool = True, extra: Iterable[str] = ()) -> int:
    """Print the route report of a round.

    Returns:
        The exit code: 2 with no planning dir, else 0.
    """
    state = collect(a, fresh=fresh, extra=extra, write_cache=True)
    if state is None:
        print(f"no planning dir at {pathlib.Path(a.planning_dir)}")
        return 2
    print(render(state, show_all=a.all))
    return 0
