# SPDX-License-Identifier: MIT
"""usage_report.py: what a round spent, by session, model, effort and task group.

--since and --until, --project-dir, units by model, efforts, --groups, the measured
group fit --budget prints, and which transcripts are a route's lead, agents and hook
sessions.
"""

import datetime as dt
import json
import re
import shutil
import unittest
from collections.abc import Iterable
from typing import TypedDict, cast

from typing_extensions import override

import support
from support import RS, Result, crec, human, jline, peer, sent, ts, used

UR = support.SCRIPTS / "usage_report.py"
# argparse's exit code on an argument it cannot read
USAGE_ERROR = 2


class _Message(TypedDict):
    """The message of an assistant turn grec writes."""

    id: str
    model: str
    content: list[dict[str, object]]
    usage: dict[str, int]


class _Turn(TypedDict):
    """An assistant turn grec writes."""

    type: str
    timestamp: str
    requestId: str
    message: _Message


def rec(
    offset: float, request: str, model: str, tokens: int, entrypoint: str = ""
) -> str:
    """An assistant turn of model that read tokens from the cache, from entrypoint."""
    r: dict[str, object] = {
        "type": "assistant",
        "timestamp": ts(offset),
        "requestId": request,
        "message": {
            "id": request,
            "model": model,
            "content": [],
            "usage": {"cache_read_input_tokens": tokens},
        },
    }
    if entrypoint:
        r["entrypoint"] = entrypoint
    return jline(r)


def erec(offset: float, request: str, effort: str) -> str:
    """An assistant turn its request records at effort (none when empty)."""
    r: dict[str, object] = {
        "type": "assistant",
        "timestamp": ts(offset),
        "requestId": request,
        "message": {
            "id": request,
            "model": "claude-sonnet-5-5",
            "content": [],
            "usage": {"input_tokens": 1000},
        },
    }
    if effort:
        r["effort"] = effort
    return jline(r)


def grec(
    offset: float,
    request: str,
    tokens: int,
    content: Iterable[dict[str, object]] = (),
) -> str:
    """A task group's assistant turn at tokens of context, holding content."""
    turn: _Turn = {
        "type": "assistant",
        "timestamp": ts(offset),
        "requestId": request,
        "message": {
            "id": request,
            "model": "claude-opus-5-5",
            "content": list(content),
            "usage": {"cache_read_input_tokens": tokens},
        },
    }
    return jline(turn)


def tool(tool_id: str, name: str, command: str = "") -> list[dict[str, object]]:
    """The content of a turn that calls tool name with command."""
    return [
        {"type": "tool_use", "id": tool_id, "name": name, "input": {"command": command}}
    ]


def endturn(offset: float) -> str:
    """An assistant turn that ends the lead's turn."""
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "message": {
                "id": "e",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "ok"}],
            },
        }
    )


def auq(offset: float, question: str) -> str:
    """The user's answer to question, asked with AskUserQuestion."""
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "toolUseResult": {
                "questions": [{"question": question}],
                "answers": {question: "Yes"},
            },
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "q", "content": "answered"}
                ],
            },
        }
    )


FIT_READS_NO_SDK = """import sys; sys.path.insert(0, sys.argv[1])
from dsp_route import budget, transcript
def read(*a): raise SystemExit("sdk sessions read")
transcript.sdk_transcripts = read
print(budget.measured_fit("g1")[1])"""

# the budget hold's spend of a route's leads, in millions
SPEND = """import pathlib, sys; sys.path.insert(0, sys.argv[1])
from dsp_route import holds
leads = [pathlib.Path(p) for p in sys.argv[3:]]
print(f"{holds.spend(leads, sys.argv[2], '1') / 1e6:.1f}")"""


