# SPDX-License-Identifier: MIT
"""The monitor switch: `DSP_MONITOR`, its shell predicate and its in-process test."""

import ast
import hashlib
import json
import os
import re
from pathlib import Path
from typing import NamedTuple, Required, TypedDict, cast

import support
from support import PLUGIN, PY, RS, SCRIPTS, ev

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


# the report's time stamps: with a year in its first line, without in a delta's header
STAMP = re.compile(r"(\d{4}-)?\d{2}-\d{2} \d{2}:\d{2}")
# the hook's claim file of a throttle window, named by the window's number
CHECKED = re.compile(r"(s1\.)\d+(\.checked)$")
# equal commit dates in every build, so the repository's SHAs are equal too
DATES = {
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}
# the kind of line each payload of sequence() records, in order
EXPECTED = [
    "session",
    "post",
    "prompt",
    "pre",
    "dispatch",
    "pre",
    "stop",
    "idle",
    "start",
    "failed",
    "compact",
    "notify",
    "turn-end",
    "api-error",
    "session-end",
]
EVENTS = "home/.claude/dsp-routes/events"


class _Command(TypedDict):
    """One command of a hooks.json entry."""

    command: str


class _Registration(TypedDict, total=False):
    """One hooks.json entry: an optional matcher and its commands."""

    matcher: str
    hooks: Required[list[_Command]]


# a registration: its event, its matcher (None: none) and its command
Entry = tuple[str, str | None, str]
# a hook run: payload index, event, matcher and command
Key = tuple[int, str, str, str]


def hooks_file() -> dict[str, list[_Registration]]:
    """The plugin's hooks/hooks.json, by event."""
    data = cast(
        "dict[str, object]", json.loads((PLUGIN / "hooks/hooks.json").read_text())
    )
    return cast("dict[str, list[_Registration]]", data["hooks"])


def guarded(event: str) -> bool:
    """Whether event's registrations are the recording-only ones the switch guards.

    Told by the event, not by the command: an entry that lost its guard is still one.
    """
    from dsp_route import hook  # imported lazily by route_state.py (TID253)

    return event in hook.RECORD_ONLY


def sequence(cwd: str) -> list[dict[str, object]]:
    """One payload per registration, as s1's lead's hooks receive them in cwd."""
    a1 = {"agent_id": "a1", "agent_type": "general-purpose"}

    def lead(hook: str, **fields: object) -> dict[str, object]:
        return {"session_id": "s1", "hook_event_name": hook, "cwd": cwd, **fields}

    return [
        lead("SessionStart", source="compact"),
        lead("PostToolUse", tool_name="Read", tool_use_id="r1", duration_ms=3),
        lead("UserPromptSubmit", prompt="go on"),
        lead(
            "PreToolUse",
            tool_name="Bash",
            tool_use_id="b1",
            tool_input={"command": "git status", "description": "status"},
        ),
        # no budget is recorded, so the dispatch is held
        lead(
            "PreToolUse",
            tool_name="Agent",
            tool_use_id="d1",
            tool_input={
                "name": "exec-p1-01-a",
                "description": "lane",
                "subagent_type": "decision-spec-plan:dsp-deep",
            },
        ),
        # a synthetic MCP tool: only the `^mcp__.*create_note$` entry matches it
        lead(
            "PreToolUse",
            tool_name="mcp__notes__create_note",
            tool_use_id="n1",
            tool_input={},
        ),
        lead("SubagentStop", **a1),
        lead("TeammateIdle", agent_id="a1", teammate_name="helper", team_name="t"),
        lead("SubagentStart", **a1),
        lead(
            "PostToolUseFailure",
            tool_name="Agent",
            tool_use_id="d2",
            tool_input={"name": "bad"},
            error="boom",
            is_interrupt=False,
            duration_ms=7,
        ),
        lead("PostCompact", trigger="auto"),
        lead("Notification", notification_type="idle_prompt", message="m"),
        lead("Stop"),
        lead("StopFailure", error="rate_limit"),
        lead("SessionEnd", reason="clear"),
    ]


