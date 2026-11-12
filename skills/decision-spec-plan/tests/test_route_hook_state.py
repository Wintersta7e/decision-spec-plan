# SPDX-License-Identifier: MIT
"""`route_state.py --hook`'s state report.

Who it speaks to, the user's answers it tallies, pending decisions, deltas on an agent's
return, and the SessionStart re-read after a compaction or resume.
"""

import json
import re
import subprocess
import time
import unittest
from typing import IO, cast

from typing_extensions import override

import support
from support import RS, ev, jline

ANSWERED = 9  # the answers the tally test gives before the tenth


def askq(answer: str, recommended: str = "Keep it (Recommended)") -> str:
    """A PostToolUse of AskUserQuestion answered with answer."""
    body = jline(
        {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {
                        "question": "Q?",
                        "options": [{"label": recommended}, {"label": "Drop it"}],
                    }
                ]
            },
            "tool_response": {"answers": {"Q?": answer}},
        }
    )
    return ev("PostToolUse", "s1", body[1:-1])


def _context(out: str) -> str | None:
    """The `additionalContext` a hook printed, or None when out holds none."""
    try:
        data = cast("object", json.loads(out))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    spec = cast("dict[str, object]", data).get("hookSpecificOutput")
    if not isinstance(spec, dict):
        return None
    ctx = cast("dict[str, object]", spec).get("additionalContext")
    return ctx if isinstance(ctx, str) else None


def _unbind(m: support.Marker) -> None:
    """The marker's phase 1 marked as not bound by the decision ledger."""
    m.setdefault("ledger", {})["1"] = False


def pending_state(cls: type[support.Route] | support.Route) -> None:
    """The pending section's steps.

    An old-format index with D2 unwritten, the phase unbound, and one report the next
    delta compares against.
    """
    d = cls.P / "decisions/phase1"
    _ = cls.write(d / "00-index.md", "| D1 | a |\n| D2 | b |\n")
    _ = cls.write(d / "D1-a.md", "ruling\n")
    cls.edit_marker(_unbind)
    for f in (cls.HOME / ".claude/dsp-routes").glob("*.checked"):
        f.unlink()


class StateHook(support.Route):
    """The state hook: who it speaks to."""

    def test_who_it_speaks_to(self) -> None:
        """The lead's session hears the report; agents, others and prompts do not."""
        _ = self.hook("report", ev("PostToolUse", "s1", '"tool_name":"Agent"'))
        _ = self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read"')
        )  # throttled
        self.unthrottle()
        _ = self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read"')
        )  # nothing changed
        _ = self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read","agent_id":"a1"')
        )
        _ = self.hook(
            "silent", ev("PostToolUse", "s2", '"tool_name":"Read"')
        )  # never activated
        _ = self.hook(
            "silent",
            ev("UserPromptSubmit", "s1", '"prompt":"what is left on the todo?"'),
        )
        _ = self.hook(
            "silent",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<task-notification>\n<task-id>x</task-id>"',
            ),
        )


class Answers(support.Route):
    """The user's answers.

    Nine in ten taking the recommendation stop telling the lead anything (F89).
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Run the report that throttles the next tool calls."""
        super().setUpClass()
        # the state hook section's report: the next tool calls are throttled
        _ = cls.py(
            RS, "--hook", input=ev("PostToolUse", "s1", '"tool_name":"Agent"') + "\n"
        )

    def test_answer_tally(self) -> None:
        """Answers are tallied, the tenth tells, and a re-activation keeps them."""
        out = ""
        for answer in ["Drop it"] + ["Keep it (Recommended)"] * 8:
            out += self.hook_out(askq(answer)).out
        asks = self.marker().get("asks", [])
        self.ok(
            "answers are tallied, and fewer than ten say nothing",
            out == "" and len(asks) == ANSWERED,
            f"{out} {json.dumps(asks)}",
        )
        _ = self.hook(
            "/took your recommendation in 9 of their last 10 answers/",
            askq("Keep it (Recommended)"),
        )
        _ = self.hook(
            "silent", askq("Keep it", "Keep it")
        )  # no option recommended: not tallied
        _ = self.hook("/9 of their last 10/", askq("Drop it"))
        _ = self.hook("silent", askq("Drop it"))
        # the tally spans the route: a phase's re-activation (Stage 5's `--sins on`)
        # keeps it
        before = self.marker()
        assert "asks" in before, json.dumps(before)
        n = len(before["asks"])
        _ = self.activate_route()
        asks = self.marker().get("asks", [])
        self.ok(
            "a re-activation keeps the answer tally", len(asks) == n, json.dumps(asks)
        )


