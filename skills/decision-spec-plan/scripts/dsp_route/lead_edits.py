# SPDX-License-Identifier: MIT
"""The lead's own edits to the route's repository once its budget is recorded (F68)."""

import json
import pathlib
from collections.abc import Mapping
from typing import NamedTuple, cast

from .common import (
    REGISTRY,
    Budget,
    RegistryEntry,
    RouteArgs,
    as_dict,
    budgets,
    git,
    load_json,
    route_args,
)

# A rebase, merge or cherry-pick in progress: a conflict the lead resolves itself is
# cheaper than a group's checkpoint.
IN_PROGRESS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")
# The files the lead may edit itself after a budget before the hold: a one-line fix is
# cheaper than a group; a third file is execution.
FREE = 2


class Edit(NamedTuple):
    """One counted edit: its file, whether in a linked worktree, and the tally."""

    path: pathlib.Path
    worktree: bool
    budget: Budget
    seen: list[str]
    tally: pathlib.Path


def repo_edit(
    event: Mapping[str, object], route: RouteArgs
) -> tuple[pathlib.Path, bool] | None:
    """Return the edited file and whether it is in a linked worktree, else None.

    A file of the route's repository or of a worktree of it, outside the planning dir,
    not ignored, with no rebase or merge in progress there.
    """
    inp = as_dict(event.get("tool_input")) or {}
    raw = str(inp.get("file_path") or inp.get("notebook_path") or "")
    if not raw:
        return None
    path = (pathlib.Path(str(event.get("cwd") or ".")) / raw).resolve()
    if path.is_relative_to(pathlib.Path(route.planning_dir)):
        return None
    where = ("rev-parse", "--path-format=absolute", "--git-common-dir", "--git-dir")
    rc, out = git(path.parent, *where)
    _, own = git(route.repo or route.planning_dir, *where)
    if rc or not own or out.splitlines()[0] != own.splitlines()[0]:
        return None
    gitdir = pathlib.Path(out.splitlines()[-1])
    if any((gitdir / n).exists() for n in IN_PROGRESS):
        return None
    if git(path.parent, "check-ignore", "-q", str(path))[0] == 0:
        return None
    # another checkout than the route's own is a lane's worktree
    return path, str(gitdir) != own.splitlines()[-1]


def _counted(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> Edit | None:
    """Return the lead's counted edit; None before a budget or for one that is not."""
    marker = load_json(pathlib.Path(entry["marker"]))
    route = route_args(marker)
    found = budgets(route.planning_dir, marker, route.phase)
    if not found or not (hit := repo_edit(event, route)):
        return None
    b = found[-1]
    tally = REGISTRY / f"{session}.edits"
    t = load_json(tally)
    files = t.get("files") if t.get("at") == b["at"] else None
    seen = (
        [str(f) for f in cast("list[object]", files)] if isinstance(files, list) else []
    )
    return Edit(hit[0], hit[1], b, seen, tally)


def edit_hold(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> tuple[str, str] | None:
    """Return (decision, reason) on the lead's edit of a new repository file, or None.

    Past FREE files since the phase's last budget: deny in a lane's worktree, which its
    group owns; ask the user in the main checkout. A file already edited passes.
    """
    if not (e := _counted(event, session, entry)):
        return None
    if str(e.path) in e.seen or len(e.seen) < FREE:
        return None
    why = (
        f"you edited {len(e.seen)} files of the repository yourself since this phase's "
        f"budget ({e.budget.get('label')}). Execution is a fresh group's, never "
        "yours: a fix, a post-merge bug, a real-data run or an investigation gets an "
        "`exec-` group with its own checkpoint (execution.md). Edits while a rebase or "
        "merge is in progress do not count. Why: after its last lane returned, one "
        "lead made 126 edits itself and spent 30.4M of its 45.4M there (F68)."
    )
    if e.worktree:
        return (
            "deny",
            f"{e.path.name} is in a lane's worktree, which its group owns; {why}",
        )
    return "ask", why


def record_edit(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> None:
    """Add the file of a lead's edit that ran to the phase's tally."""
    if (e := _counted(event, session, entry)) and str(e.path) not in e.seen:
        files = [*e.seen, str(e.path)]
        _ = e.tally.write_text(json.dumps({"at": e.budget["at"], "files": files}))