class Ran(NamedTuple):
    """What a run of the sequence did: each hook's output and the files it changed."""

    outputs: dict[Key, tuple[str, int]]
    created: set[str]
    modified: set[str]
    spawns: int
    scanned: int


def existing(outputs: dict[Key, tuple[str, int]]) -> dict[Key, tuple[str, int]]:
    """The outputs of the registrations the switch does not guard."""
    return {k: v for k, v in outputs.items() if not guarded(k[1])}


def loud(outputs: dict[Key, tuple[str, int]]) -> list[Key]:
    """The guarded registrations' runs that printed something or did not exit 0."""
    return [k for k, v in outputs.items() if guarded(k[1]) and v != ("", 0)]


class OffIsToday(support.Sandbox):
    """hooks.json fed one payload per registration, each entry run as `sh -c`."""

    @classmethod
    def _build(cls, root: Path) -> Path:
        """Root rebuilt: HOME, repository R with planning dir R/.plan, s1's route; R."""
        cls.rm(root)
        home = root / "home"
        home.mkdir(parents=True)
        repo = root / "repo"
        _ = cls.git("init", "-q", "-b", "main", repo)
        _ = cls.git("-C", repo, "commit", "-q", "--allow-empty", "-m", "one", env=DATES)
        for d in ("lanes", "plans", "decisions/phase1", "spec"):
            (repo / ".plan" / d).mkdir(parents=True)
        r = cls.py(
            RS,
            repo / ".plan",
            "--phase",
            "1",
            "--repo",
            repo,
            "--sections",
            "1-",
            "--activate",
            session="s1",
            env={"HOME": str(home)},
            merge=True,
        )
        if r.code != 0:
            msg = f"--activate failed: {r.out}"
            raise AssertionError(msg)
        return repo

    @staticmethod
    def _entries(
        hooks: dict[str, list[_Registration]], *, drop_guarded: bool
    ) -> list[Entry]:
        """Hooks' registrations, without the guarded ones with drop_guarded."""
        return [
            (event, e.get("matcher"), h["command"])
            for event, regs in hooks.items()
            for e in regs
            for h in e["hooks"]
            if not (drop_guarded and guarded(event))
        ]

    @staticmethod
    def _snap(root: Path) -> dict[str, tuple[int, str]]:
        """Each path under root's HOME and R: mtime and SHA-1 (a directory: none)."""
        out: dict[str, tuple[int, str]] = {}
        for top in (root / "home", root / "repo"):
            for p in (top, *top.rglob("*")):
                rel = CHECKED.sub(r"\1<w>\2", str(p.relative_to(root)))
                if p.is_file():
                    digest = hashlib.sha1(p.read_bytes(), usedforsecurity=False)
                    out[rel] = (p.stat().st_mtime_ns, digest.hexdigest())
                else:
                    out[rel] = (0, "dir")
        return out

    def _run(
        self, root: Path, entries: list[Entry], env: dict[str, str], run: str
    ) -> Ran:
        """The sequence fed to entries in a fresh build at root, with env."""
        repo = self._build(root)
        shim = self.T / "shim" / run
        log = self.T / "shim" / f"{run}.log"
        self.rm(shim, log)
        self.chmod_x(
            self.write(
                shim / "python3",
                f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{log}'\nexec '{PY}' \"$@\"\n",
            )
        )
        full = {
            "HOME": str(root / "home"),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "PATH": f"{shim}{os.pathsep}{self.env['PATH']}",
            **env,
        }
        before = self._snap(root)
        outputs: dict[Key, tuple[str, int]] = {}
        hit: set[int] = set()
        for i, payload in enumerate(sequence(str(repo))):
            subject = str(payload.get("tool_name", payload.get("source", "")))
            for n, (event, matcher, command) in enumerate(entries):
                if event != payload["hook_event_name"] or (
                    matcher and matcher != "*" and not re.fullmatch(matcher, subject)
                ):
                    continue
                hit.add(n)
                r = self.run_(
                    ["sh", "-c", command],
                    input=json.dumps(payload),
                    env=full,
                    timeout=10,
                )
                outputs[i, event, matcher or "", command] = (
                    STAMP.sub("<now>", r.out),
                    r.code,
                )
        self.ok(
            f"{run}: {len(hit)} of {len(entries)} entries got a payload",
            len(hit) == len(entries),
        )
        after = self._snap(root)
        return Ran(
            outputs,
            set(after) - set(before),
            {p for p, v in before.items() if after.get(p) != v},
            len(log.read_text().splitlines()) if log.exists() else 0,
            len(after),
        )

    def test_monitor_off_is_today(self) -> None:
        """Switch unset, "0" or "": each hook acts as it does with no guarded entry."""
        from dsp_route import switch  # the hook imports it lazily (TID253)

        box, hooks = self.T / "box", hooks_file()
        a = self._run(box, self._entries(hooks, drop_guarded=True), {}, "A")
        every = self._entries(hooks, drop_guarded=False)
        offs: list[tuple[str, dict[str, str]]] = [
            ("B", {}),
            ("B'", {switch.NAME: "0"}),
            ("B''", {switch.NAME: ""}),
        ]
        bs = {
            label: self._run(box, every, env, f"B{n}")
            for n, (label, env) in enumerate(offs)
        }
        differ = {
            label: [
                part
                for part, x, y in (
                    ("outputs", existing(b.outputs), a.outputs),
                    ("created", b.created, a.created),
                    ("modified", b.modified, a.modified),
                    ("spawns", b.spawns, a.spawns),
                    ("guarded output", bool(loud(b.outputs)), False),
                )
                if x != y
            ]
            for label, b in bs.items()
        }
        spawns = " ".join(f"{k}={v.spawns}" for k, v in {"A": a, **bs}.items())
        self.ok(
            f"scanned {a.scanned} paths; created {len(a.created)}; "
            f"modified {len(a.modified)}; spawns {spawns}",
            a.scanned > 0 and not any(differ.values()),
            differ,
        )

    def test_monitor_on_is_observed_and_silent(self) -> None:
        """Switch on: a line per payload, the same outputs, the guarded ones silent."""
        box, hooks = self.T / "box", hooks_file()
        a = self._run(box, self._entries(hooks, drop_guarded=True), {}, "A")
        every = self._entries(hooks, drop_guarded=False)
        c = self._run(box, every, MON, "C")
        log = box / EVENTS / "s1.jsonl"
        text = log.read_text() if log.exists() else ""
        lines = [cast("dict[str, object]", json.loads(x)) for x in text.splitlines()]
        kinds = [x.get("ev") for x in lines]
        self.ok(f"spawns A={a.spawns} C={c.spawns}", c.spawns > a.spawns)
        self.ok(f"{len(lines)} event lines, one per payload", kinds == EXPECTED, kinds)
        mcp = [x.get("ev") for x in lines if x.get("tool") == "mcp__notes__create_note"]
        self.ok("the MCP payload's line is a pre", mcp == ["pre"], mcp)
        self.ok(
            "the existing entries print what they print with tracking off",
            existing(c.outputs) == a.outputs,
        )
        self.ok(
            "tracking on creates only the event log",
            c.created - a.created == {EVENTS, f"{EVENTS}/s1.jsonl", f"{EVENTS}/.swept"},
            sorted(c.created - a.created),
        )
        missing = {**MON, "CLAUDE_PLUGIN_ROOT": str(self.T / "missing")}
        gone = self._run(box, every, missing, "C-missing")
        for label, ran in (("on", c), ("on, plugin root missing", gone)):
            self.ok(
                f"{label}: the guarded entries print nothing and exit 0",
                not loud(ran.outputs),
                loud(ran.outputs),
            )
