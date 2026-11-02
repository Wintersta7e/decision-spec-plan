"""The lines the hook puts into the lead's context beside the report: the skill's files changed
since the session read them (F78), the stage and what to re-read, the budget, a prompt naming the
route in a session that never loaded it, and the answer tally (F101)."""

import json
import pathlib
import re

from .common import RETURNS, SKILL, SKILL_DIR
from .report import lane_checkpoints
from .transcript import skill_loaded

# answers taking the recommended option: past 9 of the last 10 the asks stopped informing (F101)
TAKE_WINDOW, TAKE_RATE = 10, 9
# the route named in a prompt; "DSP" in capitals is signal processing, `dsp-deep` an agent type
NAMED = re.compile(r"\bdsp\b(?!-)|\bdecision-spec-plan\b")


def skill_changes(entry_path, entry):
    """The skill's files written since this session last read them; marks them read."""
    seen = entry.get("skill_seen", entry.get("activated", 0))
    files = [SKILL, *sorted((SKILL_DIR / "references").rglob("*.md"))]
    changed = [f for f in files if f.stat().st_mtime > seen]
    if changed:
        entry["skill_seen"] = max(f.stat().st_mtime for f in changed)
        entry_path.write_text(json.dumps(entry) + "\n")
    return [str(f.relative_to(SKILL_DIR)) for f in changed]


def stage_docs(a, rung):
    """(stage, the lead documents it reads) going by which of the phase's files exist."""
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


def budget_line(marker, phase):
    budgets = [b for b in marker.get("budgets", []) if b.get("phase") == phase]
    if not budgets:
        return []
    b = budgets[-1]
    line = f"budget     {b['label']} · {b['estimate']:g}M · {b['groups']} exec- agents"
    return [f"{line} · since {b['at'][:16]}Z"]


def unloaded(event):
    """The line for a prompt naming the route in a session whose transcript never loaded it."""
    prompt = event.get("prompt") or ""
    # an agent's return is not the user; a path (the skill's repository, `src/dsp/`) names no route
    if prompt.lstrip().startswith(RETURNS) or not NAMED.search(
        re.sub(r"\S*/\S*", " ", prompt)
    ):
        return None
    if skill_loaded(event.get("transcript_path") or ""):
        return None
    return (
        "The user named the decision-spec-plan route: load it with the Skill tool before any "
        "other work — the rung announcement, its cost and `--activate` come first (one lead did "
        "43 minutes of work before loading it). Route the task the user named, never the "
        "skill's nearest stage (`references/tasks.md`)."
    )


def took(event, entry):
    """Tally into the marker whether each answer that had a recommended option took it; past
    TAKE_RATE of the last TAKE_WINDOW, the line telling the lead its asks stopped informing."""
    asked = event.get("tool_input") or {}
    answers = (event.get("tool_response") or {}).get("answers") or {}
    path = pathlib.Path(entry["marker"])
    marker = json.loads(path.read_text())
    tally = marker.setdefault("asks", [])
    before = len(tally)
    for q in asked.get("questions") or []:
        best = [
            o.get("label")
            for o in q.get("options") or []
            if "(Recommended)" in str(o.get("label"))
        ]
        if best and q.get("question") in answers:
            tally.append(answers[q["question"]] in best)
    path.write_text(json.dumps(marker) + "\n")
    last = tally[-TAKE_WINDOW:]
    if len(tally) == before or len(last) < TAKE_WINDOW or sum(last) < TAKE_RATE:
        return None
    return (
        f"The user took your recommendation in {sum(last)} of their last {TAKE_WINDOW} "
        "answers: an ask answered that way no longer tells you what they want. Ask only the "
        "calls you are unsure of, each with the strongest case against your recommendation "
        "and a `backlog` option where it adds scope; rule the rest as defaults they may "
        "overturn (F101)."
    )
