# SPDX-License-Identifier: MIT
"""The hook inside a route's agents.

An exec- agent's context stop (F75) and its commit held for an unread ruling (F59), a
hunt- agent held find-only (F109), and an agent sent back to wait on its own background
job (F92).
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


# every writing `git config` form a hunter is refused, one per form the spec names
CONFIG_WRITES = (
    "git config --add a.b c",
    "git config --replace-all a.b c",
    "git config --unset a.b",
    "git config --unset-all a.b",
    "git config --rename-section a b",
    "git config --remove-section a",
    "git config -e",
    "git config --edit",
    "git config user.name x",
    "git config set user.name x",
    "git config unset user.name",
    "git config rename-section a b",
    "git config remove-section a",
    "git config edit",
)
CONFIG_WRITE_FORMS = 14
# a hunter's git forms past a plain commit and config write: a subcommand the hook
# cannot read, plumbing that commits, config indirection
HUNTER_GIT = (
    "git $x status",
    'git "$(echo commit)" -m x',
    "git commit-tree HEAD^{tree} -m x",
    "git update-ref refs/heads/x HEAD",
    "git -c include.path=/x log",
    "git -c includeIf.onbranch:main.path=/x log",
    "git -c INCLUDE.path=/x log",
    "git --config-env include.path=X log",
    "GIT_CONFIG_PARAMETERS=\"'alias.sv=commit'\" git sv",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.sv GIT_CONFIG_VALUE_0=commit git sv",
    "env GIT_CONFIG_KEY_0=core.hooksPath git status",
    "export GIT_CONFIG_COUNT=1; git status",
)
HUNTER_GIT_FORMS = 12
# the git a hunter may run inside the hunted repository: one per allowlist entry
READ_ONLY_GIT = (
    "git status",
    "git log --oneline",
    "git show HEAD",
    "git diff HEAD~1",
    "git blame README",
    "git grep x",
    "git ls-files",
    "git ls-tree HEAD",
    "git ls-remote .",
    "git cat-file -t HEAD",
    "git rev-parse HEAD",
    "git rev-list HEAD",
    "git describe --always",
    "git shortlog -s HEAD",
    "git name-rev HEAD",
    "git merge-base HEAD main",
    "git for-each-ref",
    "git show-ref",
    "git config --get user.name",
    "git branch",
    "git branch -a --list",
    "git tag",
    "git tag -l 'v*'",
    "git worktree list",
    "git remote",
    "git remote -v",
    "git remote show origin",
    "git remote get-url origin",
    "git stash list",
    "git stash show",
)
READ_ONLY_FORMS = 30
# git the hunted repository refuses a hunter and its own clone allows: a saving stash
# among them
REPO_WRITES = (
    "git reset --hard",
    "git notes add -m x",
    "git symbolic-ref HEAD refs/heads/x",
    "git branch -f x",
    "git checkout -b x",
    "git tag v1",
    "git stash",
    "git stash push",
    "git stash save x",
    "git stash store abc",
    "git stash create",
    "git stash -m x",
)
REPO_WRITE_FORMS = 12
# aliases the hunter's repository defines, each running a held command
HELD_ALIASES = {
    "sv": "commit",
    "up": "update-ref refs/heads/x HEAD",
    "cf": "config core.hooksPath h",
    "sh": "!git commit",
}
HELD_ALIAS_FORMS = 4
# clones of the hunted repository {r} run inside it that write into it, or where the
# hook cannot tell: {out} is outside it, a word that only looks like the destination
CLONE_INTO_REPO = (
    "git clone -q file://{r} {r}/x",
    "git clone -q file://{r}",  # git names the destination after the source, here
    "git clone file://{r} x",
    'git clone file://{r} "$D"',
    "git clone file://{r} -b {out}",
    "git clone file://{r} --br {out}",
    "git clone file://{r} -qb {out}",
    "git clone --separate-git-dir={r}/g file://{r} {out}",
    "git clone --separate-git-dir {r}/g file://{r} {out}",
    "git clone $OPTS file://{r} {out}",
)
CLONE_INTO_REPO_FORMS = 10
# `for` loops a hunter runs in {t}, outside the hunted repository {r}: a literal list
# writes one target per word; a computed list, a variable set again in the body, a
# target after the loop or on its `done` the hook cannot read
LOOP_WRITES = (
    ("for b in a b c; do printf x > dir/$b; done", "silent"),
    ("for i in 1 2 3; do cargo test > ../log-$i.txt 2>&1; done", "silent"),
    ("for b in a b; do for c in x y; do echo > $b$c; done; done", "silent"),
    ("while false; do for c in x; do echo > $c; done; done", "silent"),
    ("for b in a b c; do printf x > {r}/x$b; done", "deny:find-only"),
    ("for b in {t}/a {r}/b; do echo > $b; done", "deny:find-only"),
    ("for i in $(seq 3); do echo > f$i; done", "deny:find-only"),
    ("for i in *; do echo > f$i; done", "deny:find-only"),
    ("b={t}; for b in $(ls); do echo > $b/f; done", "deny:find-only"),
    ("for b in {t}; do b={r}; echo > $b/f; done", "deny:find-only"),
    ("for b in {t}; do :; done; echo > $b/f", "deny:find-only"),
    ("for b in {t}/a; do :; done > $b/f", "deny:find-only"),
)
LOOP_WRITE_FORMS = 12


class HuntAgent(Route):
    """A hunt- agent is find-only: no commit, git config write, alias or repo edit."""

    def call(
        self, agent: str, tool: str, tool_input: dict[str, str], cwd: str | None = None
    ) -> str:
        """A PreToolUse call of tool with tool_input by agent in the lead's session.

        In cwd when given, else in ev's directory.
        """
        extra = (
            f'"agent_id":"{agent}","tool_name":"{tool}",'
            f'"tool_input":{json.dumps(tool_input)},"transcript_path":"{self.LEAD}"'
        )
        if cwd is not None:
            extra += f',"cwd":{json.dumps(cwd)}'
        return ev("PreToolUse", "s1", extra)

    @override
    def setUp(self) -> None:
        """Agent h1 is `hunt-env`, agent e1 an exec- agent with no rulings file."""
        super().setUp()
        for agent, name in (("h1", "hunt-env"), ("e1", "exec-p9-01-a")):
            meta = f'{{"name":"{name}","agentType":"dsp-deep"}}\n'
            _ = self.write(self.SUB / f"agent-{agent}.meta.json", meta)
            _ = self.write(self.SUB / f"agent-{agent}.jsonl", human(-60) + "\n")

    def test_commit_and_config(self) -> None:
        """A commit, a git config write and an inline alias are refused; reads pass."""
        bash = "Bash"
        _ = self.hook(
            "deny:find-only", self.call("h1", bash, {"command": "git commit -m x"})
        )
        _ = self.hook(
            "silent", self.call("e1", bash, {"command": "git commit -m x"})
        )  # an exec- agent's commit is judged by its rulings alone
        self.ok("writing forms", len(CONFIG_WRITES) == CONFIG_WRITE_FORMS)
        writes = (
            *CONFIG_WRITES,
            "git config --global core.hooksPath h",
            "git -c alias.sv=commit sv -m x",
            "git --config-env alias.sv=X sv",
        )
        for command in writes:
            _ = self.hook("deny:find-only", self.call("h1", bash, {"command": command}))
        for command in (
            "git config --get user.name",
            "git config --list",
            "git config --show-origin --get user.name",
            "git config user.name",
            "git -c core.pager=cat log",
            "git config get user.name",
            "git status",
        ):
            _ = self.hook("silent", self.call("h1", bash, {"command": command}))

    def test_edits(self) -> None:
        """An edit in the repository outside the planning dir is refused."""
        inside = str(self.R / "src.py")
        _ = self.hook("deny:find-only", self.call("h1", "Write", {"file_path": inside}))
        _ = self.hook("deny:find-only", self.call("h1", "Edit", {"file_path": inside}))
        for allowed in (self.P / "hunt/findings/env.md", self.T / "clone/src.py"):
            for tool in ("Write", "Edit"):
                _ = self.hook(
                    "silent", self.call("h1", tool, {"file_path": str(allowed)})
                )
        home = self.HOME
        for config in (home / ".gitconfig", home / ".config/git/config"):
            _ = self.hook(
                "deny:find-only", self.call("h1", "Edit", {"file_path": str(config)})
            )

    def test_plumbing_and_indirection(self) -> None:
        """Plumbing commits and config indirection are held; unreadable fails."""
        bash = "Bash"
        self.ok("hunter git forms", len(HUNTER_GIT) == HUNTER_GIT_FORMS)
        for command in HUNTER_GIT:
            _ = self.hook("deny:find-only", self.call("h1", bash, {"command": command}))
        for command in (
            "git stash list",
            "git stash show",
            "git show HEAD",
            "git -c core.pager=cat log",
            "git --version",
        ):
            _ = self.hook("silent", self.call("h1", bash, {"command": command}))
        _ = self.hook(
            "silent", self.call("e1", bash, {"command": "git update-ref refs/x HEAD"})
        )  # held for hunters alone

    def test_redirects(self) -> None:
        """A redirect or tee into the repository outside the planning dir is refused."""
        bash, r, p, t = "Bash", self.R, self.P, self.T
        held = (
            f"echo x > {r}/src.py",
            f"git diff >> {r}/d.txt",
            f"git diff | tee -a {r}/d.txt",
            "echo x > src.py",  # relative to the call's directory, the repository
        )
        for command in held:
            _ = self.hook(
                "deny:find-only", self.call("h1", bash, {"command": command}, str(r))
            )
        for command in (
            f"echo x > {p}/hunt/n.md",
            f"git diff > {t}/clone.diff",
            "git diff > /dev/null",
            f"git diff | tee {t}/d.txt",
        ):
            _ = self.hook("silent", self.call("h1", bash, {"command": command}, str(r)))

    def test_for_loops(self) -> None:
        """A loop over literal words writes each target; a computed one is held."""
        bash, r, t = "Bash", self.R, self.T
        self.ok("loop forms", len(LOOP_WRITES) == LOOP_WRITE_FORMS)
        for form, want in LOOP_WRITES:
            command = form.format(r=r, t=t)
            _ = self.hook(want, self.call("h1", bash, {"command": command}, str(t)))

    def test_repo_aliases(self) -> None:
        """An alias the repository defines is judged by the command it runs."""
        repo = self.init_repo(self.T / "aliased")
        self.ok("alias forms", len(HELD_ALIASES) == HELD_ALIAS_FORMS)
        for name, value in (*HELD_ALIASES.items(), ("st", "status")):
            _ = self.git("-C", repo, "config", f"alias.{name}", value)
        for name in HELD_ALIASES:
            _ = self.hook(
                "deny:find-only",
                self.call("h1", "Bash", {"command": f"git {name}"}, str(repo)),
            )
        _ = self.hook(
            "deny:find-only",
            self.call("h1", "Bash", {"command": f"git -C {repo} sv"}),
        )
        _ = self.hook(
            "silent", self.call("h1", "Bash", {"command": "git st"}, str(repo))
        )

    def test_read_only_inside_the_repo(self) -> None:
        """Inside the hunted repository a hunter's git reads; its own clone is free."""
        bash, r = "Bash", str(self.R)
        clone = str(self.init_repo(self.T / "hunter-clone"))
        self.ok("read-only forms", len(READ_ONLY_GIT) == READ_ONLY_FORMS)
        self.ok("repo write forms", len(REPO_WRITES) == REPO_WRITE_FORMS)
        for command in READ_ONLY_GIT:
            _ = self.hook("silent", self.call("h1", bash, {"command": command}, r))
        for command in REPO_WRITES:
            _ = self.hook(
                "deny:find-only", self.call("h1", bash, {"command": command}, r)
            )
            _ = self.hook("silent", self.call("h1", bash, {"command": command}, clone))
        planning = str(self.P)  # git there still runs on the repository
        _ = self.hook(
            "deny:find-only",
            self.call("h1", bash, {"command": "git reset --hard"}, planning),
        )
        for command, want in (
            (f"cd {r} && git reset --hard", "deny:find-only"),
            (f"git -C {r} reset --hard", "deny:find-only"),
            ('cd "$X" && git status', "silent"),
            ('cd "$X" && git reset --hard', "deny:find-only"),
            ("pushd /x && git reset --hard", "deny:find-only"),
            ('echo x > "$UNKNOWN"/f', "deny:find-only"),
            (f"cd {r} && echo x > f", "deny:find-only"),
            ("X=/dev; echo x > $X/null", "silent"),
            ("echo x > $PWD/f", "silent"),
        ):
            _ = self.hook(want, self.call("h1", bash, {"command": command}, clone))
        for command, want in (
            (f"cd {clone} && git reset --hard && echo x > f", "silent"),
            (f"cd {clone} && git diff | tee d.txt", "silent"),
            ("(cd /x) && echo x > f", "deny:find-only"),
        ):
            _ = self.hook(want, self.call("h1", bash, {"command": command}, r))

    def test_clone_out_of_the_repo(self) -> None:
        """The brief's clone runs from the repository; a clone into it is held."""
        bash, r, out = "Bash", self.R, self.T / "hunt/env"
        clone = f"git clone -q file://{r} {out}"
        for cwd in (r, self.P, self.T):
            _ = self.hook("silent", self.call("h1", bash, {"command": clone}, str(cwd)))
        self.ok("clone forms", len(CLONE_INTO_REPO) == CLONE_INTO_REPO_FORMS)
        for form in CLONE_INTO_REPO:
            command = form.format(r=r, out=out)
            _ = self.hook(
                "deny:find-only", self.call("h1", bash, {"command": command}, str(r))
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


class MonitorOutputUnderTempRoot(Route):
    """A monitor's output, with no shell to say where, is read under the temp root.

    Claude Code's temp root is $CLAUDE_CODE_TMPDIR, else the system temp dir ($TMPDIR),
    joined with claude-<uid>.
    """

    def _idle(self, idle: str, var: str, root: Path) -> support.Result:
        """The hook on idle, with var naming root."""
        return self.py(
            support.RS,
            "--hook",
            input=idle + "\n",
            merge=True,
            env={var: str(root)},
        )

    def test_temp_root(self) -> None:
        """Each variable names the root a monitor's output is found under."""
        for n, var in enumerate(("CLAUDE_CODE_TMPDIR", "TMPDIR")):
            with self.subTest(var=var):
                root = self.T / f"root-{n}"
                tasks = root / f"claude-{os.getuid()}" / "p" / "s1" / "tasks"
                tasks.mkdir(parents=True)
                name = f"exec-p1-03-{n}"
                agent = f"a{name}-0123456789abcdef"
                tm = self.SUB / f"agent-{agent}.jsonl"
                _ = self.write(tm, "")
                self.append(
                    tm,
                    *call(
                        "m1",
                        "Monitor",
                        {"command": "tail -f g.log", "description": "gate"},
                        "Monitor started (task bmx1, expires in 30m unless the source "
                        "ends "
                        "first).",
                    ),
                )
                idle = ev(
                    "TeammateIdle",
                    "s1",
                    f'"teammate_name":"{name}","agent_id":"{agent}",'
                    f'"transcript_path":"{self.LEAD}"',
                )
                _ = self.write(tasks / "bmx1.output", "x\n")
                r = self._idle(idle, var, root)
                self.ok(
                    f"{var}: running",
                    r.code == SENT_BACK and "F92" in r.out,
                    r.out[:600],
                )
                _ = self.write(tasks / "bmx1.output", "x\n[exited with code 0]\n")
                r = self._idle(idle, var, root)
                self.ok(f"{var}: ended", r.code == 0 and not r.out.strip(), r.out[:600])


if __name__ == "__main__":
    _ = unittest.main()
