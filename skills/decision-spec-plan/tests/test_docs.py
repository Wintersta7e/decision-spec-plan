# SPDX-License-Identifier: MIT
"""The plugin's own files agree with each other.

The agent tiers' role rules, the hook wiring, the files SKILL.md names, the
failure-mode rows cited as evidence, every script's --help and SKILL.md's size.
"""

import ast
import json
import re
import unittest
from pathlib import Path
from typing import ClassVar, NotRequired, Required, TypedDict, cast

import support
from support import PLUGIN, SCRIPTS

SKILL_LIMIT = 19000  # characters of SKILL.md, under the 20,000 a compaction keeps
# the guarded events hooks.json runs in the background: none can block the session
ASYNC = {"SubagentStart", "PostToolUseFailure", "PostCompact", "Notification"}

# one command of a hooks.json entry; the functional form, as `async` is a keyword
_Hook = TypedDict(
    "_Hook", {"command": str, "async": NotRequired[bool], "shell": NotRequired[str]}
)


class _Entry(TypedDict, total=False):
    """One hooks.json entry: an optional matcher and its commands."""

    matcher: str
    hooks: Required[list[_Hook]]


class _HooksFile(TypedDict):
    """hooks/hooks.json: the entries of each event."""

    hooks: dict[str, list[_Entry]]


def role_rules(path: Path) -> str:
    """An agent file from its `Your final message` line to the end."""
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("Your final message")), None
    )
    return "" if start is None else "\n".join(lines[start:]).rstrip("\n")


