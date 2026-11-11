# SPDX-License-Identifier: MIT
"""The PreToolUse holds on the lead's dispatches in an active route.

A harvester at rung S (F87), the decision ledger, and the route's budget with each
allowed dispatch's ETA (F74, F83). The hold on a route agent with no route (F79) is the
hook's own: it runs before any route is read.
"""

import contextlib
import io
import pathlib
import re
import statistics
from collections.abc import Iterable, Mapping

from .common import (
    EXEC,
    LEDGER_CHECKS,
    PLAN_ID,
    SCRIPT,
    SLACK,
    Budget,
    RegistryEntry,
    RouteArgs,
    StrPath,
    as_dict,
    budgets,
    checked,
    deny,
    emit,
    load_json,
    parse_json,
    route_args,
    routes,
    save_budget,
)
from .transcript import (
    answered_since,
    ended_run,
    event_transcript,
    finished_spans,
    session_transcripts,
)

# The phase an agent's name names (`harvest-code-p9`, `exec-p9-01-a`, `dec-p9-D1`): that
# phase's work, not another's budget's.
PHASE_OF = re.compile(r"(?<![A-Za-z0-9])p(\d+)(?=-|$)")


def _tool_input(event: Mapping[str, object]) -> dict[str, object]:
    """Return a hook event's tool input, {} without one."""
    return as_dict(event.get("tool_input")) or {}


def _phases(name: str) -> set[str]:
    """Return the phases an agent's name names."""
    return {m[1] for m in PHASE_OF.finditer(name)}


def leads(event: Mapping[str, object], marker: pathlib.Path) -> list[pathlib.Path]:
    """Return the route's lead transcripts: this session's and any other registered."""
    own = event_transcript(event)
    found = [own] if own else []
    for sid, e in routes():
        if e.get("marker") == str(marker):
            found += [p.resolve() for p in session_transcripts(sid)]
    return list(dict.fromkeys(found))


def dead_recipient(event: Mapping[str, object], entry: RegistryEntry) -> str | None:
    """Return the refusal of the lead's message to an ended agent, else None (F64)."""
    if event.get("tool_name") != "SendMessage":
        return None
    to = str(_tool_input(event).get("to") or "")
    ended = ended_run(leads(event, pathlib.Path(entry["marker"])), to) if to else None
    if not ended:
        return None
    stamp, reason = ended
    return (
        f"{to} stopped for good at {stamp} ({reason or 'its run failed'}): its idle "
        "notice says its run ended, and a message never reaches it — after a spend "
        "limit one lead messaged such an agent twice and reported it running for 20 "
        "min. Dispatch a fresh agent with its brief, told to continue from its file's "
        "end (SKILL.md, F64)."
    )


def spend(paths: Iterable[pathlib.Path], since: str, phase: str) -> float:
    """Return the units these leads, their agents and hook sessions spent since `since`.

    The route's budget prices the lead and every review and agent (F74) — but a lead's
    prompt written again after it sat idle past the cache's life: that is the wait for
    the user's answer, and one such rewrite after a 3 h wait tipped a wave over (F93).
    An agent whose name names another phase (`harvest-code-p9`, `exec-p9-01-a`) is that
    phase's: another phase's harvest and decision round in the same lead session made 8
    of 20 over-budget holds false (F74).
    """
    import usage_report

    total, projects = 0.0, set[pathlib.Path]()
    for path in paths:
        lead, agents, sdk = usage_report.route_cost(path, since)
        total += lead["units"] - lead["idle"]
        total += sum(a["units"] for a in agents if _phases(a["name"]) <= {str(phase)})
        if path.parent not in projects:
            projects.add(path.parent)
            total += sum(s["units"] for s in sdk)
    return total


def s_harvester(event: Mapping[str, object], entry: RegistryEntry) -> bool:
    """Return whether the lead dispatches a harvester on a rung-S route (F87).

    At S the lead harvests itself. A harvest named in the dispatch counts, not a task
    group or verifier whose work names one (`Fix harvest-date parsing`) or a review of
    harvested findings.
    """
    if event.get("tool_name") != "Agent":
        return False
    dispatch = _tool_input(event)
    name = str(dispatch.get("name") or "")
    if name.startswith(("exec-", "verify-")):
        return False
    text = f"{name} {dispatch.get('description') or ''}"
    rung = load_json(pathlib.Path(entry["marker"])).get("rung")
    return rung == "S" and bool(
        re.search(r"\bharvest(?:ers?|ing|s)?\b", text, re.IGNORECASE)
    )


