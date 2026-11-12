# SPDX-License-Identifier: MIT
"""`route_state.py --activate` and the hooks before and around it.

No route, a prompt naming the route before its skill loaded, a route agent dispatched
with none, and route settings given without --activate.
"""

import json
import re
import subprocess
import time
import unittest
from pathlib import Path
from typing import ClassVar, cast

import support
from support import PY, RS, SCRIPTS, ev, jstr

CHECKS = 2  # the version of the decision checks a new ledger entry is bound to
USAGE = 2  # route_state.py's exit on a usage error
MON = {"DSP_MONITOR": "1"}  # the monitor switch on
READ = '"tool_name":"Read"'


def route_agent(session: str, kind: str) -> str:
    """A PreToolUse event of session dispatching a route agent of kind."""
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Agent",'
        f'"tool_input":{{"subagent_type":"{kind}","name":"pride-r1"}}',
    )


class NoRouteThenActivate(support.Route):
    """The repository of support.Route with no route until the test activates one."""

    activate: ClassVar[bool] = False

    def asks(self, prompt: str, transcript: str) -> str:
        """A UserPromptSubmit event of prompt, its transcript the named file under T."""
        return ev(
            "UserPromptSubmit",
            "s1",
            f'"prompt":{jstr(prompt)},"transcript_path":"{self.T}/{transcript}"',
        )

    def test_no_route_active(self) -> None:
        """The hooks with no route, then --activate and the settings it alone takes."""
        r, p, t = self.R, self.P, self.T
        # no route active: everything passes, the hook is silent
        _ = self.guard(0, r, "git push origin main")
        _ = self.guard(0, r, "git --no-pager push origin main")
        _ = self.guard(0, r, "DSP_SKIP_PUSH_GUARD=1 git push origin main")
        _ = self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Agent"'))
        # ...but a route agent dispatched with no route means the skill never loaded:
        # F79 records it
        _ = self.hook(
            "deny:no active decision-spec-plan route.*Skill tool.*--activate --rung",
            route_agent("s1", "dsp-deep"),
        )
        _ = self.hook(
            "deny:no active decision-spec-plan route",
            route_agent("s1", "decision-spec-plan:dsp-mechanical"),
        )
        _ = self.hook("silent", route_agent("s1", "general-purpose"))
        _ = self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                '"agent_id":"a1","tool_name":"Agent",'
                '"tool_input":{"subagent_type":"dsp-deep"}',
            ),
        )
        # a prompt naming the route in a session that has not loaded it: the skill
        # first, before any work (one lead did 43 minutes of work after "use dsp" before
        # loading it)
        _ = self.write(
            t / "no-skill.jsonl",
            '{"type":"user","message":{"role":"user","content":"hi"}}\n',
        )
        _ = self.write(
            t / "skill.jsonl",
            '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"k1",'
            '"name":"Skill","input":{"skill":"decision-spec-plan"}}]}}\n',
        )
        _ = self.hook(
            "/decision-spec-plan[^.]*Skill tool[^.]*before any other/",
            self.asks("use dsp to find why the export drops rows", "no-skill.jsonl"),
        )
        _ = self.hook(
            "/Skill tool/",
            self.asks("run this through decision-spec-plan", "no-skill.jsonl"),
        )
        _ = self.hook(
            "silent",
            self.asks("use dsp to find why the export drops rows", "skill.jsonl"),
        )
        _ = self.write(
            t / "slash.jsonl",
            '{"type":"user","message":{"role":"user","content":[{"type":"text","text":'
            '"Base directory for this skill: /x/.claude/skills/decision-spec-plan\\n\\n'
            '# Decision"}]}}\n',
        )
        _ = self.hook(
            "silent", self.asks("now use dsp for the export bug", "slash.jsonl")
        )
        _ = self.hook(
            "silent",
            self.asks("tune the DSP filter in the audio path", "no-skill.jsonl"),
        )
        _ = self.hook(
            "silent", self.asks("how many dsp-deep agents ran?", "no-skill.jsonl")
        )
        # an agent's return, a path into the skill's own repository or a dsp source dir
        # is not the user naming it
        _ = self.hook(
            "silent",
            self.asks(
                "<task-notification>\n<result>3 bugs in "
                "skills/decision-spec-plan/scripts/"
                "route_state.py, use dsp</result>\n</task-notification>",
                "no-skill.jsonl",
            ),
        )
        _ = self.hook(
            "silent",
            self.asks(
                "fix the README typo in /work/decision-spec-plan", "no-skill.jsonl"
            ),
        )
        _ = self.hook(
            "silent",
            self.asks("the clipping bug is in src/dsp/biquad.c", "no-skill.jsonl"),
        )

        res = self.py(RS, p, "--phase", "1", "--repo", r, "--activate", cwd=r)
        self.ok(
            "activate without a session id: marker written, exit 1, says so",
            res.code == 1
            and self.MK(r).is_file()
            and support.grep(res.out, "CLAUDE_CODE_SESSION_ID is unset"),
            res.out,
        )
        _ = self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Read"'))

        res = self.py(
            RS,
            p,
            "--phase",
            "1",
            "--repo",
            r,
            "--sections",
            "1-",
            "--activate",
            session="s1",
        )
        self.ok(
            "activate registered s1, --main resolved to main",
            (self.HOME / ".claude/dsp-routes/s1.json").is_file()
            and support.grep_file(self.MK(r), '"--main", "main"'),
            res.out,
        )
        m = self.marker()
        self.ok(
            "a phase with no index yet is bound by the decision ledger, "
            "under today's checks",
            m.get("ledger", {}).get("1") is True
            and m["ledger"].get("1#checks") == CHECKS,
            json.dumps(m),
        )
        _ = self.hook("silent", route_agent("s1", "dsp-deep"))
        _ = self.hook(
            "deny:no active decision-spec-plan route", route_agent("s2", "dsp-deep")
        )
        # a route setting given without --activate was dropped in silence (live)
        for flag in ("--rung L", "--sins on", "--ci-harness e2e"):
            res = self.py(
                RS,
                p,
                "--phase",
                "1",
                "--repo",
                r,
                *flag.split(),
                session="s1",
                merge=True,
            )
            self.ok(
                f"{flag} without --activate is refused",
                res.code == USAGE and support.grep(res.out, "only with --activate"),
                res.out,
            )


