"""The route report: one screen of a round's state (route_state.py's docstring), printed by the
script and injected into the lead's context by the hook."""

import json
import pathlib
import re
import time

from .common import ago, default_branch, git, load_json, marker_path

FRESH_S = 120
HANDOFF_MAX = 40_000
# the route's handoff (bootstrap.md), or the project's session handoff where it keeps one
HANDOFFS = ("HANDOFF.md", "SESSION-HANDOFF.md")
CHECKPOINT_MAX = 35
RULINGS_MAX = 12_000
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
FINAL_SHA = re.compile(
    r"^\W*Final SHA:\W*([0-9a-f]{7,40})\b", re.MULTILINE | re.IGNORECASE
)
MERGED = re.compile(
    r"^\W*Merged\s+\W*([\w.-]+?)\W+([0-9a-f]{7,40})\W+(?:→|->)\W*([0-9a-f]{7,40})\b",
    re.MULTILINE,
)
# The decision index's header: `> **Base**: `main` at `<sha>`` and one `> **Assumes**: `<ref>` at
# `<sha>`` per unmerged branch the round builds on (templates.md §1).
BASE = re.compile(
    r"^>?\s*\*\*(Base|Assumes)\*\*:\s*`([^`]+)`\s+at\s+`([0-9a-f]{7,40})`", re.MULTILINE
)


def describe(path):
    """(problems, size, age, last line) of one artefact."""
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    age = time.time() - path.stat().st_mtime
    problems = []
    if not lines:
        problems.append("empty")
    if sum(1 for ln in text.split("\n") if ln.lstrip().startswith("```")) % 2:
        problems.append("unpaired ``` fence")
    if age < FRESH_S:
        problems.append(f"written {int(age)}s ago — still being written?")
    return problems, len(text.encode()), age, (lines[-1].strip() if lines else "")


def pending(names):
    names = list(names)
    return " ".join(names[:8]) + (f" +{len(names) - 8}" if len(names) > 8 else "")


class Report:
    def __init__(self, show_all, fresh=True):
        self.show_all, self.fresh, self.lines, self.flags = show_all, fresh, [], []

    def file(self, path, base):
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
        return problems

    def flag(self, text):
        self.flags.append(text)


def lane_checkpoints(lanes, phase):
    """Every lane checkpoint but another phase's: `p<P>-<id>-…` and lanes named any other way."""
    return [
        c
        for c in sorted(lanes.glob("*-checkpoint.md"))
        if not ((m := re.match(r"p(\d+)-", c.name)) and m.group(1) != phase)
    ]


def gate_logs(lanes, phase):
    """(log, the commit and dirty count of its first `sha=` line within 20 lines, its last `exit=`
    or None, the CI harness its first 20 lines name or None) for each gate log but another
    phase's — the lines push_guard.py reads. A harness log ran only that suite: no full gate."""
    out = []
    # Line by line: a whole log read at once raised ENOMEM on a large one. Lines end at `\n`
    # only, as push_guard.py reads them: a progress bar's `\r` before `exit=` is no line break.
    for log in sorted(lanes.glob("*-gate*.log")):
        if (m := re.match(r"p(\d+)-", log.name)) and m.group(1) != phase:
            continue
        first, last, harness = "", None, None
        with log.open(errors="replace", newline="\n") as f:
            for n, ln in enumerate(f):
                if n < 20 and not first and ln.startswith("sha="):
                    first = ln
                if n < 20 and not harness and ln.startswith("harness="):
                    harness = ln[len("harness=") :].strip()
                if m := re.fullmatch(r"exit=(\d+)\s*", ln):
                    last = m.group(1)
        head = re.fullmatch(r"sha=([0-9a-f]{40}) dirty=(\d+)\s*", first)
        sha, dirty = head.groups() if head else ("", "")
        out.append((log, sha, dirty, last, harness))
    return out


def lane_check(repo, main, full, gates, worktree):
    """What the lead checked by hand on a group's return: the lane's commits since the main branch,
    the gate at its SHA, their trailers, and what its worktree left uncommitted (F80)."""
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
    keys = {}
    for key in (ln.split(":", 1)[0] for ln in trailers.splitlines() if ":" in ln):
        keys[key] = keys.get(key, 0) + 1
    parts.append(
        "trailers "
        + (", ".join(f"{k} ×{n}" for k, n in sorted(keys.items())) or "none")
    )
    if worktree and worktree[1] == full:
        changed = git(worktree[0], "status", "--porcelain", "--untracked-files=no")[1]
        if changed:
            parts.append(f"{len(changed.splitlines())} uncommitted in its worktree")
    return " · ".join(parts)


