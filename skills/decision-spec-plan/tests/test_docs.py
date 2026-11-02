"""The plugin's own files agree with each other: the agent tiers' role rules, the hook wiring,
the files SKILL.md names, the failure-mode rows cited as evidence, every script's --help and
SKILL.md's size."""

import ast
import json
import re
import unittest

import support
from support import PLUGIN, SCRIPTS


def role_rules(path):
    """An agent file from its `Your final message` line to the end."""
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("Your final message")), None
    )
    return "" if start is None else "\n".join(lines[start:]).rstrip("\n")


class PluginFiles(support.Sandbox):
    no_hooks = False

    def test_mechanical_tier_carries_the_deep_tiers_rules(self):
        # a lane moved to the mechanical tier once ran with no one-group limit, context stop,
        # rulings, no-progress or heavy-run rule
        deep = role_rules(PLUGIN / "agents/dsp-deep.md")
        mech = role_rules(PLUGIN / "agents/dsp-mechanical.md")
        self.ok(
            "dsp-mechanical carries dsp-deep's role rules", deep != "" and deep == mech
        )

    def test_wiring(self):
        # its hooks run this plugin's scripts on every event the route needs, and a dispatch names
        # the agent as the plugin qualifies it (a bare `dsp-deep` resolves to no agent)
        manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
        self.ok(
            "plugin.json names the plugin decision-spec-plan",
            manifest.get("name") == "decision-spec-plan",
        )
        hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
        reg = sorted(
            f"{event} {entry.get('matcher') or ''} {h['command']}"
            for event, entries in hooks.items()
            for entry in entries
            for h in entry["hooks"]
        )
        route = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook'
        want = [
            f"PostToolUse * {route}",
            f"PreToolUse Agent|Bash|Write|Edit|MultiEdit|NotebookEdit {route}",
            'PreToolUse Bash python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push_guard.py"',
            f"SessionStart compact|resume {route}",
            f"SubagentStop  {route}",
            f"TeammateIdle  {route}",
            f"UserPromptSubmit  {route}",
        ]
        self.ok(
            "hooks.json registers route_state.py and push_guard.py on the route's 7 hooks",
            reg == want,
            "\n".join(reg),
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

    def test_named_files_and_cited_rows_exist(self):
        # SKILL.md's pointer to the ask format once named a file the skill never shipped
        skill = (PLUGIN / "SKILL.md").read_text(encoding="utf-8")
        names = sorted(set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", skill)))
        shipped = {p.name for p in PLUGIN.rglob("*")}
        gone = [n for n in names if n.rsplit("/", 1)[-1] not in shipped]
        self.ok("every file SKILL.md names exists", not gone, " ".join(gone))
        # ...and every failure-mode row a file cites as a rule's evidence exists
        modes = PLUGIN / "references/failure-modes.md"
        rows = set(re.findall(r"^\| (F[0-9]+) ", modes.read_text(), re.MULTILINE))
        sources = [PLUGIN / "SKILL.md"]
        for d in ("references", "agents", "scripts"):
            sources += [
                p
                for p in (PLUGIN / d).rglob("*")
                if p.is_file() and p.suffix in (".md", ".py") and p.name != modes.name
            ]
        cited = set()
        for p in sources:
            cited |= set(re.findall(r"\bF[0-9]+\b", p.read_text(errors="replace")))
        gone = sorted(cited - rows)
        self.ok(
            "every failure-mode row a file cites exists",
            bool(rows) and not gone,
            " ".join(gone),
        )

    def test_help_is_the_whole_interface(self):
        # shown only its docstring's first line, a lead read ~20k characters of the scripts'
        # source to learn their options (F84)
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

    def test_skill_fits_a_compaction(self):
        # a compaction re-attaches SKILL.md cut at 20,000 characters (failure-modes F61)
        n = len((PLUGIN / "SKILL.md").read_text(encoding="utf-8"))
        self.ok(f"SKILL.md is {n} characters (limit 19000)", n <= 19000)


if __name__ == "__main__":
    unittest.main()