RUN = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{16}$")
NEW_RUNS = 1000  # ids minted in one process, all distinct
PREVIOUS = 8  # the earlier routes an entry keeps
# a time stamp of the report (`%Y-%m-%d %H:%M`) or of a delta's header (`%m-%d %H:%M`)
STAMP = re.compile(r"(\d{4}-)?\d{2}-\d{2} \d{2}:\d{2}")

# 50 activations by one session, as `route_state.py --activate` runs them; the exits
WRITER = """import contextlib, json, os, sys
sys.path.insert(0, sys.argv[1])
import route_state
argv = [*sys.argv[2:4], "--phase", "1", "--repo", sys.argv[4], "--activate"]
codes = set()
with open(os.devnull, "w") as out, contextlib.redirect_stdout(out):
    for _ in range(50):
        sys.argv = list(argv)
        codes.add(route_state.main())
print(json.dumps(sorted(codes)))"""

# the marker read in a loop until the stop file exists: reads, misses, parse failures
READER = """import json, pathlib, sys
marker, stop = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
reads = misses = bad = 0
runs = set()
while not stop.exists():
    try:
        text = marker.read_text()
    except FileNotFoundError:
        misses += 1
        continue
    reads += 1
    try:
        runs.add(json.loads(text).get("run"))
    except ValueError:
        bad += 1
print(json.dumps({"reads": reads, "misses": misses, "bad": bad, "runs": list(runs)}))"""

# activate's read of the old marker with Path.read_text failing as argv[3] says on the
# marker's first reads: missing<N> (FileNotFoundError N times), enodata (another
# OSError once), brace (a torn "{" once); with argv[4], activate() itself on argv[4]
OLD_MARKER = """import contextlib, errno, io, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from dsp_route import activate, common
marker, mode = pathlib.Path(sys.argv[2]), sys.argv[3]
read = pathlib.Path.read_text
calls = 0
def read_text(self, *a, **k):
    global calls
    if self != marker:
        return read(self, *a, **k)
    calls += 1
    if mode == "brace" and calls == 1:
        return "{"
    if mode == "enodata" and calls == 1:
        raise OSError(errno.ENODATA, "x")
    if mode.startswith("missing") and calls <= int(mode[7:]):
        raise FileNotFoundError(marker)
    return read(self, *a, **k)
pathlib.Path.read_text = read_text
if len(sys.argv) > 4:
    a = common.parser().parse_args(
        [sys.argv[4], "--phase", "1", "--repo", sys.argv[5], "--activate"],
        namespace=common.RouteArgs(),
    )
    with contextlib.redirect_stdout(io.StringIO()):
        got = activate.activate(a, "main")
else:
    got = activate._old_marker(marker)
print(json.dumps({"calls": calls, "got": got}))"""


def upgraded(m: support.Marker) -> None:
    """The marker carrying `run_upgraded`."""
    m["run_upgraded"] = True