def slug(path: object) -> str:
    """The transcript dir name Claude Code gives a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


class UsageReport(support.Route):
    """usage_report.py on the route's lead and on transcripts written for each check."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the lead transcripts the report reads."""
        super().setUpClass()
        reg = cls.HOME / ".claude/dsp-routes"
        # the --main section's s9 copy of the route, and the lead transcripts the budget
        # and two-routes sections wrote: the lead's own records, in the order they were
        # written
        _ = shutil.copy(reg / "s1.json", reg / "s9.json")
        p = cls.HOME / ".claude/projects/p"
        _ = cls.write(p / "s9.jsonl", "")
        cls.append(p / "s9.jsonl", human(1), human(2), used(2, "u9", 5000000))
        _ = cls.write(cls.LEAD, "")
        cls.append(
            cls.LEAD,
            human(-3600),
            peer(1),
            human(1),
            *(sent(2, f"t{i}", f"exec-p1-0{i}-a") for i in range(1, 5)),
            sent(2, "t5", "exec-p1-05-a"),
            human(1),
            used(2, "u1", 11000),
            used(2, "u2", 2000),
            human(2),
            human(3),
            endturn(-2),
            human(-1),
            auq(-1, "Which lane runs first, p1-01 or p1-02?"),
            auq(-1, "Wave w5: ≈50M for 9 exec- agents — go ahead?"),
            endturn(0),
            human(3),
        )
        _ = cls.write(p / "s5.jsonl", human(1) + "\n")

    def usage(self, *args: object, merge: bool = True) -> Result:
        """usage_report.py on args, stderr merged into its output unless not merge."""
        return self.py(UR, *args, merge=merge)

    def test_usage_report(self) -> None:
        """Windows, project dirs, units, efforts, task groups and the budget's fit."""
        self.since_and_project_dir()
        self.units_and_efforts()
        self.task_groups()
        self.budget_fit()

    def since_and_project_dir(self) -> None:
        """--since in any offset, an unreadable --since, and --project-dir."""
        home = self.HOME
        pdir = home / ".claude/projects/p"
        r = self.usage("s1", "--project-dir", pdir)
        self.ok(
            "usage_report without --since",
            r.code == 0 and support.grep(r.out, "^lead .*turns=   2"),
            r.out,
        )
        z = ts(-600)
        o = (
            dt.datetime.fromisoformat(z)
            .astimezone(dt.timezone(dt.timedelta(hours=2)))
            .isoformat()
        )

        def lead_line(since: str) -> str:
            out = self.usage(
                "s1", "--project-dir", pdir, "--since", since, merge=False
            ).out
            return "\n".join(ln for ln in out.split("\n") if ln.startswith("lead"))

        a, b = lead_line(z), lead_line(o)
        self.ok(
            f"usage_report --since {o} counts as {z}",
            a == b and support.grep(a, "turns=   2"),
            f"{a} | {b}",
        )
        r = self.usage("s1", "--project-dir", pdir, "--since", "yesterday")
        self.ok(
            "usage_report refuses an unparseable --since",
            r.code == USAGE_ERROR and support.grep(r.out, "argument --since"),
            r.out,
        )
        # --project-dir naming the project itself, as a lead did (live)
        proj = self.T / "proj.x"
        proj.mkdir()
        sproj = home / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(proj))
        sproj.mkdir(parents=True)
        _ = shutil.copy(self.LEAD, sproj)
        r = self.usage("s1", "--project-dir", proj)
        self.ok(
            "usage_report --project-dir of the project reads its transcripts",
            r.code == 0 and support.grep(r.out, "^lead .*turns=   2"),
            r.out,
        )
        self.rm(proj, sproj)

    def units_and_efforts(self) -> None:
        """The units by model, hook sessions up to the round's end, and agent efforts.

        Hook sessions count only up to the round's last record or --until.
        """
        udir = self.HOME / ".claude/projects/u"
        udir.mkdir(parents=True)
        self.append(
            udir / "u1.jsonl",
            rec(-100, "q1", "claude-opus-5-5", 10000000),
            rec(-90, "q2", "claude-sonnet-5-5", 20000000),
            rec(-50, "q3", "claude-haiku-5-5", 24000000),
        )
        self.append(
            udir / "u2.jsonl",
            rec(-60, "k1", "claude-opus-5-5", 4000000, "sdk-ts"),
            rec(100, "k2", "claude-opus-5-5", 10000000, "sdk-ts"),
        )
        out = self.usage("u1", "--project-dir", udir).out
        self.ok(
            "usage_report: units by model, hook sessions up to the round's end",
            support.grep(
                out, "^total 1.5M = lead 1.3M + 0 agents 0.0M + 1 hook sessions 0.2M"
            ),
            out,
        )
        out = self.usage("u1", "--project-dir", udir, "--until", ts(-55)).out
        self.ok(
            "usage_report --until",
            support.grep(
                out, "^total 1.2M = lead 1.0M + 0 agents 0.0M + 1 hook sessions 0.2M"
            ),
            out,
        )
        # each agent's effort as its requests record it, a change mid-run included
        self.append(udir / "u3.jsonl", erec(-30, "e0", "xhigh"))
        sub = udir / "u3/subagents"
        sub.mkdir(parents=True)
        self.append(
            sub / "agent-ax.jsonl",
            erec(-20, "e1", "high"),
            erec(-10, "e2", "xhigh"),
            erec(-5, "e3", "high"),
        )
        self.append(sub / "agent-ay.jsonl", erec(-20, "e4", ""))
        out = self.usage("u3", "--project-dir", udir).out
        self.ok(
            "usage_report prints each agent's effort",
            support.grep(out, "^lead .* effort xhigh$")
            and support.grep(out, "^agent .*claude-sonnet-5-5 *high/xhigh  *agent-ax$")
            and support.grep(out, "^agent .*claude-sonnet-5-5 *-  *agent-ay$"),
            out,
        )

    def task_groups(self) -> None:
        """--groups: a task group's context at its first edit, its peak and commits.

        It also prints how many commits fit under the 200k stop (F60, F75); an
        integrator is not a task group.
        """
        gproj = self.HOME / ".claude/projects/g"
        g1 = gproj / "g1/subagents"
        g1.mkdir(parents=True)
        self.append(gproj / "g1.jsonl", grec(-700, "l1", 1000))
        commit = tool("t2", "Bash", "git add a && git commit -m x")
        self.append(
            g1 / "agent-e1.jsonl",
            grec(-600, "e1", 30000),
            grec(-500, "e2", 80000, tool("t1", "Edit")),
            grec(-400, "e3", 120000, commit),
            grec(-400, "e3", 120000, commit),  # a streamed copy
            grec(-300, "e4", 160000, tool("t3", "Bash", "git -C /w commit -m y")),
            grec(-240, "e5", 190000, tool("t4", "Bash", "git log")),
        )
        _ = self.write(
            g1 / "agent-e1.meta.json",
            '{"name":"exec-p1-01-a","agentType":"dsp-deep"}\n',
        )
        self.append(
            g1 / "agent-e2.jsonl",
            grec(-200, "w1", 50000, tool("t5", "Write")),
            grec(-100, "w2", 60000, tool("t6", "Bash", "git commit -m m")),
        )
        _ = self.write(
            g1 / "agent-e2.meta.json", '{"name":"exec-wave1","agentType":"dsp-deep"}\n'
        )
        out = self.usage("g1", "--project-dir", gproj, "--groups").out
        self.ok(
            "usage_report --groups",
            support.grep(
                out,
                "^group  exec-p1-01-a .*first-edit=  80k  peak= 190k  commits= 2  "
                "per-commit=  55k +6 min",
                E=True,
            )
            and support.grep(
                out,
                "^groups 1: median 6 min, 0.0M; first edit at 80k, "
                "+55k context per commit: "
                "about 2 commits fit under 200k",
            )
            and not support.grep(out, "exec-wave1"),
            out,
        )
        # a turn after a gap past the cache's 5 minutes that writes the whole prompt
        # again: a 10-minute wait loop cost 38.0M of one window's agent spend so (F92)
        rewrite = cast("_Turn", json.loads(grec(-1300, "r2", 0)))
        rewrite["message"]["usage"] = {"cache_creation_input_tokens": 100000}
        self.append(
            g1 / "agent-e3.jsonl",
            grec(-1700, "r1", 90000, tool("t7", "Edit")),
            jline(rewrite),
            grec(-1250, "r3", 100000),
        )
        _ = self.write(
            g1 / "agent-e3.meta.json",
            '{"name":"exec-p1-02-a","agentType":"dsp-deep"}\n',
        )
        out = self.usage("g1", "--project-dir", gproj, "--groups").out
        self.ok(
            "usage_report counts the cache rewrites after a gap past 5 minutes",
            support.grep(out, "^group  exec-p1-02-a .* rewrites=1$")
            and support.grep(out, "^group  exec-p1-01-a .* rewrites=0$")
            and support.grep(
                out, "^cache +0.1M  1 agent turns wrote the whole prompt", E=True
            ),
            out,
        )
        (g1 / "agent-e3.jsonl").unlink()
        (g1 / "agent-e3.meta.json").unlink()

    def budget_fit(self) -> None:
        """--budget prints that measure where the lead prices the wave (F60, F75)."""
        tmp = self.T
        m = self.marker()
        m["budgets"] = []
        _ = self.write(tmp / "gm.json", json.dumps(m))
        reg = self.HOME / ".claude/dsp-routes/g1.json"
        _ = self.write(
            reg,
            jline({"marker": str(tmp / "gm.json"), "planning_dir": str(self.P)}) + "\n",
        )

        def budget(*args: str) -> str:
            return self.py(RS, "--budget", *args, session="g1", merge=True).out

        out = budget("wg", "--estimate", "5", "--groups", "3", "--tasks", "9")
        self.ok(
            "--budget prints the project's measured group fit "
            "and the groups the tasks need",
            support.grep(out, "about 2 commits fit under 200k")
            and support.grep(out, "9 tasks need at least 5 task groups, not 3"),
            out,
        )
        out = budget("wg2", "--estimate", "5", "--groups", "6", "--tasks", "9")
        self.ok(
            "--budget with enough groups only prints the fit",
            support.grep(out, "about 2 commits fit")
            and not support.grep(out, "need at least"),
            out,
        )
        # the fit reads task groups only: a scan of every hook session per transcript
        # took 54 s
        out = self.run_(
            [support.PY, "-c", FIT_READS_NO_SDK, support.SCRIPTS], merge=True
        ).out
        self.ok("--budget's fit never reads the hook sessions", out == "2", out)
        reg.unlink()


