# SPDX-License-Identifier: MIT
"""The lines the hook puts into the lead's context beside the report.

The skill's files changed since the session read them (F78), the stage and what to
re-read, the budget, a prompt naming the route in a session that never loaded it, and
the answer tally (F89).
"""

import hashlib
import json
import pathlib
import re
from collections.abc import Mapping

from .common import (
    RETURNS,
    SKILL,
    SKILL_DIR,
    RegistryEntry,
    RouteArgs,
    StrPath,
    as_dict,
    as_list,
    budgets,
    parse_json,
    write_atomic,
)
from .transcript import skill_loaded

# answers taking the recommended option: past 9 of the last 10, the asks stopped
# informing anyone (F89)
TAKE_WINDOW, TAKE_RATE = 10, 9
# the route named in a prompt; "DSP" in capitals is signal processing, `dsp-deep` an
# agent type
NAMED = re.compile(r"\bdsp\b(?!-)|\bdecision-spec-plan\b")


def skill_changes(entry_path: pathlib.Path, entry: RegistryEntry) -> list[str]:
    """Return the skill's files changed since this session last read them; mark them.

    A file written since is changed only when its text is: an upgrade (`git archive |
    tar -x`) rewrites every file, and told every running lead to re-read all of them.
    """
    seen = entry.get("skill_seen", entry.get("activated", 0))
    files = {
        str(f.relative_to(SKILL_DIR)): f
        for f in [SKILL, *sorted((SKILL_DIR / "references").rglob("*.md"))]
    }
    held = as_dict(entry.get("skill_digests"))
    newer = [rel for rel, f in files.items() if f.stat().st_mtime > seen]
    if not newer and held is not None:
        return []
    digests = {
        rel: hashlib.sha256(f.read_bytes()).hexdigest()[:16] for rel, f in files.items()
    }
    # an entry from before the digests: the mtime alone decides, this once
    changed = [rel for rel in newer if held is None or held.get(rel) != digests[rel]]
    if newer:
        entry["skill_seen"] = max(files[rel].stat().st_mtime for rel in newer)
    entry["skill_digests"] = digests
    write_atomic(entry_path, json.dumps(entry) + "\n")
    return changed


def stage_docs(a: RouteArgs, rung: object) -> tuple[int, str]:
    """Return (stage, the lead documents it reads) by which phase files exist."""
    from .report import lane_checkpoints

    base, p = pathlib.Path(a.planning_dir), a.phase
    sins = ", references/sins/lead.md" if rung == "L" else ""
    dec = base / "decisions" / f"phase{p}"
    if any((base / "lanes").glob(f"p{p}-*")) or lane_checkpoints(base / "lanes", p):
        return 5, "references/execution.md" + sins
    if any(
        not f.name.startswith(f"p{p}-00") for f in (base / "plans").glob(f"p{p}-*.md")
    ):
        return 4, "references/templates.md §4, references/briefs/plan-brief.md"
    if any((base / "reconcile").glob(f"p{p}-*.md")):
        return 3, "references/briefs/reconcile-brief.md" + sins
    if (dec / "00-arbiter.md").exists():
        return 2, "references/templates.md §3, references/briefs/spec-brief.md"
    if dec.is_dir():
        return 1, "references/templates.md §1-2, references/briefs/decision-brief.md"
    return 0, "references/prompts.md §0"


def budget_line(
    planning_dir: StrPath, marker: Mapping[str, object], phase: str
) -> list[str]:
    """Return the report's `budget` line of the phase's latest budget, if any."""
    found = budgets(planning_dir, marker, phase)
    if not found:
        return []
    b = found[-1]
    line = f"budget     {b['label']} · {b['estimate']:g}M"
    if "groups" in b:
        line += f" · {b['groups']} exec- agents"
    return [f"{line} · since {b['at'][:16]}Z"]


def unloaded(event: Mapping[str, object]) -> str | None:
    """Return the line for a prompt naming the route where the skill never loaded."""
    prompt = str(event.get("prompt") or "")
    # an agent's return is not the user; a path (the skill's repository, `src/dsp/`)
    # names no route
    if prompt.lstrip().startswith(RETURNS) or not NAMED.search(
        re.sub(r"\S*/\S*", " ", prompt)
    ):
        return None
    if skill_loaded(str(event.get("transcript_path") or "")):
        return None
    return (
        "The user named the decision-spec-plan route: load it with the Skill tool "
        "before any other work — the rung announcement, its cost and `--activate` come "
        "first (one lead did 43 minutes of work before loading it). Route the task the "
        "user named, never the skill's nearest stage (`references/tasks.md`)."
    )


def _taken(asked: Mapping[str, object], answers: Mapping[str, object]) -> list[bool]:
    """Return whether each answer that had a recommended option took it."""
    taken: list[bool] = []
    for item in as_list(asked.get("questions")) or []:
        q = as_dict(item) or {}
        best = [
            o.get("label")
            for o in (as_dict(x) or {} for x in as_list(q.get("options")) or [])
            if "(Recommended)" in str(o.get("label"))
        ]
        question = q.get("question")
        if best and isinstance(question, str) and question in answers:
            taken.append(answers[question] in best)
    return taken


def took(event: Mapping[str, object], entry: RegistryEntry) -> str | None:
    """Tally whether each answer took the recommended option; flag a run of them.

    The tally goes into the marker. Past TAKE_RATE of the last TAKE_WINDOW, returns the
    line telling the lead its asks stopped informing.
    """
    asked = as_dict(event.get("tool_input")) or {}
    response = as_dict(event.get("tool_response")) or {}
    answers = as_dict(response.get("answers")) or {}
    path = pathlib.Path(entry["marker"])
    marker = as_dict(parse_json(path.read_text()))
    tally = as_list(marker.setdefault("asks", [])) if marker is not None else None
    if marker is None or tally is None:
        return None
    before = len(tally)
    tally += _taken(asked, answers)
    write_atomic(path, json.dumps(marker) + "\n")
    last = tally[-TAKE_WINDOW:]
    took_n = sum(bool(t) for t in last)
    if len(tally) == before or len(last) < TAKE_WINDOW or took_n < TAKE_RATE:
        return None
    return (
        f"The user took your recommendation in {took_n} of their last {TAKE_WINDOW} "
        "answers: an ask answered that way no longer tells you what they want. Ask "
        "only the calls you are unsure of, each with the strongest case against your "
        "recommendation and a `backlog` option where it adds scope; rule the rest as "
        "defaults they may overturn (F89)."
    )
