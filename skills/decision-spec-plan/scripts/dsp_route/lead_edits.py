# SPDX-License-Identifier: MIT
"""The lead's own edits to the route's repository once its budget is recorded (F68)."""

import json
import pathlib
from collections.abc import Mapping

from .common import (
    REGISTRY,
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
FIRST, EVERY = 2, 10


def repo_edit(event: Mapping[str, object], route: RouteArgs) -> bool:
    """Return whether the edited file is one of the route's repository's.

    Of it or of a worktree of it, outside the planning dir, not ignored, with no rebase
    or merge in progress there.
    """
    inp = as_dict(event.get("tool_input")) or {}
    raw = str(inp.get("file_path") or inp.get("notebook_path") or "")
    if not raw:
        return False
    path = (pathlib.Path(str(event.get("cwd") or ".")) / raw).resolve()
    if path.is_relative_to(pathlib.Path(route.planning_dir)):
        return False
    where = ("rev-parse", "--path-format=absolute", "--git-common-dir", "--git-dir")
    rc, out = git(path.parent, *where)
    _, own = git(route.repo or route.planning_dir, *where[:3])
    if rc or not own or out.splitlines()[0] != own:
        return False
    gitdir = pathlib.Path(out.splitlines()[-1])
    if any((gitdir / n).exists() for n in IN_PROGRESS):
        return False
    return git(path.parent, "check-ignore", "-q", str(path))[0] != 0


def lead_edits(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> str | None:
    """Return the nudge at the lead's FIRST edit of the repository since the budget.

    The phase's last budget; and every EVERY edits after it; else None.
    """
    marker = load_json(pathlib.Path(entry["marker"]))
    route = route_args(marker)
    found = budgets(route.planning_dir, marker, route.phase)
    if not found or not repo_edit(event, route):
        return None
    b = found[-1]
    tally_path = REGISTRY / f"{session}.edits"
    tally = load_json(tally_path)
    seen = tally.get("n", 0)
    n = (seen if isinstance(seen, int) else 0) + 1 if tally.get("at") == b["at"] else 1
    _ = tally_path.write_text(json.dumps({"at": b["at"], "n": n}))
    if n < FIRST or (n - FIRST) % EVERY:
        return None
    return (
        f"route_state.py (hook): you edited {n} files of the repository yourself since "
        f"this phase's budget ({b.get('label')}). Execution is a fresh group's, never "
        "yours: a fix, a post-merge bug, a real-data run or an investigation gets an "
        "`exec-` group with its own checkpoint (execution.md). Edits while a rebase or "
        "merge is in progress do not count. Why: after its last lane returned, one "
        "lead made 126 edits itself and spent 30.4M of its 45.4M there (F68)."
    )
