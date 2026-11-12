# SPDX-License-Identifier: MIT
"""The route monitor: `dsp_monitor.py`, its page skeleton and the names it shares."""

import hashlib

import support
from dsp_route import common


class SharedNames(support.Sandbox):
    """The route slug and the agent-id name, owned by `common` for every reader."""

    def test_route_slug_and_id_name(self) -> None:
        """The slug is the marker's; the name drops the `a` and the hash suffix."""
        want = hashlib.sha1(b"/x/plan", usedforsecurity=False).hexdigest()[:10]
        self.ok("route slug", common.route_slug("/x/plan") == want)
        cases = {
            "aexec-p1-04-1-0123abcd": "exec-p1-04-1",
            "ab_c-12345678": "b_c",
            "lead": "lead",
        }
        for agent, name in cases.items():
            self.ok(f"id_name({agent})", common.id_name(agent) == name)
