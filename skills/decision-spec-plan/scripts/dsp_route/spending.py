# SPDX-License-Identifier: MIT
"""A route's spend against its budget, priced by usage_report.py.

Below the holds and `--budget` that both read it. Not in transcript.py: usage_report.py
imports that module, so the pricing would import it back.
"""

import pathlib
import re
from collections.abc import Iterable

# The phase an agent's name names (`harvest-code-p9`, `exec-p9-01-a`, `dec-p9-D1`): that
# phase's work, not another's budget's.
PHASE_OF = re.compile(r"(?<![A-Za-z0-9])p(\d+)(?=-|$)")


def phases(name: str) -> set[str]:
    """Return the phases an agent's name names."""
    return {m[1] for m in PHASE_OF.finditer(name)}


def spend(paths: Iterable[pathlib.Path], since: str, phase: str) -> float:
    """Return the units these leads, their agents and hook sessions spent since `since`.

    The route's budget prices the lead and every review and agent (F74) — but a lead's
    prompt written again after it sat idle past the cache's life: that is the wait for
    the user's answer, and one such rewrite after a 3 h wait tipped a wave over (F93).
    An agent whose name names another phase (`harvest-code-p9`, `exec-p9-01-a`) is that
    phase's: another phase's harvest and decision round in the same lead session made 8
    of 20 over-budget holds false (F74). A hook session counts once: the leads' searches
    overlap when one ran outside the repository or in a worktree.
    """
    import usage_report

    total, seen = 0.0, set[pathlib.Path]()
    for path in paths:
        lead, agents, sdk = usage_report.route_cost(path, since, seen=seen)
        total += lead["units"] - lead["idle"]
        total += sum(a["units"] for a in agents if phases(a["name"]) <= {str(phase)})
        total += sum(s["units"] for s in sdk)
    return total
