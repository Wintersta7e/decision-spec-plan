# SPDX-License-Identifier: MIT
"""The hook inside a route's agents.

An exec- agent's context stop (F75) and its commit held for an unread ruling (F59), and
an agent sent back to wait on its own background job (F92).
"""

import json
import os
import unittest
from pathlib import Path
from typing import cast

from typing_extensions import override

import support
from support import call, ev, human, jline, notice, ts, used

SENT_BACK = 2  # the stop hook's exit that sends the agent back to wait


class Route(support.Route):
    """support.Route with the lead's transcript begun and its subagents dir SUB."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Begin the lead's transcript and create SUB."""
        super().setUpClass()
        # the lead transcript the budget section began, the hooks' transcript_path
        _ = cls.write(cls.LEAD, human(-3600) + "\n")
        cls.SUB: Path = cls.HOME / ".claude/projects/p/s1/subagents"
        cls.SUB.mkdir(parents=True)


class ExecAgent(Route):
    """An exec- agent's context stop and its commit held for an unread ruling."""

    def inagent(self, agent: str, command: str) -> str:
        """A Bash call of command by agent in the lead's session."""
        return ev(
            "PreToolUse",
            "s1",
            f'"agent_id":"{agent}","tool_name":"Bash",'
            f'"tool_input":{{"command":"{command}"}},'
            f'"transcript_path":"{self.LEAD}"',
        )

    def test_context_stop_and_rulings_hold(self) -> None:
        """The context stop is told once; a commit waits until the ruling is read."""
        rulings = self.P / "lanes/p1-01-rulings.md"
        self._context_stop(rulings)
        read = self._rulings_hold(rulings)
        self._commit_forms(rulings, read)
        self._own_lane_file(rulings)

    def _context_stop(self, rulings: Path) -> None:
        """Past 200k tokens an exec- agent is told to finish, once."""
        sub = self.SUB
        _ = self.write(
            sub / "agent-x1.meta.json",
            '{"name":"exec-p1-01-b","agentType":"dsp-deep"}\n',
        )
        _ = self.write(
            sub / "agent-y1.meta.json",
            '{"name":"pride-p1-push1","agentType":"dsp-deep"}\n',
        )
        first = {
            "type": "user",
            "timestamp": ts(-60),
            "message": {"role": "user", "content": f"Rulings file: {rulings}"},
        }
        _ = self.write(sub / "agent-x1.jsonl", jline(first) + "\n")
        self.append(sub / "agent-x1.jsonl", used(-50, "a1", 150000))
        _ = (sub / "agent-y1.jsonl").write_bytes((sub / "agent-x1.jsonl").read_bytes())
        _ = self.hook("silent", self.inagent("x1", "ls"))
        self.append(sub / "agent-x1.jsonl", used(-40, "a2", 210000))
        self.append(sub / "agent-y1.jsonl", used(-40, "a2", 210000))
        _ = self.hook(
            "/your context is 210k tokens. Finish the task/", self.inagent("x1", "ls")
        )
        _ = self.hook("silent", self.inagent("x1", "ls"))  # told once
        _ = self.hook("silent", self.inagent("y1", "ls"))  # not an exec- agent
        _ = self.hook(
            "silent", self.inagent("x1", "git commit -m x")
        )  # no rulings file yet

    def _rulings_hold(self, rulings: Path) -> dict[str, object]:
        """A commit is held until the agent reads its rulings; the read is returned."""
        sub = self.SUB
        _ = self.write(rulings, "R1 use the old API\n")
        _ = self.hook(
            r"deny:re-read .*p1-01-rulings.md \(.*\) before you commit",
            self.inagent("x1", "git -C /w commit -m x"),
        )
        # the text says which: a file the agent never read is not one changed "after
        # your last read" (live); a fast-forward makes no commit of the agent's
        _ = self.hook(
            r"deny:p1-01-rulings.md \(you have not read it\) before you commit",
            self.inagent("x1", "git commit -m x"),
        )
        _ = self.hook("silent", self.inagent("x1", "git merge --ff-only exec-p1-01-a"))
        _ = self.hook("silent", self.inagent("x1", "git status"))
        _ = self.hook("silent", self.inagent("y1", "git commit -m x"))
        read: dict[str, object] = {
            "type": "assistant",
            "timestamp": ts(30),
            "message": {
                "id": "r1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "r1",
                        "name": "Read",
                        "input": {"file_path": str(rulings)},
                    }
                ],
            },
        }
        self.append(sub / "agent-x1.jsonl", jline(read))
        _ = self.hook("silent", self.inagent("x1", "git commit -m x"))
        return read

    def _commit_forms(self, rulings: Path, read: dict[str, object]) -> None:
        """A changed ruling holds every form that makes a commit, read as bash would."""
        t, sub = self.T, self.SUB
        # the transcript repeats a tool_use in an untimestamped api-request-blob record;
        # the read still counts
        blob = {
            "type": "api-request-blob",
            "agentId": "x1",
            "hash": "h1",
            "sessionId": "s1",
            "message": read["message"],
        }
        self.append(sub / "agent-x1.jsonl", jline(blob))
        _ = self.hook("silent", self.inagent("x1", "git commit -m x"))
        self.touch(rulings, 120)
        _ = self.hook(
            r"deny:re-read .*p1-01-rulings.md "
            r"\(the lead changed it after your last read\)",
            self.inagent("x1", "git commit -m x"),
        )
        # every form that makes a commit, read as bash reads it: a regex missed each of
        # these
        held = "deny:re-read .*p1-01-rulings.md"
        _ = self.hook(held, self.inagent("x1", "git -C '/a b/wt' commit -m x"))
        _ = self.hook(held, self.inagent("x1", "git --no-pager commit -m x"))
        _ = self.hook(held, self.inagent("x1", "git merge --no-ff lane"))
        _ = self.hook(held, self.inagent("x1", "git cherry-pick abc123"))
        _ = self.hook("silent", self.inagent("x1", "git log --grep 'commit'"))
        _ = self.hook(held, self.inagent("x1", "sudo git commit -m x"))
        _ = self.hook(held, self.inagent("x1", "git $'commit' -m x"))
        _ = self.hook(held, self.inagent("x1", "X='git commit -m x'; bash -c $X"))
        _ = self.hook(held, self.inagent("x1", r"bash <<EOF\ngit commit -m x\nEOF"))
        _ = self.hook(held, self.inagent("x1", "git merge --ff-only --no-ff lane"))
        _ = self.hook("silent", self.inagent("x1", "git merge --no-ff --ff-only lane"))
        # a script it runs is read where the command's `cd` left it, by path too, and as
        # it will be written
        scripts = t / "scripts"
        _ = self.write(scripts / "commit.sh", "git commit -m x\n")
        self.chmod_x(scripts / "commit.sh")
        _ = self.hook(held, self.inagent("x1", f"cd {scripts} && bash commit.sh"))
        _ = self.hook(held, self.inagent("x1", f"{scripts}/commit.sh"))
        _ = self.write(scripts / "w.sh", "ls\n")
        _ = self.hook(
            held,
            self.inagent(
                "x1", f"printf 'git commit -m x' >{scripts}/w.sh; bash {scripts}/w.sh"
            ),
        )

    def _own_lane_file(self, rulings: Path) -> None:
        """Only the agent's own lane file holds its commit, its archive never."""
        p, sub = self.P, self.SUB
        # only the agent's own lane file holds its commit: a `lanes/` listing once named
        # every lane's (F59)
        cat = {
            "type": "assistant",
            "timestamp": ts(200),
            "message": {
                "id": "r2",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "r2",
                        "name": "Bash",
                        "input": {"command": f"cat {rulings}"},
                    }
                ],
            },
        }
        self.append(sub / "agent-x1.jsonl", jline(cat))
        _ = self.write(p / "lanes/p1-02-rulings.md", "R1 another lane's ruling\n")
        self.touch(p / "lanes/p1-02-rulings.md", 300)
        listing = "\n".join(sorted(f.name for f in (p / "lanes").iterdir()))
        result = {
            "type": "user",
            "timestamp": ts(210),
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "l1", "content": listing}
                ],
            },
        }
        self.append(sub / "agent-x1.jsonl", jline(result))
        _ = self.hook("silent", self.inagent("x1", "git commit -m x"))
        # the lane's archive of applied rulings never holds a commit
        _ = self.write(p / "lanes/p1-01-rulings-archive.md", "R0 applied\n")
        self.touch(p / "lanes/p1-01-rulings-archive.md", 300)
        _ = self.hook("silent", self.inagent("x1", "git commit -m x"))
        # a lane file named by plan id, never in the transcript: the dispatch points at
        # a brief
        _ = self.write(
            sub / "agent-z1.meta.json",
            '{"name":"exec-p1-03-c","agentType":"dsp-deep"}\n',
        )
        brief = {
            "type": "user",
            "timestamp": ts(-60),
            "message": {
                "role": "user",
                "content": "Read your brief first: /w/dispatch-p1-03-c.md",
            },
        }
        _ = self.write(sub / "agent-z1.jsonl", jline(brief) + "\n")
        _ = self.write(p / "lanes/p1-03-wide-rulings.md", "R1 wide\n")
        _ = self.hook(
            "deny:re-read .*p1-03-wide-rulings.md",
            self.inagent("z1", "git commit -m x"),
        )