def _verifier_hold(
    tool_input: Mapping[str, object], d: pathlib.Path, planning_dir: str, script: str
) -> str | None:
    """Return why a `verify-` dispatch's prompt is not one decision_check.py wrote."""
    prompt = str(tool_input.get("prompt") or "").strip()
    reviews = pathlib.Path(planning_dir) / "reviews"
    # the phase's, a review round's (`<round>/verify/`), a sins run's or its slice's
    files = [
        *d.glob("**/verify/*.prompt.md"),
        *reviews.glob("**/verify/*.prompt.md"),
    ]
    written = {p.read_text(errors="replace").strip() for p in files}
    if prompt in written:
        return None
    return (
        "a verifier's prompt is the file `decision_check.py --verifier R<n> --sha "
        "<commit>` wrote, unchanged: the finding and the commit, with no SETTLED list, "
        f"rationale or reviewer name ({script}; failure-modes F86)."
    )


def ledger_hold(event: Mapping[str, object], entry: RegistryEntry) -> str | None:
    """Return why the decision ledger holds an `exec-` or `verify-` dispatch."""
    import decision_check

    marker = as_dict(parse_json(pathlib.Path(entry["marker"]).read_text())) or {}
    phase = route_args(marker).phase
    d = pathlib.Path(entry["planning_dir"]) / "decisions" / f"phase{phase}"
    tool_input = _tool_input(event)
    script = pathlib.Path(decision_check.__file__).resolve()
    if str(tool_input.get("name") or "").startswith("verify-"):
        return _verifier_hold(tool_input, d, entry["planning_dir"], str(script))
    ledger = as_dict(marker.get("ledger")) or {}
    # the phase's index when bound, and each review round's own index unless it
    # predates the phase's first activation
    rounds = [d] if ledger.get(phase) else []
    rounds += [
        i.parent
        for i in sorted(d.glob("*/00-index.md"))
        if ledger.get(f"{phase}/{i.parent.name}", True)
    ]
    held = [
        f"the decision ledger fails `{script} {r}` — fix each line, then dispatch:\n"
        + fails
        for r in rounds
        if (r / "00-index.md").exists() and (fails := round_fails(r, marker))
    ]
    return "\n".join(held) or None


def review_hold(entry: RegistryEntry) -> str | None:
    """Return why the route holds a review comment, else None (F104).

    Each round of the phase whose index records a review (`**Review**`) must pass
    decision_check.py. A route that records no review holds nothing: its comments
    answer a ticket or a reviewer, and a guard on every comment teaches agents to route
    around it (F96).
    """
    import decision_check

    marker = as_dict(parse_json(pathlib.Path(entry["marker"]).read_text())) or {}
    phase = route_args(marker).phase
    d = pathlib.Path(entry["planning_dir"]) / "decisions" / f"phase{phase}"
    reviews = [
        i.parent
        for i in [d / "00-index.md", *sorted(d.glob("*/00-index.md"))]
        if i.exists() and decision_check.REVIEW.search(i.read_text(errors="replace"))
    ]
    script = pathlib.Path(decision_check.__file__).resolve()
    held = [
        f"the review's decision document fails `{script} {r}` — fix each line, then "
        "post. A verdict rests on the files read and the probes run; while one is "
        "missing it says unfinished (templates.md §1, tasks.md):\n" + fails
        for r in reviews
        if (fails := round_fails(r, marker))
    ]
    return "\n".join(held) or None


def round_fails(r: pathlib.Path, marker: Mapping[str, object]) -> str | None:
    """Return decision_check.py's output on round r when it fails, else None.

    A review's range is read in the route's repository (F104).
    """
    import decision_check

    route = route_args(marker)
    ledger = as_dict(marker.get("ledger")) or {}
    legacy = (
        [] if ledger.get(f"{route.phase}#checks") == LEDGER_CHECKS else ["--legacy"]
    )
    repo = ["--repo", route.repo] if route.repo else []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = decision_check.main(
            [str(r), "--rung", str(marker.get("rung") or "M"), *legacy, *repo]
        )
    return out.getvalue().strip() if code == 1 else None


