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
from collections.abc import Iterable

from .common import (
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
# Each lane's `git cherry` answer, kept in the git common dir for one main tip: a
# cherry walks main's trees since the lane's base, 4-5 s each on a slow drive. Not
# `dsp-route*.json`, which push_guard.py reads as route markers.
CHERRIES = "dsp-cherry.json"
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


def describe(path: pathlib.Path) -> tuple[list[str], int, float, str]:
    """Return (problems, size, age, last line) of one artefact."""
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    age = time.time() - path.stat().st_mtime
    problems: list[str] = []
    if not lines:
        problems.append("empty")
    if sum(1 for ln in text.split("\n") if ln.lstrip().startswith("```")) % 2:
        problems.append("unpaired ``` fence")
    if age < FRESH_S:
        problems.append(f"written {int(age)}s ago — still being written?")
    return problems, len(text.encode()), age, (lines[-1].strip() if lines else "")


def pending(names: Iterable[str]) -> str:
    """Return the first PENDING_MAX names, and how many more there are."""
    names = list(names)
    more = len(names) - PENDING_MAX
    return " ".join(names[:PENDING_MAX]) + (f" +{more}" if more > 0 else "")


class Report:
    """The report's per-file lines and its flags, gathered while it reads the round."""

    def __init__(self, *, show_all: bool, fresh: bool = True) -> None:
        """Start an empty report; `show_all` lists each file, `fresh` flags new ones."""
        self.show_all: bool = show_all
        self.fresh: bool = fresh
        self.lines: list[str] = []
        self.flags: list[str] = []

    def file(self, path: pathlib.Path, base: pathlib.Path) -> None:
        """Flag an artefact's problems and, with show_all, list it."""
        problems, size, age, last = describe(path)
        if not self.fresh:
            problems = [p for p in problems if not p.startswith("written ")]
        rel = path.relative_to(base) if path.is_relative_to(base) else path
        for p in problems:
            self.flags.append(f"{p:<34} {rel}  ends: {last[:70]!r}")
        if self.show_all:
            self.lines.append(
                f"    {rel!s:<48} {size / 1024:6.1f} KB {ago(age):>5}  {last[:60]!r}"
            )

    def flag(self, text: str) -> None:
        """Add a flag."""
        self.flags.append(text)


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


def lane_check(
    repo: StrPath,
    main: str,
    full: str,
    gates: Iterable[GateLog],
    worktree: Worktree | None,
) -> str:
    """Return what the lead checked by hand on a group's return (F80).

    The lane's commits since the main branch, the gate at its SHA, their trailers, and
    what its worktree left uncommitted.
    """
    parts = [f"{git(repo, 'rev-list', '--count', f'{main}..{full}')[1]} commits"]
    at = [(dirty, code) for _, sha, dirty, code, ci in gates if sha == full and not ci]
    if any(at_ == ("0", "0") for at_ in at):
        parts.append("gate exit=0")
    elif at:
        parts.append(f"gate exit={at[-1][1] or 'none yet'} dirty={at[-1][0]}")
    else:
        parts.append("no gate log at this SHA")
    trailers = git(repo, "log", "--format=%(trailers:only,unfold)", f"{main}..{full}")[
        1
    ]
    keys: dict[str, int] = {}
    for key in (ln.split(":", 1)[0] for ln in trailers.splitlines() if ":" in ln):
        keys[key] = keys.get(key, 0) + 1
    parts.append(
        "trailers "
        + (", ".join(f"{k} ×{n}" for k, n in sorted(keys.items())) or "none")
    )
    if worktree and worktree[1] == full:
        changed = git(
            str(worktree[0]), "status", "--porcelain", "--untracked-files=no"
        )[1]
        if changed:
            parts.append(f"{len(changed.splitlines())} uncommitted in its worktree")
    return " · ".join(parts)


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


def _main_branch(a: RouteArgs, rep: Report) -> str:
    """Return the main branch the report checks lanes against; flag a missing --main."""
    main = a.main or (default_branch(a.repo) if a.repo else "main")
    if (
        a.repo
        and git(a.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{main}")[0]
    ):
        fallback = default_branch(a.repo)
        rep.flag(f"{'--main ' + main + ' does not exist':<34} using {fallback}")
        main = fallback
    return main


def _handoff_flags(base: pathlib.Path, rep: Report) -> None:
    """Flag a handoff past HANDOFF_MAX (F76)."""
    for name in HANDOFFS:
        handoff = base / name
        if handoff.exists() and handoff.stat().st_size > HANDOFF_MAX:
            rep.flag(
                f"{name + ' over 40 KB':<34} {handoff.stat().st_size / 1024:.0f} KB — "
                "move closed lanes and settled history to HANDOFF-archive.md (F76)"
            )


def _decisions(a: RouteArgs, base: pathlib.Path, rep: Report) -> str:
    """Return the report's `decisions` line; flag the D files and the base's drift."""
    dec = base / "decisions" / f"phase{a.phase}"
    index = dec / "00-index.md"
    index_text = index.read_text(errors="replace") if index.exists() else ""
    wanted = sorted(
        {m[1] for m in re.finditer(r"^\|\s*\*{0,2}D(\d+)\b", index_text, re.MULTILINE)},
        key=int,
    )
    have = {
        m[1]: f for f in sorted(dec.glob("D*.md")) if (m := re.match(r"D(\d+)", f.name))
    }
    # At rung S the index holds the decisions themselves: no D file follows
    # (templates.md §1). Without --repo, --activate wrote the marker in the planning
    # dir's repository.
    route = marker_path(a.repo or base, str(base.resolve()))
    rung = a.rung or (load_json(route).get("rung") if route else None)
    waiting = [f"D{n}" for n in wanted if n not in have and rung != "S"]
    markers = headers = 0
    for f in have.values():
        rep.file(f, base)
        text = f.read_text(errors="replace")
        markers += text.count("> **SUPERSEDED BY")
        headers += "> **Read 00-arbiter.md first.**" in text
    fixed = [
        "00-dispatch",
        "00-framing-review",
        "00-seams",
        "00-arbiter",
        "spec-returns",
    ]
    present = " ".join(
        f"{n} {'yes' if (dec / (n + '.md')).exists() else 'no'}" for n in fixed
    )
    if a.repo and index.exists():
        for line in base_drift(a.repo, index_text):
            rep.flag(line)
    return (
        f"decisions  {len(have)} D files ({len(wanted)} in the index"
        + (f"; pending {pending(waiting)}" if waiting else "")
        + f") · markers {markers}, header in {headers}/{len(have)} · {present}"
    )


def _spec(a: RouteArgs, sections: str, base: pathlib.Path, rep: Report) -> str:
    """Return the report's `spec` line for --sections; flag the section files."""
    lo, sep, hi = sections.replace("–", "-").partition("-")
    first, last = int(lo), (int(hi) if hi else (None if sep else int(lo)))
    spec = [
        f
        for f in sorted(pathlib.Path(a.spec_dir or base / "spec").glob("*.md"))
        if (m := re.match(r"0*(\d+)-", f.name))
        and first <= int(m[1]) <= (last if last is not None else 10**6)
    ]
    got = {int(m[1]) for f in spec if (m := re.match(r"0*(\d+)-", f.name))}
    for f in spec:
        rep.file(f, base)
    if last is None:
        return f"spec       {len(got)} sections from §{first}"
    waiting = [f"§{s}" for s in range(first, last + 1) if s not in got]
    return f"spec       {len(got)}/{last - first + 1} sections" + (
        f" (pending {pending(waiting)})" if waiting else ""
    )


def _manifest(
    base: pathlib.Path, p: str, plan_id: str, plan: pathlib.Path
) -> pathlib.Path:
    """Return a plan's manifest: by plan id in the layout, its stem in prompts.md §4."""
    m = base / "manifests" / (plan.stem + ".json")
    if not m.exists() and (base / "manifests" / f"p{p}-{plan_id}.json").exists():
        m = base / "manifests" / f"p{p}-{plan_id}.json"
    return m


def _plans(base: pathlib.Path, p: str, rep: Report) -> tuple[str, list[str]]:
    """Return the report's `plans` line and the plan ids the index names."""
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
    waiting = [f"p{p}-{i}" for i in ids if i not in plans]
    manifests_ok = 0
    for i, f in plans.items():
        rep.file(f, base)
        m = _manifest(base, p, i, f)
        try:
            _ = parse_json(m.read_text())
            manifests_ok += 1
        except FileNotFoundError:
            rep.flag(f"{'no manifest':<34} manifests/{m.name}")
        except ValueError:
            rep.flag(f"{'manifest is not valid JSON':<34} manifests/{m.name}")
    line = (
        f"plans      {len(plans)} plans ({len(ids)} in the index"
        + (f"; pending {pending(waiting)}" if waiting else "")
        + f") · {manifests_ok} manifests parse"
    )
    return line, ids


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


@dataclasses.dataclass(frozen=True)
class _Lanes:
    """What each lane checkpoint is checked against."""

    repo: str | None
    main: str
    gates: list[GateLog]
    worktrees: dict[str, Worktree]
    records: dict[str, tuple[str, str, str]]
    # each checkpoint SHA's full commit SHA, and every commit on main: one git call
    # each for all lanes, where one per lane cost a hook 24 s at 47 lanes
    commits: dict[str, str]
    on_main: frozenset[str]
    # {lane commit: whether main holds its every patch} at main's tip; _merged adds
    cherries: dict[str, bool]


def _cherries(repo: str, tip: str) -> tuple[pathlib.Path | None, dict[str, bool]]:
    """Return the cherry cache's file and the answers it holds for main's tip."""
    route = marker_path(repo)
    if route is None:
        return None, {}
    path = route.with_name(CHERRIES)
    held = as_dict(load_json(path).get(tip)) or {}
    return path, {k: v for k, v in held.items() if isinstance(v, bool)}


def _save_cherries(path: pathlib.Path, tip: str, cherries: dict[str, bool]) -> None:
    """Replace the cherry cache whole, so a concurrent hook never reads half of it."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}")
    # a cache: a read-only git dir costs the next report its cherries, nothing else
    with contextlib.suppress(OSError):
        _ = tmp.write_text(json.dumps({tip: cherries}))
        _ = tmp.replace(path)


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


def _merged(lanes: _Lanes, repo: str, plan_id: str, full: str) -> tuple[bool, str]:
    """Return whether a lane's commit is on the main branch, and how it got there."""
    main = lanes.main
    inside = full in lanes.on_main
    how = ""
    if not inside:
        # A rebased lane: every commit's patch is already on main.
        held = lanes.cherries.get(full)
        if held is None:
            rc, cherry = git(repo, "cherry", main, full)
            held = rc == 0 and not any(ln.startswith("+") for ln in cherry.splitlines())
            # a failed cherry is asked again, never kept as an answer
            if rc == 0:
                lanes.cherries[full] = held
        inside = held
        how = " (by patch)" if inside else ""
    rec = lanes.records.get(plan_id)
    if not inside and rec and full.startswith(rec[0]):
        inside = git(repo, "merge-base", "--is-ancestor", rec[1], main)[0] == 0
        how = f" as {rec[1]} ({rec[2]})" if inside else ""
    return inside, how


def _branch_note(
    lanes: _Lanes, repo: str, plan_id: str, full: str, *, inside: bool
) -> tuple[str, str | None]:
    """Return the state note for a lane branch whose tip is not its checkpoint's.

    With the flag for a merged lane that moved past its SHA (F41), else None.
    """
    head = lanes.worktrees[plan_id][1]
    if head == full:
        return "", None
    # the branch's commits main lacks, by patch: a lane the integrator rebased and
    # merged has none, though its tip is not the checkpoint's
    ahead = git(
        repo,
        "rev-list",
        "--count",
        "--right-only",
        "--cherry-pick",
        f"{lanes.main}...{head}",
    )[1]
    flag = None
    if inside and ahead not in ("", "0"):
        flag = (
            f"{'lane moved past its merged SHA':<34} {plan_id} ({ahead} commits, F41)"
        )
    return f", branch {ahead} not on main", flag


def _lane_state(
    lanes: _Lanes, plan_id: str, sha: str | None, name: str, rep: Report
) -> tuple[str, bool, str | None]:
    """Return a lane's (state, merged, full SHA) from its checkpoint's SHA."""
    if not sha:
        return "no SHA", False, None
    if not lanes.repo:
        return sha, False, None
    repo = lanes.repo
    full = lanes.commits.get(sha)
    if full is None:
        rep.flag(f"{'checkpoint SHA not in the repo':<34} lanes/{name} ({sha})")
        return f"{sha} unknown", False, None
    inside, how = _merged(lanes, repo, plan_id, full)
    state = f"{sha} {'merged' + how if inside else 'not merged'}"
    if plan_id in lanes.worktrees:
        note, flag = _branch_note(lanes, repo, plan_id, full, inside=inside)
        state += note
        if flag:
            rep.flag(flag)
    return state, inside, full


def _checkpoint_sha(text: str) -> tuple[str | None, bool]:
    """Return a checkpoint's SHA, and whether a `Final SHA:` line gave it."""
    final = [m[1] for m in FINAL_SHA.finditer(text)]
    shas = final or [m[0] for m in SHA.finditer(text)]
    return (shas[-1] if shas else None), bool(final)


def _checkpoint(
    c: pathlib.Path, text: str, base: pathlib.Path, lanes: _Lanes, rep: Report
) -> bool:
    """Report one lane checkpoint, whose text is text; return whether it is merged."""
    rep.file(c, base)
    plan_id = c.name[: -len("-checkpoint.md")]
    sha, final = _checkpoint_sha(text)
    if not final:
        rep.flag(
            f"{'no `Final SHA:` line':<34} lanes/{c.name} (last SHA in the text used)"
        )
    state, inside, full = _lane_state(lanes, plan_id, sha, c.name, rep)
    size = len(text.splitlines())
    # A merged lane has no next group to read its checkpoint (F76).
    if size > CHECKPOINT_MAX and not inside:
        rep.flag(
            f"{f'checkpoint over {CHECKPOINT_MAX} lines':<34} lanes/{c.name} ({size} — "
            "the next group overwrites it with the lane's state and map)"
        )
    # Every group reads its lane's rulings file whole; applied rulings belong in the
    # archive, read only for an id the dispatch names (F67).
    rulings = c.with_name(plan_id + "-rulings.md")
    if not inside and rulings.exists() and rulings.stat().st_size > RULINGS_MAX:
        rep.flag(
            f"{f'rulings over {RULINGS_MAX // 1000} KB':<34} lanes/{rulings.name} "
            f"({rulings.stat().st_size // 1000} KB — between groups, move the applied "
            f"ones to {plan_id}-rulings-archive.md)"
        )
    # Every open lane gets its line, so a group's return changes it and the next
    # injection carries the check the lead used to make by hand (F80).
    if full and not inside and lanes.repo:
        state += " · " + lane_check(
            lanes.repo,
            lanes.main,
            full,
            lanes.gates,
            lanes.worktrees.get(plan_id),
        )
    if rep.show_all or not inside:
        rep.lines.append(f"    {plan_id:<48} {state}")
    return inside


def _lanes_line(
    a: RouteArgs, main: str, gates: list[GateLog], plans: int, rep: Report
) -> str:
    """Return the report's `lanes` line; report each lane checkpoint."""
    base = pathlib.Path(a.planning_dir)
    lanes_dir = base / "lanes"
    checkpoints = lane_checkpoints(lanes_dir, a.phase)
    texts = {c: c.read_text(errors="replace") for c in checkpoints}
    shas = sorted({s for t in texts.values() if (s := _checkpoint_sha(t)[0])})
    # `--`: main names a revision even where a file of that name exists; newest first
    on_main = git(a.repo, "rev-list", main, "--")[1].split() if a.repo and shas else []
    tip = on_main[0] if on_main else ""
    store, cherries = _cherries(a.repo, tip) if a.repo and tip else (None, {})
    lanes = _Lanes(
        repo=a.repo,
        main=main,
        gates=gates,
        worktrees=_worktrees(a.repo) if a.repo else {},
        records=_merge_records(lanes_dir),
        commits=_commits(a.repo, shas) if a.repo else {},
        on_main=frozenset(on_main),
        cherries=dict(cherries),
    )
    merged = sum(_checkpoint(c, texts[c], base, lanes, rep) for c in checkpoints)
    if store and lanes.cherries != cherries:
        _save_cherries(store, tip, lanes.cherries)
    lane_trees = sum(1 for b in lanes.worktrees if b != main)
    return f"lanes      {len(checkpoints)} checkpoints ({plans} plans)" + (
        f" · {merged} merged into {main} · {lane_trees} lane worktrees"
        if a.repo
        else ""
    )


def _gates_line(
    gates: list[GateLog], lanes: pathlib.Path, base: pathlib.Path, rep: Report
) -> str:
    """Return the report's `gates` line; flag a red or unfinished gate log."""
    green = red = running = 0
    for log, _, _, code, ci in gates:
        if code is None:
            running += 1
            rep.flag(f"{'gate log has no exit= line':<34} lanes/{log.name}")
        elif code == "0":
            green += 1
        else:
            red += 1
            what = f"RED harness={ci} exit={code}" if ci else f"RED exit={code}"
            rep.flag(f"{what:<34} lanes/{log.name}")
    waves = sorted(lanes.glob("wave*-integration.md"))
    for w in waves:
        rep.file(w, base)
    return (
        f"gates      {green} green · {red} red · {running} without exit= · "
        f"{len(waves)} integration files"
    )


def report(a: RouteArgs, *, fresh: bool = True, extra: Iterable[str] = ()) -> int:
    """Print the route report of a round.

    Returns:
        The exit code: 2 with no planning dir, else 0.
    """
    base, p = pathlib.Path(a.planning_dir), a.phase
    if not base.is_dir():
        print(f"no planning dir at {base}")
        return 2
    rep = Report(show_all=a.all, fresh=fresh)
    out = [f"route state · {base} · phase {p} · {time.strftime('%Y-%m-%d %H:%M')}"]
    main = _main_branch(a, rep)
    _handoff_flags(base, rep)
    out.append(_decisions(a, base, rep))
    if a.sections:
        out.append(_spec(a, a.sections, base, rep))

    rec = sorted((base / "reconcile").glob(f"p{p}-*.md"))
    for f in rec:
        rep.file(f, base)
    out.append(f"reconcile  {len(rec)} files")

    plans_line, ids = _plans(base, p, rep)
    out.append(plans_line)
    lanes = base / "lanes"
    gates = gate_logs(lanes, p)
    out.append(_lanes_line(a, main, gates, len(ids), rep))
    out.append(_gates_line(gates, lanes, base, rep))
    out.extend(extra)

    print("\n".join(out))
    if rep.lines:
        print("\n".join(rep.lines))
    print(f"flags      {len(rep.flags)}")
    for f in rep.flags:
        print(f"  {f}")
    return 0