class WaitsOnItsJob(Route):
    """An agent that ends its turn while its own background job runs.

    It is sent back to wait on it: nothing wakes a teammate when the job ends (F92).
    """

    def test_stop_hook(self) -> None:
        """Running jobs of the agent's own send it back; ended or others' do not."""
        t, sub, lead = self.T, self.SUB, self.LEAD
        tasks = t / "tasks"
        tasks.mkdir()
        tm = sub / "agent-aexec-p1-02-a-0123456789abcdef.jsonl"
        _ = self.write(tm, "")
        self.append(
            tm,
            *call(
                "t1",
                "Bash",
                {"command": "npm test", "run_in_background": True},
                "Command running in background with ID: bsh1. "
                "Output is being written to: "
                f"{tasks}/bsh1.output. You will be notified when it completes.",
            ),
            *call("t2", "Bash", {"command": "ls"}, "a b"),
        )
        idle = ev(
            "TeammateIdle",
            "s1",
            '"teammate_name":"exec-p1-02-a",'
            '"agent_id":"aexec-p1-02-a-0123456789abcdef",'
            f'"transcript_path":"{lead}"',
        )
        _ = self.write(tasks / "bsh1.output", "running\n")
        self.stophook(2, "npm test.*bsh1.output.*F92", idle)
        _ = self.write(tasks / "bsh1.output", "running\n\n[exited with code 0]\n")
        self.stophook(0, "^$", idle)
        _ = self.write(tasks / "bsh1.output", "\n[killed]\n")
        self.stophook(0, "^$", idle)
        self.append(
            tm,
            *call(
                "t3",
                "Monitor",
                {
                    "command": "until grep -q ^exit= g.log; do sleep 20; done",
                    "description": "gate",
                },
                "Monitor started (task bmo1, expires in 30m unless the source ends "
                "first).",
            ),
        )
        _ = self.write(tasks / "bmo1.output", "x\n")
        self.stophook(2, r"until grep -q \^exit= g.log.*F92", idle)
        (tasks / "bmo1.output").unlink()
        self.append(tm, notice("bmo1", "completed"))
        self.stophook(0, "^$", idle)  # its notification ended it
        self.stophook(
            0,
            "^$",
            ev(
                "TeammateIdle",
                "s1",
                '"teammate_name":"nobody","agent_id":"anobody-00000000",'
                f'"transcript_path":"{lead}"',
            ),
        )
        # a foreground command past its timeout moves to the background without
        # run_in_background
        self.append(
            tm,
            *call(
                "t4",
                "Bash",
                {"command": "npx eslint . > lint.log"},
                "partial output\nCommand did not complete within its 300s timeout "
                "and was moved "
                "to the background (ID: bauto1). Output is being written to: "
                f"{tasks}/bauto1."
                "output. You will be notified when it completes.",
            ),
        )
        _ = self.write(tasks / "bauto1.output", "x\n")
        self.stophook(2, "npx eslint.*bauto1.output.*F92", idle)
        (tasks / "bauto1.output").unlink()
        # SubagentStop lists every background job of the session, a neighbour
        # teammate's too: only the jobs the stopping agent's own transcript started
        # count, and an agent with no transcript has none.
        tb = sub / "agent-aexec-p1-02-b-0123456789abcdef.jsonl"
        _ = self.write(tb, "")
        self.append(
            tb,
            *call(
                "u1",
                "Bash",
                {"command": "npm test > gate.log", "run_in_background": True},
                "Command running in background with ID: bsb1. "
                "Output is being written to: "
                f"{tasks}/bsb1.output. You will be notified when it completes.",
            ),
            *call(
                "u2",
                "Monitor",
                {"command": "tail -f x", "description": "watch"},
                "Monitor started (task bsb2, expires in 30m unless the source ends "
                "first).",
            ),
        )

        def bg(task: str, kind: str, status: str) -> str:
            return (
                f'"background_tasks":[{{"id":"{task}","type":"{kind}",'
                f'"status":"{status}",'
                '"command":"npm test > gate.log"}]'
            )

        def stop(extra: str, session: str = "s1") -> str:
            return ev(
                "SubagentStop",
                session,
                '"agent_id":"aexec-p1-02-b-0123456789abcdef","agent_type":"dsp-deep",'
                f'"transcript_path":"{lead}",{extra}',
            )

        self.stophook(
            2,
            "npm test > gate.log.*bsb1.output.*F92",
            stop(bg("bsb1", "shell", "running")),
        )
        self.stophook(0, "^$", stop(bg("bsb1", "shell", "completed")))
        self.stophook(0, "^$", stop(bg("bsb1", "subagent", "running")))
        self.stophook(2, "tail -f x.*F92", stop(bg("bsb2", "monitor", "running")))
        self.stophook(
            0, "^$", stop(bg("bother", "shell", "running"))
        )  # a neighbour's job
        self.stophook(
            0,
            "^$",
            ev(
                "SubagentStop",
                "s1",
                f'"agent_id":"a0123456789abcdef",{bg("bsb1", "shell", "running")}',
            ),
        )  # no transcript
        self.stophook(0, "^$", stop(bg("bsb1", "shell", "running"), "s77"))  # no route
        active = f'"stop_hook_active":true,{bg("bsb1", "shell", "running")}'
        self.stophook(2, "F92", stop(active))
        # sent back twice: a hung job is the agent's to report
        self.stophook(0, "^$", stop(active))
        _ = cast("object", json.loads(stop(active)))  # the event stays valid JSON


if __name__ == "__main__":
    _ = unittest.main()
