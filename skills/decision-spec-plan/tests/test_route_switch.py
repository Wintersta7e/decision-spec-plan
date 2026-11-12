# SPDX-License-Identifier: MIT
"""The monitor switch: `DSP_MONITOR`, its shell predicate and its in-process test."""

import ast

import support
from support import PY, RS, SCRIPTS, ev

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


MON = {"DSP_MONITOR": "1"}
COLD = ("dsp_route.switch", "dsp_route.record")


class ColdPaths(support.Route):
    """The switch on a session with no route, and what each cold path imports."""

    def test_route_sessions_only(self) -> None:
        """A session with no registry entry records nothing, switch on."""
        events = self.HOME / ".claude/dsp-routes/events"
        self.rm(events)  # the routed import case records into it
        codes = [
            self.py(RS, "--hook", input=ev(name, "s7", extra) + "\n", env=MON).code
            for name, extra in (("PostToolUse", '"tool_name":"Read"'), ("Stop", ""))
        ]
        self.ok(
            f"{len(codes)} events of s7: exit 0, no events path",
            codes == [0, 0] and not events.exists(),
            codes,
        )

    def imported(self, session: str, env: dict[str, str]) -> list[str]:
        """The dsp_route modules a PostToolUse of session imports."""
        r = self.run_(
            [PY, "-X", "importtime", RS, "--hook"],
            input=ev("PostToolUse", session, '"tool_name":"Read"') + "\n",
            env=env,
            merge=True,
        )
        names = (line.rsplit("|", 1)[-1].strip() for line in r.out.splitlines())
        return [n for n in names if n.startswith("dsp_route.")]

    def test_no_import_on_cold_paths(self) -> None:
        """No route imports neither module; a routed call, switch off, no recorder."""
        for env, label in ((MON, "on"), ({}, "off")):
            mods = self.imported("s7", env)
            self.ok(
                f"no route, switch {label}: {len(mods)} dsp_route modules, none cold",
                mods and not set(mods) & set(COLD),
                mods,
            )
        off = self.imported("s1", {})
        self.ok(
            f"routed, switch off: {len(off)} dsp_route modules, no recorder",
            off and "dsp_route.record" not in off,
            off,
        )
        on = self.imported("s1", MON)
        self.ok(
            f"routed, switch on: {len(on)} dsp_route modules, the recorder among them",
            set(COLD) <= set(on),
            on,
        )