class Pending(support.Route):
    """Pending, not missing: index rows without files."""

    def test_pending_not_missing(self) -> None:
        """An index row without its file is pending, and no flag calls it missing."""
        pending_state(self)
        _ = self.hook(
            r"/decisions  1 D files \(2 in the index; pending D2\)/",
            ev("PostToolUse", "s1", '"tool_name":"Agent"'),
        )
        ctx = _context(self.last)
        clean = (
            ctx is not None and re.search("missing|written [0-9]+s ago", ctx) is None
        )
        self.ok("no missing / freshness flags in a hook report", clean, self.last)


class Deltas(support.Route):
    """Deltas on an agent's return, by prompt or by the next tool call."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Leave the pending section's state, its report included."""
        super().setUpClass()
        # the state the pending section leaves, its report included
        pending_state(cls)
        _ = cls.py(
            RS, "--hook", input=ev("PostToolUse", "s1", '"tool_name":"Agent"') + "\n"
        )

    def test_deltas(self) -> None:
        """A teammate's message and the next tool call report what changed."""
        p = self.P
        _ = self.write(
            p / "lanes/p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {self.MAIN}\n"
        )
        _ = self.hook(
            "/lanes      1 checkpoints/",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<teammate-message teammate_id=\"g1\">'
                r'done</teammate-message>"',
            ),
        )
        _ = self.hook(
            "silent",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<agent-message from=\"a1\">\n[Subagent hand-back] done"',
            ),
        )
        _ = self.write(p / "decisions/phase1/D2-b.md", "ruling\n")
        self.unthrottle()
        _ = self.hook(
            r"/changed between .*\n.*2 D files \(2 in the index\)/",
            ev("PostToolUse", "s1", '"tool_name":"Bash"'),
        )


class SessionStart(support.Route):
    """SessionStart after a compaction and a resume."""

    def test_session_start(self) -> None:
        """A compaction re-reads the handoff, a resume the skill; others are silent."""
        _ = self.hook(
            r"/Re-read .*HANDOFF.md[\s\S]*\nroute state ·/",
            ev("SessionStart", "s1", '"source":"compact"'),
        )
        _ = self.hook(
            "/Read .*SKILL.md in full/", ev("SessionStart", "s1", '"source":"resume"')
        )
        _ = self.hook("silent", ev("SessionStart", "s1", '"source":"startup"'))
        _ = self.hook("silent", ev("SessionStart", "s2", '"source":"compact"'))


READ = '"tool_name":"Read"'


def _flag(cls: support.Route, name: str = "two") -> None:
    """A new flag in the next report: an empty reconcile file an hour old."""
    rec = cls.write(cls.P / f"reconcile/p1-{name}.md", "")
    cls.touch(rec, -3600)


def _post(cls: support.Route, session: str) -> str:
    """The context a PostToolUse of session injects, "" for none."""
    return _context(cls.hook_out(ev("PostToolUse", session, READ)).out) or ""


class TwoLeads(support.Route):
    """Two leads of one route each keep their own last injection."""

    def test_two_leads(self) -> None:
        """A flag one lead was told of still reaches the other."""
        _ = self.activate_route(session="s2")
        _ = _post(self, "s1")
        _ = _post(self, "s2")
        _flag(self)
        self.unthrottle()
        s1 = _post(self, "s1")
        self.unthrottle()
        s2 = _post(self, "s2")
        self.ok(
            "two leads: both hear the new flag",
            "reconcile/p1-two.md" in s1 and "reconcile/p1-two.md" in s2,
            f"s1 {s1!r}\ns2 {s2!r}",
        )


class SeedShared(support.Route):
    """A new lead's delta starts from the shared file, which stays as it was."""

    def test_seed_shared(self) -> None:
        """The shared `.last` seeds a new session's delta and is never written."""
        _ = _post(self, "s1")
        marker = self.MK(self.R)
        shared = marker.with_suffix(".last")
        own = marker.with_name(f"{marker.stem}.s1.last")
        if own.exists():
            _ = own.replace(shared)
        self.touch(shared, -600)
        before = (shared.read_bytes(), shared.stat().st_mtime_ns)
        _flag(self)
        _ = self.activate_route(session="s3")
        out = _post(self, "s3")
        after = (shared.read_bytes(), shared.stat().st_mtime_ns)
        self.ok(
            "seed: a new session's first report is a delta from the shared file",
            "changed between" in out and "in-flight block's state" not in out,
            out,
        )
        self.ok(
            "seed: the shared file's bytes and mtime are unchanged",
            after == before,
            f"before {before}\nafter  {after}",
        )