class HookSessions(support.Sandbox):
    """Which transcripts are a route's leads, and which the running session's own.

    A route's other headless lead is a lead, a project named alike is not a worktree,
    and with no session id the running session's own transcript.
    """

    def test_leads_and_hook_sessions(self) -> None:
        """A second lead counts as lead; hook sessions and a look-alike do not."""
        tmp, home = self.T, self.HOME
        tab = self.init_repo(tmp / "tab")
        _ = self.git(
            "-C", tab, "worktree", "add", "-q", tmp / "tab-p1-01", "-b", "p1-01"
        )
        _ = self.git("init", "-q", "-b", "main", tmp / "tab-v2")
        projects = home / ".claude/projects"
        for d in ("-t-tab", "-t-tab-p1-01", "-t-tab-v2"):
            (projects / d).mkdir(parents=True)
        self.append(
            projects / "-t-tab/lead.jsonl",
            crec(-100, "a1", 1000000, str(tab)),
            crec(-50, "a2", 1000000, str(tab)),
        )
        self.append(
            projects / "-t-tab/lead2.jsonl",
            crec(-80, "b1", 5000000, str(tab), "sdk-cli"),
        )
        _ = self.write(home / ".claude/dsp-routes/lead2.json", "{}\n")
        self.append(
            projects / "-t-tab-p1-01/hook.jsonl",
            crec(-80, "c1", 2000000, str(tmp / "tab-p1-01"), "sdk-ts"),
        )
        self.append(
            projects / "-t-tab-v2/other.jsonl",
            crec(-80, "d1", 7000000, str(tmp / "tab-v2"), "sdk-py"),
        )
        self.touch(projects / "-t-tab/lead.jsonl", -60)
        out = self.py(UR, "lead", "--project-dir", projects / "-t-tab", merge=True).out
        self.ok(
            "usage_report: hook sessions are neither a route's lead "
            "nor another project",
            support.grep(
                out, "^total 4.0M = lead 2.0M + 0 agents 0.0M + 1 hook sessions 2.0M"
            ),
            out,
        )
        out = self.py(
            UR, "--project-dir", projects / "-t-tab", session="lead", merge=True
        ).out
        self.ok(
            "usage_report without a session id reports the running session",
            support.grep(out, "^session lead "),
            out,
        )
        (home / ".claude/dsp-routes/lead2.json").unlink()

    def test_lead_outside_its_repository(self) -> None:
        """A lead run from outside the repo counts the repo's and worktrees' hooks.

        Two leads ran from a directory in no repository: their hook sessions ran in the
        repository and its worktrees, and the report counted none of them.
        """
        tmp, home = self.T, self.HOME
        tab = self.init_repo(tmp / "repo")
        _ = self.git(
            "-C", tab, "worktree", "add", "-q", tmp / "repo-p1-01", "-b", "p1-01"
        )
        _ = self.git("init", "-q", "-b", "main", tmp / "repo-v2")
        hub = tmp / "hub"
        hub.mkdir()
        projects = home / ".claude/projects"
        lead = projects / slug(hub) / "lead.jsonl"
        lead2 = projects / slug(tab) / "lead2.jsonl"
        for d in ("", "-p1-01", "-v2"):
            (projects / (slug(tab) + d)).mkdir(parents=True)
        lead.parent.mkdir(parents=True)
        self.append(
            lead,
            crec(-100, "a1", 1000000, str(hub)),
            crec(-50, "a2", 1000000, str(hub)),
        )
        self.append(
            lead2,
            crec(-100, "b1", 1000000, str(tab)),
            crec(-40, "b2", 1000000, str(tab)),
        )
        self.append(
            projects / slug(tab) / "hook.jsonl",
            crec(-80, "c1", 2000000, str(tab), "sdk-ts"),
        )
        self.append(
            projects / slug(tab) / "human.jsonl",
            crec(-80, "c2", 5000000, str(tab)),
        )
        self.append(
            projects / (slug(tab) + "-p1-01") / "hook.jsonl",
            crec(-80, "c3", 3000000, str(tmp / "repo-p1-01"), "sdk-cli"),
        )
        self.append(
            projects / (slug(tab) + "-v2") / "other.jsonl",
            crec(-80, "c4", 7000000, str(tmp / "repo-v2"), "sdk-py"),
        )
        marker = jline({"marker": str(tab / ".git/dsp-route-0123456789.json")})
        for name in ("lead", "lead2"):
            _ = self.write(home / f".claude/dsp-routes/{name}.json", marker + "\n")
        want = "^total 7.0M = lead 2.0M + 0 agents 0.0M + 2 hook sessions 5.0M"
        out = self.py(UR, "lead", "--project-dir", lead.parent, merge=True).out
        self.ok(
            "usage_report: a registered lead outside its repository counts the "
            "repository's hook sessions",
            support.grep(out, want),
            out,
        )
        # the route's two leads count each hook session once
        out = self.run_(
            [support.PY, "-c", SPEND, support.SCRIPTS, ts(-200), lead, lead2],
            merge=True,
        ).out
        self.ok("the budget's spend counts a hook session once", out == "9.0", out)
        for name in ("lead", "lead2"):
            (home / f".claude/dsp-routes/{name}.json").unlink()
        out = self.py(
            UR, "lead", "--project-dir", lead.parent, "--repo", tab, merge=True
        ).out
        self.ok(
            "usage_report --repo counts that repository's hook sessions",
            support.grep(out, want),
            out,
        )


if __name__ == "__main__":
    _ = unittest.main()