def base_hold(
    planning_dir: StrPath, route: RouteArgs, found: list[Budget]
) -> str | None:
    """Return what moved under the round, unless the user's latest choice covers it.

    What moved is report.moved_under's. Pin and merge cover any move, catch-up the
    moves it was recorded with (F91).
    """
    from .report import round_moved

    # a check that raises holds nothing, and leaves the budget's own checks standing
    moved = checked(round_moved, planning_dir, route)
    choice = next((b for b in reversed(found) if b.get("base")), None)
    how = choice.get("base") if choice else None
    if not moved or how in ("pin", "merge"):
        return None
    if how == "catch-up" and choice and set(moved) <= set(choice.get("moved") or []):
        return None
    return (
        "what this round was planned on moved, as of the last fetch:\n"
        + "\n".join(f"  {ln}" for ln in moved)
        + "\nAsk the user with the budget: pin (build on the recorded base), catch up "
        "(re-check each ruling on the moved ref and re-plan, priced) or track by merge "
        "(merge the base into each lane as it goes); record the answer with `python3 "
        f'{SCRIPT} --budget "<route>" --estimate <M> --base pin|catch-up|merge`. One '
        "route's report flagged a moved base seven times, no lead raised it, and the "
        "catch-up rounds cost 44.8M (F91)."
    )


def _answer(event: Mapping[str, object], b: Budget) -> str | None:
    """Return when the user answered the budget in the session that recorded it."""
    # Only the recording session's transcripts: a new session's "read the handoff
    # and proceed" once approved a figure that session never told the user (F74). A
    # session with no prompt of the user's answers only its own dispatches
    # (headless `claude -p`).
    recorder = b.get("session") or ""
    rec = session_transcripts(recorder)
    answered = answered_since(rec, b["at"]) if rec else None
    if answered == b["at"] and recorder != event.get("session_id"):
        return None
    return answered


def _unanswered(event: Mapping[str, object], b: Budget, head: str, record: str) -> str:
    """Return the refusal of a dispatch whose budget the user has not answered."""
    return (
        f"{head}: the user has not answered it in the lead session that recorded "
        "it. Tell them the figure and wait for their answer before dispatching"
        + (
            " — or, the user gone from that session, record it again from this "
            f"one with {record}."
            if b.get("session") != event.get("session_id")
            else "."
        )
    )


def gate_dispatch(event: Mapping[str, object], entry: RegistryEntry) -> int:
    """Hold an `exec-` dispatch to the route's budget; give an allowed one its ETA.

    Held until the route's budget is recorded and the user answered it in the lead
    session that recorded it — at S, recorded is enough — and once the route's spend
    since passes 125% of it (execution.md, F74); an allowed one gets its ETA (F83). One
    budget a route: a hand-over to a new lead session keeps it (F74).

    Returns:
        The hook's exit code, always 0.
    """
    path = pathlib.Path(entry["marker"])
    marker = as_dict(parse_json(path.read_text())) or {}
    route = route_args(marker)
    phase = route.phase
    found = budgets(entry["planning_dir"], marker, phase)
    record = f'`python3 {SCRIPT} --budget "<route>" --estimate <M>`'
    if not found:
        return deny(
            f"phase {phase} has no budget. Price the route's work left per costs.md "
            "(the lead, every review and agent of the stages left, the task groups at "
            "the group median, a seven-sins review at L's phase end), record it with "
            f"{record}, tell the user the figure and wait for their answer — at S, "
            "tell them and go on (execution.md)."
        )
    b = found[-1]
    name = str(_tool_input(event).get("name") or "")
    if _phases(name) - {str(phase)}:
        # spend() leaves another phase's agents out, so one dispatched here would run
        # uncounted
        return deny(
            f"{name} names another phase than this route's phase {phase}: activate "
            "that phase (`--activate --phase <P>`) and record its budget first (F74)."
        )
    paths = leads(event, path)
    head = f"budget '{b['label']}' ({b['estimate']:g}M, recorded {b['at']})"
    if held := base_hold(entry["planning_dir"], route, found):
        return deny(f"{head}: {held}")
    if not (b.get("answered") or marker.get("rung") == "S"):
        answered = _answer(event, b)
        if not answered:
            return deny(_unanswered(event, b, head, record))
        if answered != b["at"]:
            # a user's answer is kept with the record, so a hand-over to a new lead
            # session asks nothing again; a headless session's pass is its own and is
            # never kept
            save_budget(entry["planning_dir"], marker, {**b, "answered": answered})
    used = spend(paths, b["at"], phase)
    if used > b["estimate"] * 1e6 * SLACK:
        return deny(
            f"{head}: {used / 1e6:.1f}M spent since — more than 25% over. Record the "
            f"remaining work's figure with {record}, tell the user what ran over and "
            "why, and wait for their answer (F74)."
        )
    emit("PreToolUse", eta(paths, name, entry["planning_dir"]))
    return 0