class PluginFiles(support.Sandbox):
    """Checks of the plugin's shipped files against each other."""

    no_hooks: ClassVar[bool] = False

    def test_mechanical_tier_carries_the_deep_tiers_rules(self) -> None:
        """dsp-mechanical's role rules are dsp-deep's."""
        # a lane moved to the mechanical tier once ran with no one-group limit, context
        # stop, rulings, no-progress or heavy-run rule
        deep = role_rules(PLUGIN / "agents/dsp-deep.md")
        mech = role_rules(PLUGIN / "agents/dsp-mechanical.md")
        self.ok(
            "dsp-mechanical carries dsp-deep's role rules", deep != "" and deep == mech
        )

    def test_wiring(self) -> None:
        """The manifest's name, the hook registrations and the qualified agent names."""
        # its hooks run this plugin's scripts on every event the route needs, and a
        # dispatch names the agent as the plugin qualifies it (a bare `dsp-deep`
        # resolves to no agent)
        manifest = cast(
            "dict[str, object]",
            json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text()),
        )
        self.ok(
            "plugin.json names the plugin decision-spec-plan",
            manifest.get("name") == "decision-spec-plan",
        )
        hooks = cast(
            "_HooksFile", json.loads((PLUGIN / "hooks/hooks.json").read_text())
        )["hooks"]
        reg = sorted(
            f"{event} {entry.get('matcher') or ''} {h['command']}"
            for event, entries in hooks.items()
            for entry in entries
            for h in entry["hooks"]
        )
        from dsp_route import switch  # the hook imports switch lazily (TID253)

        route = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook'
        # a recording-only command: one `sh` test while the switch is off, and never a
        # failing exit, so a Stop is never blocked
        g = f"{switch.GUARD} && {route} || true"
        want = [
            f"Notification  {g}",
            f"PostCompact  {g}",
            f"PostToolUse * {route}",
            f"PostToolUseFailure Agent {g}",
            (
                "PreToolUse Agent|Bash|Write|Edit|MultiEdit|NotebookEdit|SendMessage "
                f"{route}"
            ),
            'PreToolUse Bash python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push_guard.py"',
            # an MCP tool's review note, held like `glab mr note` (F104); a matcher with
            # `^` or `$` is an unanchored regex, so both anchors are needed
            f"PreToolUse ^mcp__.*create_note$ {route}",
            f"SessionEnd  {g}",
            f"SessionStart compact|resume {route}",
            f"Stop  {g}",
            f"StopFailure  {g}",
            f"SubagentStart  {g}",
            f"SubagentStop  {route}",
            f"TeammateIdle  {route}",
            f"UserPromptSubmit  {route}",
        ]
        self.ok(
            "hooks.json registers route_state.py and push_guard.py on the route's "
            "hooks and the guarded recording hooks",
            reg == want,
            "\n".join(reg),
        )
        cmds = [
            (event, h)
            for event, entries in hooks.items()
            for e in entries
            for h in e["hooks"]
        ]
        timed = sorted(event for event, h in cmds if "async" in h)
        self.ok(
            f"async on {timed}, each true",
            sorted(ASYNC) == timed
            and all(h.get("async", True) is True for _, h in cmds),
        )
        self.ok("no command names a shell", not [h for _, h in cmds if "shell" in h])
        stray = [
            h["command"]
            for _, h in cmds
            if switch.GUARD in h["command"] and h["command"] != g
        ]
        self.ok("the guard opens only the guarded commands", not stray, stray)

        from dsp_route import hook  # imported lazily by route_state.py (TID253)

        guarded = {event for event, h in cmds if h["command"] == g}
        self.ok(
            f"the {len(guarded)} guarded events are hook.RECORD_ONLY",
            frozenset(guarded) == hook.RECORD_ONLY,
            sorted(guarded),
        )
        bare = re.compile(r'subagent_type: "dsp-|agentType: .dsp-')
        files = [PLUGIN / "SKILL.md", *sorted((PLUGIN / "references").rglob("*"))]
        hits = [
            f"{f}:{n}"
            for f in files
            if f.is_file()
            for n, line in enumerate(f.read_text(errors="replace").split("\n"), 1)
            if bare.search(line)
        ]
        self.ok(
            "every dispatch names decision-spec-plan:dsp-*", not hits, "\n".join(hits)
        )

    def test_named_files_and_cited_rows_exist(self) -> None:
        """Every file SKILL.md names and every failure-mode row a file cites exists."""
        # SKILL.md's pointer to the ask format once named a file the skill never
        # shipped
        skill = (PLUGIN / "SKILL.md").read_text(encoding="utf-8")
        found = cast("list[str]", re.findall(r"`([A-Za-z0-9_./-]+\.md)`", skill))
        names = sorted(set(found))
        shipped = {p.name for p in PLUGIN.rglob("*")}
        gone = [n for n in names if n.rsplit("/", 1)[-1] not in shipped]
        self.ok("every file SKILL.md names exists", not gone, " ".join(gone))
        # ...and every failure-mode row a file cites as a rule's evidence exists
        modes = PLUGIN / "references/failure-modes.md"
        rows = set(
            cast(
                "list[str]",
                re.findall(r"^\| (F[0-9]+) ", modes.read_text(), re.MULTILINE),
            )
        )
        sources = [PLUGIN / "SKILL.md"]
        for d in ("references", "agents", "scripts"):
            sources += [
                p
                for p in (PLUGIN / d).rglob("*")
                if p.is_file() and p.suffix in {".md", ".py"} and p.name != modes.name
            ]
        cited: set[str] = set()
        for p in sources:
            text = p.read_text(errors="replace")
            cited |= set(cast("list[str]", re.findall(r"\bF[0-9]+\b", text)))
        gone = sorted(cited - rows)
        self.ok(
            "every failure-mode row a file cites exists",
            bool(rows) and not gone,
            " ".join(gone),
        )

    def test_help_is_the_whole_interface(self) -> None:
        """Every script's --help prints its whole docstring."""
        # shown only its docstring's first line, a lead read ~20k characters of the
        # scripts' source to learn their options (F84)
        for s in (
            "route_state.py",
            "push_guard.py",
            "criteria_check.py",
            "plan_lint.py",
            "scope_check.py",
            "test_check.py",
            "usage_report.py",
            "apply_markers.py",
            "decision_check.py",
            "dsp_monitor.py",
        ):
            doc = ast.get_docstring(ast.parse((SCRIPTS / s).read_text())) or ""
            last = doc.strip().splitlines()[-1].strip()
            out = self.py(s, "--help", merge=True).out
            self.ok(
                f"{s} --help prints its whole docstring",
                support.grep(out, last, F=True),
                last,
            )
        self.ok(
            "route_state.py --help says what the budget hold does headless",
            support.grep(self.py("route_state.py", "--help").out, "claude -p", F=True),
        )
        crit = self.py("criteria_check.py", "--help").out
        self.ok(
            "criteria_check.py --help names the file that holds a section",
            support.grep(crit, "<NN>-<slug>.md", F=True),
        )
        self.ok(
            "criteria_check.py --help shows the --test-re default",
            support.grep(crit, "__tests__", F=True),
        )

    def test_readme_tells_what_the_hook_shows(self) -> None:
        """README says the hook shows the recorded budget, not a wave's spend."""
        readme = (PLUGIN.parents[1] / "README.md").read_text(encoding="utf-8")
        for gone in ("wave spend", "spend vs quota"):
            self.ok(f"README: no {gone!r}", gone not in readme)
        for said in (
            "route state changes, budget recorded",
            (
                "Route state and the recorded budget; a wave's dispatch held once its "
                "spend passes the budget;"
            ),
        ):
            self.ok(f"README says {said!r}", said in readme)

    def test_monitor_switch_is_documented(self) -> None:
        """README, INSTALL.md and --help name the switch as switch.NAME spells it."""
        from dsp_route import record, switch  # the hook imports them lazily (TID253)

        readme = (PLUGIN.parents[1] / "README.md").read_text(encoding="utf-8")
        events = "~/" + str(record.EVENTS.relative_to(Path.home()))
        for said in (switch.NAME, "POSIX hook shell", events, "opportunistic"):
            self.ok(f"README says {said!r}", said in readme)
        install = (PLUGIN.parents[1] / "INSTALL.md").read_text(encoding="utf-8")
        self.ok(f"INSTALL.md says {switch.NAME}", switch.NAME in install)
        hooks = cast(
            "_HooksFile", json.loads((PLUGIN / "hooks/hooks.json").read_text())
        )["hooks"]
        entries = [(event, e.get("matcher")) for event, es in hooks.items() for e in es]
        names = {switch.NAME} | {event for event, _ in entries}
        names |= {m for _, m in entries if m and m != "*"}
        out = self.py("route_state.py", "--help").out
        fails = sorted(n for n in names if n not in out)
        self.ok(
            f"--help names the switch and {len(entries)} registrations: "
            f"{len(fails)} fails",
            entries and not fails,
            fails,
        )

    def test_skill_fits_a_compaction(self) -> None:
        """SKILL.md stays under the size a compaction re-attaches."""
        # a compaction re-attaches SKILL.md cut at 20,000 characters (failure-modes F61)
        n = len((PLUGIN / "SKILL.md").read_text(encoding="utf-8"))
        self.ok(f"SKILL.md is {n} characters (limit {SKILL_LIMIT})", n <= SKILL_LIMIT)


if __name__ == "__main__":
    _ = unittest.main()