class RunIdentity(support.Route):
    """The run id `--activate` keeps in the marker, and the atomic marker writes."""

    activate: ClassVar[bool] = False

    def clear(self) -> None:
        """No marker (of any planning dir) and no registry entry: no route ever run."""
        self.rm(
            *(self.R / ".git").glob("dsp-route*.json"),
            *(self.HOME / ".claude/dsp-routes").glob("*.json"),
        )

    def shape_3c70cb6(self) -> support.Marker:
        """A marker as a version before run ids wrote it."""
        return {
            "args": [
                *(str(self.P), "--phase", "1", "--main", "main"),
                *("--repo", str(self.R), "--sections", "1-"),
            ],
            "planning_dir": str(self.P),
            "activated": time.time() - 60,
            "ledger": {"1": True, "1#checks": CHECKS},
        }

    def old_marker(self, mode: str, *activate: object) -> dict[str, object]:
        """OLD_MARKER's output in mode on R's marker (activating P with activate)."""
        r = self.run_(
            [PY, "-c", OLD_MARKER, SCRIPTS, self.MK(self.R), mode, *activate],
            env={"CLAUDE_CODE_SESSION_ID": "s1"},
        )
        return cast("dict[str, object]", json.loads(r.out))

    def test_new_marker_has_a_run(self) -> None:
        """A first activation mints a run id; ids do not repeat."""
        self.clear()
        _ = self.activate_route()
        m = self.marker()
        self.ok(
            "a new marker's run is <UTC time>-<16 hex>", RUN.match(m.get("run", ""))
        )
        self.ok("a new marker is no upgrade", "run_upgraded" not in m, m)
        from dsp_route import activate  # lazy, as the hook imports it (TID253)

        ids = {activate.new_run() for _ in range(NEW_RUNS)}
        self.ok(
            f"{NEW_RUNS} new run ids are {len(ids)} distinct ids", len(ids) == NEW_RUNS
        )

    def test_run_kept(self) -> None:
        """Another session, --sins on, another phase: one run, a new `activated`."""
        self.clear()
        _ = self.activate_route()
        before = self.marker()
        for label, extra, kw in (
            ("session s2", (), {"session": "s2"}),
            ("--sins on", ("--sins", "on"), {}),
            ("phase 2", (), {"phase": "2"}),
        ):
            _ = self.activate_route(*extra, **kw)
            m = self.marker()
            self.ok(
                f"{label} keeps the run, rewrites activated",
                m.get("run") == before.get("run")
                and m["activated"] != before["activated"],
                (before, m),
            )
            before = m
        self.edit_marker(upgraded)
        _ = self.activate_route()
        m = self.marker()
        self.ok(
            "run_upgraded is carried with the run",
            m.get("run") == before.get("run") and m.get("run_upgraded") is True,
            m,
        )

    def test_upgrade(self) -> None:
        """A marker without a run, or the legacy one, gets a run and run_upgraded."""
        self.clear()
        self.set_marker(self.shape_3c70cb6())
        _ = self.activate_route()
        m = self.marker()
        self.ok(
            "a run-less marker: a new run and run_upgraded",
            RUN.match(m.get("run", "")) and m.get("run_upgraded") is True,
            m,
        )
        _ = self.activate_route()
        again = self.marker()
        self.ok(
            "the next activation keeps both",
            again.get("run") == m.get("run") and again.get("run_upgraded") is True,
            again,
        )
        self.clear()
        legacy = self.R / ".git" / "dsp-route.json"
        _ = legacy.write_text(json.dumps(self.shape_3c70cb6()))
        _ = self.activate_route()
        m = self.marker()
        self.ok(
            "the legacy per-repository marker migrates with run_upgraded",
            RUN.match(m.get("run", ""))
            and m.get("run_upgraded") is True
            and not legacy.exists(),
            m,
        )

    def test_atomic_writes(self) -> None:
        """The marker and the entry are replaced, never torn, and leave no temp file."""
        self.clear()
        _ = self.activate_route()
        entry = self.HOME / ".claude/dsp-routes/s1.json"
        files = (self.MK(self.R), entry)
        before = [f.stat().st_ino for f in files]
        _ = self.activate_route()
        self.ok(
            "a re-activation replaces the marker and the entry (new inodes)",
            [f.stat().st_ino for f in files] != before
            and all(f.stat().st_ino != i for f, i in zip(files, before, strict=True)),
        )
        tmp = [*(self.R / ".git").rglob("*.tmp"), *entry.parent.rglob("*.tmp")]
        self.ok("no temp file left", not tmp, tmp)

        stop = self.T / "stop"
        self.rm(stop)
        run = self.marker().get("run")
        reader = subprocess.Popen(
            [PY, "-c", READER, self.MK(self.R), stop],
            env=self.env,
            stdout=subprocess.PIPE,
            text=True,
        )
        writers = [
            subprocess.Popen(
                [PY, "-c", WRITER, SCRIPTS, RS, self.P, self.R],
                env={**self.env, "CLAUDE_CODE_SESSION_ID": s},
                stdout=subprocess.PIPE,
                text=True,
            )
            for s in ("s1", "s2")
        ]
        codes = [w.communicate(timeout=600)[0] for w in writers]
        _ = stop.write_text("")
        got = cast("dict[str, object]", json.loads(reader.communicate(timeout=60)[0]))
        self.ok("both writers' 50 activations exit 0", codes == ["[0]\n"] * 2, codes)
        self.ok(
            f"a reader during 2 x 50 activations: reads={got['reads']} "
            f"misses={got['misses']} parse_failures={got['bad']}",
            got["bad"] == 0 and cast("int", got["reads"]) > 0 and got["runs"] == [run],
            got,
        )

    def test_absent_is_read_twice(self) -> None:
        """The old marker counts as absent only when a second read fails too."""
        self.clear()
        _ = self.activate_route()
        m = self.marker()
        none: dict[str, object] = {}
        for mode, want, calls in (
            ("missing1", m, 2),
            ("missing2", none, 2),
            ("enodata", m, 2),
            ("brace", none, 1),
        ):
            got = self.old_marker(mode)
            self.ok(
                f"{mode}: the marker read {calls} times gives "
                + ("the marker" if want else "{}"),
                got == {"calls": calls, "got": want},
                got,
            )
        _ = self.old_marker("missing1", self.P, self.R)
        kept = self.marker()
        self.ok(
            "activate() after one missed read keeps the run, no run_upgraded",
            kept.get("run") == m.get("run") and "run_upgraded" not in kept,
            kept,
        )
        _ = self.old_marker("missing2", self.P, self.R)
        self.ok(
            "activate() after two missed reads mints another run",
            self.marker().get("run") != m.get("run"),
            self.marker(),
        )

    # --- the registry entry

    def entry_path(self, session: str = "s1") -> Path:
        """Session's registry entry."""
        return self.HOME / ".claude/dsp-routes" / f"{session}.json"

    def entry_3c70cb6(self) -> None:
        """s1's entry written as a version before run ids wrote it."""
        self.entry_path().parent.mkdir(parents=True, exist_ok=True)
        _ = self.entry_path().write_text(
            json.dumps(
                {
                    "marker": str(self.MK(self.R)),
                    "planning_dir": str(self.P),
                    "activated": time.time() - 60,
                    "ledger": {"1": True, "1#checks": CHECKS},
                }
            )
        )

    def activate_plan(self, plan: Path) -> None:
        """--activate of phase 1 by s1 for the route whose planning dir is plan."""
        for d in ("lanes", "plans", "decisions/phase1", "spec"):
            (plan / d).mkdir(parents=True, exist_ok=True)
        _ = self.py(
            RS,
            plan,
            *("--phase", "1", "--repo", self.R, "--sections", "1-", "--activate"),
            session="s1",
        )

    def pointer(self, plan: Path) -> dict[str, object]:
        """The entry's pointer to the route of plan, as `previous` lists it."""
        return {
            "marker": str(self.MK(self.R, plan)),
            "planning_dir": str(plan),
            "run": self.marker(plan=plan).get("run"),
        }

    def sequence(self) -> str:
        """A report, a merge ask and a push check on s1's route, stamps normalised."""
        self.unthrottle()
        self.rm(*(self.R / ".git").glob("*.last"))
        merge = '"tool_name":"Bash","tool_input":{"command":"gh pr merge 1"}'
        out = "\n".join(
            (
                self.hook("report", ev("PostToolUse", "s1", '"tool_name":"Read"')),
                self.hook("ask:F81", ev("PreToolUse", "s1", merge)),
                self.gmsg(self.R, "git push origin main"),
            )
        )
        return STAMP.sub("<now>", out)

    def test_entry_has_run_and_args(self) -> None:
        """The entry keeps the marker's run and arguments."""
        self.clear()
        _ = self.activate_route()
        e, m = self.entry(), self.marker()
        self.ok(
            "the entry's run and args are the marker's",
            e.get("run") == m.get("run")
            and RUN.match(e.get("run", ""))
            and e.get("args") == m["args"],
            (e, m),
        )

    def test_previous(self) -> None:
        """`previous`: an upgrade adds nothing, a restart adds the old run."""
        self.clear()
        self.set_marker(self.shape_3c70cb6())
        self.entry_3c70cb6()
        _ = self.activate_route()
        self.ok(
            "an upgrade of the live route's run-less entry: previous == []",
            self.entry().get("previous") == [],
            self.entry(),
        )
        self.clear()
        _ = self.activate_route()
        old = self.marker().get("run")
        self.rm(self.MK(self.R))
        _ = self.activate_route()
        m = self.marker()
        self.ok(
            "a route ended and begun again in one session: another run, no upgrade",
            m.get("run") not in {None, old} and "run_upgraded" not in m,
            m,
        )
        prev = self.entry().get("previous", [])
        self.ok(
            f"...and previous ({len(prev)} items) opens with the ended run",
            prev[:1]
            == [
                {
                    "marker": str(self.MK(self.R)),
                    "planning_dir": str(self.P),
                    "run": old,
                }
            ],
            prev,
        )

    def test_moves(self) -> None:
        """A session moving between routes keeps up to 8, newest first."""
        self.clear()
        b = self.R / ".plan-b"
        _ = self.activate_route()
        a_run = self.marker().get("run")
        self.rm(self.HOME / ".claude/dsp-routes/events")
        _ = self.py(RS, "--hook", input=ev("PostToolUse", "s1", READ) + "\n", env=MON)
        self.activate_plan(b)
        e = self.entry()
        prev = e.get("previous", [])
        self.ok(
            f"A then B: the entry is B's, previous ({len(prev)} items) holds A",
            e["planning_dir"] == str(b) and prev == [self.pointer(self.P)],
            e,
        )
        runs = [line.get("run") for line in self.events()]
        self.ok(
            f"...and A's event ({len(runs)} lines) keeps A's run",
            a_run is not None and runs == [a_run] == [prev[0]["run"]],
            (a_run, runs),
        )
        _ = self.activate_route()
        prev = self.entry().get("previous", [])
        self.ok(
            f"A, B, A: previous ({len(prev)} items) holds B, not A",
            prev == [self.pointer(b)],
            prev,
        )
        self.clear()
        plans = [self.R / f".plan-{i}" for i in range(10)]
        for p in plans:
            self.activate_plan(p)
        prev = self.entry().get("previous", [])
        want = [self.pointer(p) for p in reversed(plans[:-1])][:PREVIOUS]
        self.ok(
            f"ten routes in turn: previous holds {len(prev)}, newest first",
            prev == want,
            prev,
        )

    def test_skill_digests_kept(self) -> None:
        """A re-activation is no re-read of the skill: its digests stay."""
        self.clear()
        _ = self.activate_route()
        digests = {"SKILL.md": "0123456789abcdef"}
        for value, want in ((digests, digests), ("x", None)):
            data = cast("dict[str, object]", json.loads(self.entry_path().read_text()))
            data["skill_digests"] = value
            _ = self.entry_path().write_text(json.dumps(data))
            _ = self.activate_route()
            self.ok(
                f"skill_digests {value!r} after a re-activation: {want!r}",
                self.entry().get("skill_digests") == want,
                self.entry(),
            )

    def test_readers_ignore_new_fields(self) -> None:
        """The hook and push_guard.py print the same with or without the new fields."""
        self.clear()
        _ = self.activate_route()
        drop = {
            self.MK(self.R): ("run", "run_upgraded", "x_future"),
            self.entry_path(): ("run", "args", "previous", "x_future"),
        }
        for f in drop:
            data = cast("dict[str, object]", json.loads(f.read_text()))
            data["x_future"] = 1
            _ = f.write_text(json.dumps(data))
        full = self.sequence()
        for f, keys in drop.items():
            data = cast("dict[str, object]", json.loads(f.read_text()))
            for k in keys:
                _ = data.pop(k, None)
            _ = f.write_text(json.dumps(data))
        bare = self.sequence()
        self.ok(
            "the same output with the new fields and without them",
            full == bare,
            (full, bare),
        )
        self.set_marker(self.shape_3c70cb6())
        self.entry_3c70cb6()
        self.unthrottle()
        self.rm(*(self.R / ".git").glob("*.last"))
        _ = self.hook("report", ev("PostToolUse", "s1", '"tool_name":"Read"'))
        self.rm(self.HOME / ".claude/dsp-routes/events")
        _ = self.py(RS, "--hook", input=ev("PostToolUse", "s1", READ) + "\n", env=MON)
        runs = [line.get("run", "absent") for line in self.events()]
        self.ok(
            f"a run-less entry's {len(runs)} event lines carry run null",
            runs == [None],
            runs,
        )


if __name__ == "__main__":
    _ = unittest.main()