def lane_of(name: str) -> str | None:
    """Return the plan id an agent's name names, else None."""
    found = PLAN_ID.search(name)
    return found[0] if found else None


def gate_minutes(planning_dir: StrPath, lane: str) -> tuple[float, float] | None:
    """Return the minutes of the lane's plan's gates, or None.

    As (a group runs, the lead or CI runs).
    """
    import plan_lint

    plans = pathlib.Path(planning_dir) / "plans"
    plan = next(iter([*sorted(plans.glob(f"{lane}-*.md")), plans / f"{lane}.md"]))
    found = plan.exists() and plan_lint.gates(plan.read_text(errors="replace"))
    if not found:
        return None
    own = sum(m or 0 for _, m, runs in found if runs == "group")
    return own, sum(m or 0 for _, m, runs in found if runs != "group")


def eta(
    paths: Iterable[pathlib.Path], name: str, planning_dir: StrPath | None = None
) -> str:
    """Return the `exec-` dispatch `name`'s ETA (F83).

    The median minutes of the route's finished agents of its kind — integrators
    (`exec-wave*`) or task groups — its lane's first, and the minutes of the gates its
    lane's plan names.
    """
    return eta_work(paths, name) + gates_line(planning_dir, lane_of(name))


def gates_line(planning_dir: StrPath | None, lane: str | None) -> str:
    """Return the ETA's note of the minutes of the lane's plan's gates, "" without."""
    found = checked(gate_minutes, planning_dir, lane) if planning_dir and lane else None
    if not found:
        return ""
    own, other = found
    return (
        f" Its plan's gates: {own:g} min in the group that runs them, {other:g} min "
        "the lead's or CI's that the lane waits on — add them to that group's figure; "
        "the median alone said 77 min for a group that ran 341 (F83)."
    )


def eta_work(paths: Iterable[pathlib.Path], name: str) -> str:
    """Return the ETA's median minutes of the route's finished agents of its kind."""
    wave = name.startswith(EXEC + "wave")
    kind = "integrator" if wave else "task group"
    spans = [
        (lane_of(agent), minutes)
        for agent, minutes in finished_spans(
            paths,
            lambda a: a.startswith(EXEC) and a.startswith(EXEC + "wave") == wave,
        )
    ]
    route = [m for _, m in spans]
    if not route:
        return (
            f"ETA {name}: none yet — no {kind} of this route has finished. Tell the "
            "user so with this dispatch (F83)."
        )
    lane = lane_of(name)
    mine = [m for own, m in spans if lane and own == lane]
    n = len(mine or route)
    finished = f"{n} finished {kind}{'' if n == 1 else 's'}"
    source = (
        f"lane {lane}'s {finished} (the route's {len(route)}: "
        f"{statistics.median(route):.0f} min)"
        if mine
        else f"the route's {finished}"
    )
    return (
        f"ETA {name}: about {statistics.median(mine or route):.0f} min, the median of "
        f"{source}. Tell the user with this dispatch: this ETA and, for a lane, this × "
        "its groups left (F83)."
    )