class SeedOtherSession(support.Route):
    """With no shared file, another session's `.last` seeds a new lead's delta."""

    def test_seed_other_session(self) -> None:
        """A second lead's first report is a delta from the first lead's file."""
        _ = _post(self, "s1")
        marker = self.MK(self.R)
        self.ok(
            "seed: no shared file, one per-session file",
            not marker.with_suffix(".last").exists()
            and marker.with_name(f"{marker.stem}.s1.last").exists(),
            sorted(p.name for p in marker.parent.glob("*.last")),
        )
        _flag(self)
        _ = self.activate_route(session="s2")
        out = _post(self, "s2")
        self.ok(
            "seed: a second lead's first report is a delta holding the new flag",
            "changed between" in out and "reconcile/p1-two.md" in out,
            out,
        )


WINDOW_S = 20  # the hook's THROTTLE_S: a claim file per window of this many seconds
HOOKS = 8  # parallel PostToolUse hooks per round
ROUNDS = 5
KEPT = 2  # the claim files a session keeps at most: this window's and the last one's


def _window(min_left: float) -> int:
    """The current throttle window, after waiting for the next one to start.

    The wait happens only when fewer than min_left seconds of this window remain, so it
    is bounded at WINDOW_S.
    """
    left = WINDOW_S - time.time() % WINDOW_S
    if left < min_left:
        time.sleep(left)
    return int(time.time()) // WINDOW_S


class ConcurrentHooks(support.Route):
    """Parallel PostToolUse hooks of one session inject the report once."""

    def test_one_injection_per_round(self) -> None:
        """Of 8 hooks started together, exactly one injects, in every round."""
        counts: list[int] = []
        for k in range(ROUNDS):
            self.unthrottle()
            _flag(self, f"r{k}")
            _ = _window(12)
            procs = [
                subprocess.Popen(
                    [support.PY, RS, "--hook"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self.env,
                    text=True,
                )
                for _ in range(HOOKS)
            ]
            time.sleep(0.5)
            for p in procs:
                assert p.stdin is not None
                _ = p.stdin.write(ev("PostToolUse", "s1", READ) + "\n")
                p.stdin.close()
            outs: list[str] = []
            for p in procs:
                # stdout=PIPE: never None; typeshed says IO[Any], text=True makes it str
                assert p.stdout is not None
                stream: IO[str] = p.stdout
                outs.append(stream.read())
                stream.close()
                _ = p.wait(timeout=120)
            counts.append(sum(1 for o in outs if o.strip()))
        self.ok(
            f"parallel hooks: injections per round of {HOOKS}: {counts}",
            counts == [1] * ROUNDS,
            counts,
        )


class ThrottleGap(support.Route):
    """The previous window's recent claim keeps the gap; old claims are removed."""

    def test_gap_and_bound(self) -> None:
        """A claim a second old throttles, one 30 s old does not, and old ones go."""
        reg = self.HOME / ".claude/dsp-routes"
        legacy = reg / "s1.checked"
        seen: list[bool] = []
        w = _window(5)
        prev = reg / f"s1.{w - 1}.checked"
        self.touch(prev, -1)
        _flag(self, "g1")
        quiet = _post(self, "s1")
        seen.append(legacy.exists())
        self.touch(prev, -30)
        control = _post(self, "s1")
        seen.append(legacy.exists())
        self.ok(
            "throttle gap: a claim 1 s old in the last window holds, 30 s old does not",
            quiet == "" and control != "",
            f"quiet {quiet!r}\ncontrol {control!r}",
        )
        self.unthrottle()
        w = _window(5)
        for k in range(1, 6):
            self.touch(reg / f"s1.{w - k}.checked", -30)
        _flag(self, "g2")
        bound = _post(self, "s1")
        seen.append(legacy.exists())
        left = len(list(reg.glob("s1.*.checked")))
        self.ok(
            f"throttle bound: it reports and leaves {left} claim files of 6",
            bound != "" and 0 < left <= KEPT,
            f"{sorted(p.name for p in reg.glob('s1*'))}\n{bound!r}",
        )
        self.ok("the legacy s1.checked is never written", not any(seen), seen)


class ClaimFirst(support.Route):
    """A window another hook already claimed injects nothing."""

    def test_claimed_window(self) -> None:
        """With this window's claim present, a PostToolUse is silent."""
        reg = self.HOME / ".claude/dsp-routes"
        w = _window(5)
        self.touch(reg / f"s1.{w}.checked")
        _flag(self, "c1")
        out = _post(self, "s1")
        self.ok(
            "claimed window: no injection, and no legacy s1.checked",
            out == "" and not (reg / "s1.checked").exists(),
            out,
        )


if __name__ == "__main__":
    _ = unittest.main()
