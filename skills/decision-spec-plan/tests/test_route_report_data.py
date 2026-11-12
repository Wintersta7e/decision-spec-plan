# SPDX-License-Identifier: MIT
"""The route report as data: the plan index's wave edges the report reads.

`scope_check.edges()` gives each plan's direct edges, the plans its `Depends on` cell
names and the waves an `all` cell waits for; `depends()` closes over them.
"""

import scope_check
import support

INDEX = """# Phase 1 plans

| Plan | Wave | Depends on |
|---|---|---|
| p1-01-a | 0 | — |
| p1-02-b | 1 | p1-01 |
| p1-03-c | 1 | p1-01, p1-02 |
| p1-04-d | 2 | all of wave 1 |
| p1-05-e | 3 | all |
| p1-06-f | — | all |
"""


class WaveEdges(support.Sandbox):
    """Named plans, named waves, every earlier wave, and a row with no wave."""

    def test_edges(self) -> None:
        """Each row's direct edges, and the closure depends() builds on them."""
        index = self.write(self.T / "plans/p1-00-index.md", INDEX)
        rows = scope_check.plan_table(str(index))
        got = scope_check.edges(rows)
        self.ok(
            f"edges of every row: {len(got)} rows",
            len(got) > 0
            and got
            == {
                "p1-01-a": (set(), set()),
                "p1-02-b": ({"p1-01-a"}, set()),
                "p1-03-c": ({"p1-01-a", "p1-02-b"}, set()),
                "p1-04-d": (set(), {1}),
                "p1-05-e": (set(), {0, 1, 2}),
                "p1-06-f": (set(), set()),
            },
            got,
        )
        # what depends() returned on this index before it was built on edges()
        reach = scope_check.depends(rows)
        self.ok(
            f"depends() unchanged: {len(reach)} rows",
            len(reach) > 0
            and reach
            == {
                "p1-01-a": set(),
                "p1-02-b": {"p1-01-a"},
                "p1-03-c": {"p1-01-a", "p1-02-b"},
                "p1-04-d": {"p1-01-a", "p1-02-b", "p1-03-c"},
                "p1-05-e": {"p1-01-a", "p1-02-b", "p1-03-c", "p1-04-d"},
                "p1-06-f": set(),
            },
            reach,
        )
