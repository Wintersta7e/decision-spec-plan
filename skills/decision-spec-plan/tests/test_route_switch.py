# SPDX-License-Identifier: MIT
"""The monitor switch: `DSP_MONITOR`, its shell predicate and its in-process test."""

import ast

import support
from support import SCRIPTS

# each value of DSP_MONITOR (None: unset) and whether it turns the monitor on
CASES: dict[str | None, bool] = {
    "1": True,
    None: False,
    "": False,
    "0": False,
    "true": False,
    " 1": False,
}


class Switch(support.Sandbox):
    """`dsp_route/switch.py`, read as source, imported and run as the hooks run it."""

    def test_switch_module(self) -> None:
        """It imports only os; exactly "1" is on, in Python and in the shell."""
        tree = ast.parse((SCRIPTS / "dsp_route/switch.py").read_text())
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                found.add(node.module or "")
        self.ok(f"switch.py imports only os ({len(found)} modules)", found == {"os"})

        from dsp_route import switch  # the hook imports it lazily (TID253)

        wrong = [
            v
            for v, want in CASES.items()
            if switch.on({} if v is None else {switch.NAME: v}) != want
        ]
        self.ok(f"on() over {len(CASES)} values", not wrong, wrong)

        shell_wrong: list[str | None] = []
        for v, want in CASES.items():
            r = self.run_(
                ["sh", "-c", switch.GUARD],
                env={} if v is None else {switch.NAME: v},
                unset=[switch.NAME] if v is None else [],
            )
            if (r.code == 0) != want:
                shell_wrong.append(v)
        self.ok(f"GUARD over {len(CASES)} values", not shell_wrong, shell_wrong)