def base_drift(repo, text):
    """What moved under the round since its decision index recorded the base and the unmerged
    refs it assumes, as of the last fetch: a round planned on them is planned on a past (F91)."""
    rows = BASE.findall(text)
    base_ref = next((ref for kind, ref, _ in rows if kind == "Base"), None)
    out = []
    for kind, ref, sha in rows:
        rc, head = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if rc:
            out.append(
                f"{kind.lower() + ' ref gone':<34} {ref} (recorded at {sha[:9]})"
            )
            continue
        if kind == "Base":
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
            for label, name, tip in tips:
                if not tip.startswith(sha):
                    rc, n = git(repo, "rev-list", "--count", f"{sha}..{tip}")
                    out.append(
                        f"{label:<34} {name} {n if rc == 0 else '?'} commits past {sha[:9]}"
                    )
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


def report(a, fresh=True, extra=()):
    base, p = pathlib.Path(a.planning_dir), a.phase
    if not base.is_dir():
        print(f"no planning dir at {base}")
        return 2
    rep = Report(a.all, fresh)
    out = [f"route state · {base} · phase {p} · {time.strftime('%Y-%m-%d %H:%M')}"]
    main = a.main or (default_branch(a.repo) if a.repo else "main")
    if (
        a.repo
        and git(a.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{main}")[0]
    ):
        fallback = default_branch(a.repo)
        rep.flag(f"{'--main ' + main + ' does not exist':<34} using {fallback}")
        main = fallback
    for name in HANDOFFS:
        handoff = base / name
        if handoff.exists() and handoff.stat().st_size > HANDOFF_MAX:
            rep.flag(
                f"{name + ' over 40 KB':<34} {handoff.stat().st_size / 1024:.0f} KB — move "
                "closed lanes and settled history to HANDOFF-archive.md (F76)"
            )

    dec = base / "decisions" / f"phase{p}"
    index = dec / "00-index.md"
    index_text = index.read_text(errors="replace") if index.exists() else ""
    wanted = sorted(
        set(re.findall(r"^\|\s*\*{0,2}D(\d+)\b", index_text, re.MULTILINE)), key=int
    )
    have = {
        m.group(1): f
        for f in sorted(dec.glob("D*.md"))
        if (m := re.match(r"D(\d+)", f.name))
    }
    # At rung S the index holds the decisions themselves: no D file follows (templates.md §1).
    # without --repo, --activate wrote the marker in the planning dir's repository
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
    out.append(
        f"decisions  {len(have)} D files ({len(wanted)} in the index"
        + (f"; pending {pending(waiting)}" if waiting else "")
        + f") · markers {markers}, header in {headers}/{len(have)} · {present}"
    )
    if a.repo and index.exists():
        for line in base_drift(a.repo, index.read_text(errors="replace")):
            rep.flag(line)

    if a.sections:
        lo, sep, hi = a.sections.replace("–", "-").partition("-")
        first, last = int(lo), (int(hi) if hi else (None if sep else int(lo)))
        spec = [
            f
            for f in sorted(pathlib.Path(a.spec_dir or base / "spec").glob("*.md"))
            if (m := re.match(r"0*(\d+)-", f.name))
            and first <= int(m.group(1)) <= (last if last is not None else 10**6)
        ]
        got = {int(m.group(1)) for f in spec if (m := re.match(r"0*(\d+)-", f.name))}
        for f in spec:
            rep.file(f, base)
        if last is None:
            out.append(f"spec       {len(got)} sections from §{first}")
        else:
            waiting = [f"§{s}" for s in range(first, last + 1) if s not in got]
            out.append(
                f"spec       {len(got)}/{last - first + 1} sections"
                + (f" (pending {pending(waiting)})" if waiting else "")
            )

    rec = sorted((base / "reconcile").glob(f"p{p}-*.md"))
    for f in rec:
        rep.file(f, base)
    out.append(f"reconcile  {len(rec)} files")

    plans_dir = base / "plans"
    pindex = plans_dir / f"p{p}-00-index.md"
    ids = sorted(
        set(re.findall(rf"\bp{p}-(\d+[a-z]?)\b", pindex.read_text(errors="replace")))
        - {"00"}
        if pindex.exists()
        else set()
    )
    plans = {
        m.group(1): f
        for f in sorted(plans_dir.glob(f"p{p}-*.md"))
        if (m := re.match(rf"p{p}-(\d+[a-z]?)-", f.name))
        and not f.name.startswith(f"p{p}-00")
    }
    waiting = [f"p{p}-{i}" for i in ids if i not in plans]
    manifests_ok = 0
    for i, f in plans.items():
        rep.file(f, base)
        # The layout names manifests by plan id, prompts.md §4 by the plan file's stem.
        m = base / "manifests" / (f.stem + ".json")
        if not m.exists() and (base / "manifests" / f"p{p}-{i}.json").exists():
            m = base / "manifests" / f"p{p}-{i}.json"
        try:
            json.loads(m.read_text())
            manifests_ok += 1
        except FileNotFoundError:
            rep.flag(f"{'no manifest':<34} manifests/{m.name}")
        except ValueError:
            rep.flag(f"{'manifest is not valid JSON':<34} manifests/{m.name}")
    out.append(
        f"plans      {len(plans)} plans ({len(ids)} in the index"
        + (f"; pending {pending(waiting)}" if waiting else "")
        + f") · {manifests_ok} manifests parse"
    )

    lanes = base / "lanes"
    checkpoints = lane_checkpoints(lanes, p)
    gates = gate_logs(lanes, p)
    merged = 0
    worktrees = {}
    if a.repo:
        rc, wt = git(a.repo, "worktree", "list", "--porcelain")
        path = head = None
        for line in wt.splitlines() + [""]:
            if line.startswith("worktree "):
                path = line[9:]
            elif line.startswith("HEAD "):
                head = line[5:]
            elif line.startswith("branch "):
                worktrees[line.removeprefix("branch refs/heads/")] = (path, head)
    # The integrator's record of a lane it rebased or squashed: `Merged <plan-id> <lane> → <main>`.
    records = {}
    for w in sorted(lanes.glob("wave*-integration*.md")):
        for pid, lane_sha, main_sha in MERGED.findall(w.read_text(errors="replace")):
            records[pid] = (lane_sha, main_sha, w.name)
    for c in checkpoints:
        rep.file(c, base)
        plan_id = c.name[: -len("-checkpoint.md")]
        text = c.read_text(errors="replace")
        final = FINAL_SHA.findall(text)
        shas = final or SHA.findall(text)
        sha = shas[-1] if shas else None
        if not final:
            rep.flag(
                f"{'no `Final SHA:` line':<34} lanes/{c.name} (last SHA in the text used)"
            )
        state = "no SHA"
        inside = False
        full = None
        if sha and a.repo:
            rc, full = git(
                a.repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"
            )
            if rc:
                rep.flag(
                    f"{'checkpoint SHA not in the repo':<34} lanes/{c.name} ({sha})"
                )
                state = f"{sha} unknown"
            else:
                inside = git(a.repo, "merge-base", "--is-ancestor", full, main)[0] == 0
                how = ""
                if not inside:
                    # A rebased lane: every commit's patch is already on main.
                    rc, cherry = git(a.repo, "cherry", main, full)
                    inside = rc == 0 and not any(
                        ln.startswith("+") for ln in cherry.splitlines()
                    )
                    how = " (by patch)" if inside else ""
                rec = records.get(plan_id)
                if not inside and rec and full.startswith(rec[0]):
                    inside = (
                        git(a.repo, "merge-base", "--is-ancestor", rec[1], main)[0] == 0
                    )
                    how = f" as {rec[1]} ({rec[2]})" if inside else ""
                merged += inside
                state = f"{sha} {'merged' + how if inside else 'not merged'}"
                if plan_id in worktrees:
                    head = worktrees[plan_id][1]
                    if head != full:
                        # the branch's commits main lacks, by patch: a lane the integrator
                        # rebased and merged has none, though its tip is not the checkpoint's
                        ahead = git(
                            a.repo,
                            "rev-list",
                            "--count",
                            "--right-only",
                            "--cherry-pick",
                            f"{main}...{head}",
                        )[1]
                        state += f", branch {ahead} not on main"
                        if inside and ahead not in ("", "0"):
                            rep.flag(
                                f"{'lane moved past its merged SHA':<34} {plan_id} ({ahead} commits, F41)"
                            )
        elif sha:
            state = sha
        size = len(text.splitlines())
        # A merged lane has no next group to read its checkpoint (F76).
        if size > CHECKPOINT_MAX and not inside:
            rep.flag(
                f"{f'checkpoint over {CHECKPOINT_MAX} lines':<34} lanes/{c.name} ({size} — "
                "the next group overwrites it with the lane's state and map)"
            )
        # Every group reads its lane's rulings file whole; applied rulings belong in the archive,
        # read only for an id the dispatch names (F67).
        rulings = c.with_name(plan_id + "-rulings.md")
        if not inside and rulings.exists() and rulings.stat().st_size > RULINGS_MAX:
            rep.flag(
                f"{f'rulings over {RULINGS_MAX // 1000} KB':<34} lanes/{rulings.name} "
                f"({rulings.stat().st_size // 1000} KB — between groups, move the applied ones "
                f"to {plan_id}-rulings-archive.md)"
            )
        # Every open lane gets its line, so a group's return changes it and the next injection
        # carries the check the lead used to make by hand (F80).
        if full and not inside:
            state += " · " + lane_check(
                a.repo, main, full, gates, worktrees.get(plan_id)
            )
        if a.all or not inside:
            rep.lines.append(f"    {plan_id:<48} {state}")
    lane_trees = sum(1 for b in worktrees if b != main)
    out.append(
        f"lanes      {len(checkpoints)} checkpoints ({len(ids)} plans)"
        + (
            f" · {merged} merged into {main} · {lane_trees} lane worktrees"
            if a.repo
            else ""
        )
    )

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
    out.append(
        f"gates      {green} green · {red} red · {running} without exit= · {len(waves)} integration files"
    )
    out.extend(extra)

    print("\n".join(out))
    if rep.lines:
        print("\n".join(rep.lines))
    print(f"flags      {len(rep.flags)}")
    for f in rep.flags:
        print(f"  {f}")
    return 0
