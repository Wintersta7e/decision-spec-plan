# SPDX-License-Identifier: MIT
"""push_guard.py on a route's repository.

Which pushes it holds with no gate log, which gate logs clear a push, and the command
forms it reads as bash reads them (shell_cmd.py).
"""

import json
import shutil
import tempfile
import time
import unittest
from typing import TYPE_CHECKING

from typing_extensions import override

import support
from support import RS, grep

if TYPE_CHECKING:
    from pathlib import Path

GREEN = "sha={} dirty=0\nok\nexit=0\n"
HELD = 2  # the exit code of a held push
FAST = 2  # the seconds a line of 3,000 git commands may take to read
OUTSIDE = tempfile.gettempdir()  # a cwd in no repository


class GuardNoGateLog(support.Route):
    """A route of s1 on R, no gate log yet."""

    def test_route_active_no_gate_log(self) -> None:
        """With no gate log every push is held; a bypass is asked or refused."""
        repo, root = str(self.R), str(self.T)
        wt = f"{root}/wt"
        g = self.guard
        _ = g(0, repo, "ls -la")
        _ = g(0, repo, 'grep -rn "git push" .')
        _ = g(2, repo, "git push origin main")
        _ = g(2, repo, "git push")
        _ = g(2, OUTSIDE, f"cd {repo} && git push origin main")
        _ = g(2, OUTSIDE, f"git -C {repo} push origin main")
        _ = g(2, wt, "git push origin feature")
        _ = g(2, repo, "git push --tags")
        _ = g(0, repo, "git push --dry-run origin main")
        _ = g(0, repo, "git push origin --delete old")
        _ = g(0, repo, "git push origin :old")
        # the bypass is the user's word: the lead's use asks them, a route agent never
        # bypasses, and a bypass spelled any other way is asked as the same skip
        _ = g("ask", repo, "DSP_SKIP_PUSH_GUARD=1 git push origin main")
        _ = g(2, repo, "DSP_SKIP_PUSH_GUARD=1 git push origin main", "a1")
        _ = g(2, repo, "DSP_SKIP_REVIEW=1 git push origin main", "a1")
        r = g("ask", repo, 'V=DSP_SKIP_PUSH_GUARD; env "$V=1" git push origin main')
        self.ok(
            "a computed spelling is asked as a guard skip", "the push guard" in r.out
        )
        _ = g(2, repo, 'V=DSP_SKIP_PUSH_GUARD; env "$V=1" git push origin main', "a1")
        # a computed word that resolves to NAME=value is an assignment `env` makes, not
        # the command's name
        _ = g(2, repo, 'V=FOO; env "$V=1" git push origin main')
        # where the push runs: relative, chained and quoted `cd`s resolve from the cwd;
        # an unresolvable one is skipped, never replaced by the cwd
        _ = g(2, root, "cd repo && git push origin main")
        _ = g(2, OUTSIDE, f"cd {root} && cd repo && git push origin main")
        _ = g(2, OUTSIDE, f'cd "{repo}" && git push origin main')
        _ = g(2, repo, "echo abcd /tmp; git push origin main")
        _ = g(0, repo, "S=/tmp/x && cd $S && git push origin main")
        _ = g(0, repo, "cd /no-such-dir-dsp && git push origin main")
        # every push of a command is checked: a first push that sends nothing used to
        # pass it all
        _ = g(2, repo, "git push --dry-run origin main && git push origin main")
        _ = g(2, repo, "git push origin --delete old; git push origin main")
        _ = g(2, repo, "git status && git push -n origin main\ngit push origin main")
        _ = g(
            2,
            OUTSIDE,
            "cd /no-such-dir-dsp && git push origin main; "
            f"cd {repo} && git push origin main",
        )
        _ = g(
            2, repo, f"cd $X && git push origin main; cd {repo} && git push origin main"
        )
        _ = g(0, repo, "git push --dry-run origin main && git push origin --delete old")

    def test_wrapped_and_escaped_pushes(self) -> None:
        """A push in a `bash -c` or `eval` body, or spelled with escapes, is held."""
        # a `bash -c` or `eval` body after `&&` once took the outer operator for its
        # every command, so a failed `cd` inside it skipped the push; and `$'\u…'` was
        # read as `u…`
        wt, g = f"{self.T}/wt", self.guard
        _ = g(2, wt, "true && bash -c 'cd /no-such-dir-dsp; git push origin feature'")
        _ = g(2, wt, "true && eval 'cd /no-such-dir-dsp; git push origin feature'")
        _ = g(2, wt, "false || bash -c 'cd /no-such-dir-dsp; git push origin feature'")
        _ = g(2, wt, f"git $'{chr(92)}u0070ush' origin feature")
        _ = g(2, wt, f"git $'{chr(92)}U00000070ush' origin feature")
        _ = g(2, wt, "git $'\\x70ush' origin feature")
        _ = g(0, wt, "true && bash -c 'cd /no-such-dir-dsp && git push origin feature'")


class GuardGateLogs(support.Route):
    """A route of s1 on R with the gate logs section 152 leaves.

    A red and a dirty log on main, then a green one (wave1-int) that clears main only.
    Each test restores what it changes.
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the three gate logs and make the scripts directory."""
        super().setUpClass()
        lanes = cls.P / "lanes"
        _ = cls.write(lanes / "red-gate.log", f"sha={cls.MAIN} dirty=0\n...\nexit=1\n")
        _ = cls.write(
            lanes / "dirty-gate.log", f"sha={cls.MAIN} dirty=3\n...\nexit=0\n"
        )
        _ = cls.write(lanes / "wave1-int-gate.log", GREEN.format(cls.MAIN))
        cls.FEAT: str = cls.rev(cls.R, "feature")
        cls.S: Path = cls.T / "scripts"
        cls.S.mkdir()
        cls.r: str = str(cls.R)
        cls.t: str = str(cls.T)
        cls.wt: str = f"{cls.t}/wt"
        cls.lanes: Path = lanes

    def test_logs_and_holds(self) -> None:
        """A green log of the commit clears its push; a hold names each log and why."""
        repo, root, wt, lanes, g = self.r, self.t, self.wt, self.lanes, self.guard
        green = (lanes / "wave1-int-gate.log").read_text()
        self.rm(lanes / "wave1-int-gate.log", lanes / "dirty-gate.log")
        _ = g(2, repo, "git push origin main")
        _ = self.write(
            lanes / "dirty-gate.log", f"sha={self.MAIN} dirty=3\n...\nexit=0\n"
        )
        _ = g(2, repo, "git push origin main")
        _ = self.write(lanes / "wave1-int-gate.log", green)
        _ = g(0, repo, "git push origin main")
        _ = g(0, repo, "git push origin HEAD:main")
        _ = g(0, repo, "git push -u origin main 2>&1")
        _ = g(0, repo, "git push -o ci.skip origin main")
        _ = g(0, OUTSIDE, f"cd {repo} && git push origin main")
        _ = g(2, repo, "git push origin main feature")
        _ = g(2, wt, "git push origin feature")
        _ = g(2, repo, f"git push origin main && git -C {root}/wt push origin feature")
        _ = g(0, repo, "git push origin main; git push origin HEAD:main")
        # a sha= line with more fields after dirty=0 passes; a hold names each log and
        # why
        tree = self.git("-C", repo, "rev-parse", "main^{tree}")
        gl = self.git("-C", repo, "commit-tree", "-m", "gl", tree, "-p", "main")
        _ = self.git("-C", repo, "branch", "gl", gl)
        log = lanes / "gl-gate.log"
        _ = self.write(log, f"sha={gl} dirty=0 wt=lane-a\nok\nexit=0\n")
        _ = g(0, repo, "git push origin gl")
        _ = self.write(log, f"sha={gl} dirty=2 wt=lane-b\nok\nexit=0\n")
        out = self.gmsg(repo, "git push origin gl")
        self.ok(
            "the hold names a dirty log of the commit",
            grep(out, "gl-gate.log: .*dirty=2"),
            out,
        )
        _ = self.write(log, f"sha={gl} dirty=0\nok\n")
        out = self.gmsg(repo, "git push origin gl")
        self.ok(
            "the hold names a log with no exit= line",
            grep(out, "gl-gate.log: no exit= line"),
            out,
        )
        out = self.gmsg(wt, "git push origin feature")
        self.ok(
            "the hold says when no log names the commit",
            grep(out, "no gate log under .* names"),
            out,
        )
        self.rm(log)
        _ = self.git("-C", repo, "branch", "-q", "-D", "gl")
        # a directory named like a gate log is no log; a guard that crashes holds the
        # push
        (lanes / "odd-gate.log").mkdir()
        _ = g(0, repo, "git push origin main")
        (lanes / "odd-gate.log").rmdir()
        stdin = json.dumps(
            {"tool_input": {"command": "git push origin main"}, "cwd": repo}
        )
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import push_guard as g\n"
            'def boom(*a): raise OSError("injected")\n'
            "g.walk = boom; sys.exit(g.main())"
        )
        r = self.run_(
            [support.PY, "-c", code, support.SCRIPTS], input=stdin, merge=True
        )
        self.ok(
            "a crash in the guard holds the push while a route is active",
            r.code == HELD
            and grep(r.out, "the guard failed on this command (OSError: injected)"),
            r.out,
        )

    def test_tags_and_moved_refs(self) -> None:
        """A tag or ref the command moves before its push is read as moved."""
        repo, main, g = self.r, self.MAIN, self.guard
        # a tag the same command creates before pushing it: its target is what goes out
        _ = g(0, repo, f"git tag v9 {main} && git push origin v9 2>&1 | tail -2")
        _ = g(0, repo, 'git tag -a v9 -m "Release 9" main && git push origin v9')
        _ = g(0, repo, "git tag v9; git push origin v9")
        _ = g(2, repo, "git tag v9 feature && git push origin v9")
        _ = g(2, repo, "git tag -d v9 && git push origin v9")
        _ = g(2, repo, "git tag v8 main && git push origin v9")
        _ = g(2, repo, "git tag --merged=main v9 main && git push origin v9")
        _ = g(2, repo, "git tag v9 feature && git tag v9 main; git push origin v9")
        _ = g(2, repo, "git tag feature main && git push origin feature")
        _ = g(0, repo, "git tag -l 'v*' && git push origin main")
        # any other `git tag` holds: moving, deleting or re-making a tag, clustered
        # flags
        _ = self.git("-C", repo, "tag", "v7", main)
        _ = g(2, repo, "git tag -f v7 feature && git push origin v7")
        _ = g(2, repo, "git tag -af v7 -m x feature && git push origin v7")
        _ = g(2, repo, "git tag -d v7 && git tag v7 feature && git push origin v7")
        _ = g(2, repo, f"git -C {repo} tag -f v7 feature && git push origin v7")
        _ = g(2, repo, "git tag v7 main; git push origin refs/tags/v7")
        _ = self.git("-C", repo, "tag", "-d", "v7")
        # a ref moved earlier in the command is not the one read now
        _ = g(2, repo, "git commit -qam x && git push origin main")
        _ = g(2, repo, "git checkout -q main; git push origin HEAD:main")
        _ = g(2, repo, f"git -C {repo} merge -q feature && git push origin main")

    def test_unreadable_pushes(self) -> None:
        """A push whose refs the command does not show is held."""
        repo, wt, g = self.r, self.wt, self.guard
        # what a push sends must be readable from the command: held otherwise
        _ = g(2, repo, "git push")
        _ = g(2, repo, "git push origin")
        _ = g(2, repo, "git -c remote.origin.mirror=true push origin main")
        _ = g(2, repo, "git --no-pager push origin main")
        _ = g(2, repo, f"git --git-dir={repo}/.git push origin main")
        _ = g(2, repo, f"GIT_DIR={repo}/.git git push origin main")
        _ = g(
            2,
            repo,
            "true && GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=push.default "
            "GIT_CONFIG_VALUE_0=matching git push origin main",
        )
        _ = g(0, repo, "DSP_X=1 git push origin main")
        _ = g(0, repo, "MY_GIT_X=1 true; git push origin main")
        _ = g(0, OUTSIDE, f"git -C {repo} push origin main")
        # from outside the route's repository, a held form may still push it
        _ = g(2, OUTSIDE, f"git --git-dir={repo}/.git push origin main")
        _ = g(2, OUTSIDE, "git -c core.x=1 push origin main")
        _ = g(2, OUTSIDE, f"export GIT_DIR={repo}/.git; git push origin main")
        _ = g(2, OUTSIDE, f"pushd {repo} && git push origin main")
        # the command is read as bash reads it (shell_cmd.py)
        _ = g(2, wt, "timeout 60 git push origin feature")
        _ = g(2, wt, "env FOO=1 nice -n 5 git push origin feature")
        _ = g(2, wt, "command git push origin feature")
        _ = g(2, wt, "bash -c 'git push origin feature'")
        _ = g(2, wt, "eval git push origin feature")
        _ = g(2, wt, "for b in feature; do git push origin $b; done")
        _ = g(2, wt, "! git push origin feature")
        _ = g(2, wt, "{ git push origin feature; }")
        _ = g(2, wt, r"\git push origin feature")
        _ = g(
            2, wt, f"{shutil.which('git', path=self.env['PATH'])} push origin feature"
        )
        _ = g(2, wt, "'git' push origin feature")
        _ = g(2, wt, "git \\\npush origin feature")
        _ = g(2, wt, "echo $(git push origin feature)")
        _ = g(2, wt, "echo `git push origin feature`")
        _ = g(2, wt, "sudo git push origin feature")
        _ = g(2, wt, "echo feature | xargs git push origin")
        _ = g(2, wt, "if true; then git push origin feature; fi")
        _ = g(0, repo, "if true; then git push origin main; fi")
        _ = g(0, repo, 'git push origin "main"')
        _ = g(0, repo, 'echo "now run git push"')
        _ = g(0, wt, "echo 'git push origin feature'; git log -1 --oneline")
        _ = g(0, wt, "cat <<EOF\ngit push origin feature\nEOF")
        _ = g(0, repo, "git --no-pager log --grep push")
        _ = g(0, OUTSIDE, "git --no-pager log --grep push")

    def test_where_it_runs(self) -> None:
        """A push is checked in the directory it runs in, as bash reaches it."""
        repo, root, wt, g = self.r, self.t, self.wt, self.guard
        # a `cd` inside a subshell leaves the push where it was; a quoted `-C` path is
        # read whole
        _ = g(2, wt, "(cd /tmp && ls) && git push origin feature")
        _ = self.git(
            "-C", repo, "worktree", "add", "-q", "--detach", f"{root}/w t", "feature"
        )
        _ = g(2, OUTSIDE, f'git -C "{root}/w t" push origin HEAD:feature')
        _ = self.git("-C", repo, "worktree", "remove", f"{root}/w t")
        # a directory the command computes is held; one it sets, or a fresh mktemp one,
        # followed
        _ = g(2, OUTSIDE, f"D={root}/wt; cd $D && git push origin feature")
        _ = g(2, wt, 'cd "$(git rev-parse --show-toplevel)" && git push origin feature')
        _ = g(0, wt, 'W=$(mktemp -d) && cd "$W" && git push origin feature')
        # refs moved earlier in the command, read-only uses of the same git commands
        _ = g(2, repo, "git fetch . feature:main && git push origin main")
        _ = g(
            2,
            repo,
            "git symbolic-ref HEAD refs/heads/feature && git push origin HEAD:main",
        )
        _ = g(0, repo, "git fetch origin && git push origin main")
        _ = g(0, repo, "git branch --show-current && git push origin main")
        _ = g(0, repo, "git branch -a; git push origin main")
        _ = g(2, repo, "git branch tmp && git push origin main")
        _ = g(0, repo, "git checkout -- x.txt && git push origin main")
        # the matching refspec sends every branch both sides have
        _ = g(2, repo, "git push origin :")
        _ = g(2, repo, "git push origin +:")
        # a pipeline's commands and a backgrounded one run in subshells: their `cd`
        # stays there
        _ = g(2, wt, "cd /tmp | true; git push origin feature")
        _ = g(2, wt, "cd /tmp & git push origin feature")
        _ = g(2, wt, "{ cd /tmp; } | cat; git push origin feature")
        _ = g(0, wt, "git log -1 | cat; cd /tmp && git push origin feature")
        # a `cd` that fails leaves the shell where it was; only an `&&` chain after it
        # is skipped
        _ = g(2, wt, "cd /no-such-dir-dsp; git push origin feature")
        _ = g(2, wt, "cd /no-such-dir-dsp || true; git push origin feature")
        _ = g(
            2,
            wt,
            "cd /no-such-dir-dsp && cd /no-such-dir-dsp2; git push origin feature",
        )
        _ = g(0, wt, "cd /no-such-dir-dsp && git push origin feature")
        _ = g(0, wt, "cd /no-such-dir-dsp || exit 1; git push origin feature")

    def test_aliases(self) -> None:
        """A git alias is read as what it runs, wherever its config comes from."""
        repo, root, wt, g = self.r, self.t, self.wt, self.guard
        # an alias runs what it names: from the config, from `-c`, or a shell one
        _ = self.git("-C", repo, "config", "alias.pu", "push")
        _ = self.git("-C", repo, "config", "alias.sp", "!git push")
        _ = g(2, wt, "git pu origin feature")
        _ = g(0, repo, "git pu origin main")
        _ = g(2, wt, "git -c alias.x=push x origin feature")
        _ = g(2, repo, "git sp origin main")
        _ = g(0, repo, "git log -1 --oneline && git status --short")
        _ = self.git("-C", repo, "config", "--unset", "alias.pu")
        _ = self.git("-C", repo, "config", "--unset", "alias.sp")
        # any shell alias runs anything; a config the command points at may define one
        _ = self.git("-C", repo, "config", "alias.st", "!true")
        _ = g(2, repo, "git st")
        _ = self.git("-C", repo, "config", "--unset", "alias.st")
        _ = self.write(self.T / "h/.gitconfig", "[alias]\n\tp = push\n")
        _ = g(2, wt, f"git -c include.path={root}/h/.gitconfig p origin feature")
        _ = g(2, wt, f"HOME={root}/h git p origin feature")
        _ = g(2, wt, f"export XDG_CONFIG_HOME={root}/h; git p origin feature")
        # another repository's config (`--git-dir`), or one the command writes first
        _ = self.git("-C", repo, "config", "alias.p2", "push")
        _ = g(2, OUTSIDE, f"git --git-dir={repo}/.git p2 origin feature")
        _ = self.git("-C", repo, "config", "--unset", "alias.p2")
        _ = g(2, wt, "git config alias.p3 push && git p3 origin feature")
        _ = g(
            2,
            wt,
            r"printf '[alias]\n\tp3 = push\n' >>.git/config; git p3 origin feature",
        )
        _ = g(
            2,
            wt,
            r"printf '[alias]\n\tp3 = push\n' >>.git/co\nfig; git p3 origin feature",
        )
        _ = g(
            2,
            wt,
            r"""bash -c "printf '[alias]\\n\\tp3 = push\\n' >>.git/co\\nfig"; """
            "git p3 origin feature",
        )
        _ = g(2, wt, r"bash -c '$(echo git) p\ush origin feature'")
        # however deep the `bash -c` strings nest
        deep = r"$(echo git) p\ush origin feature"
        for _ in range(6):
            deep = "bash -c " + support.bash_q(deep)
        _ = g(2, wt, deep)
        # ref moves the `--` rule missed
        _ = g(2, repo, "git checkout -B main feature -- && git push origin main")
        _ = g(
            2,
            repo,
            f"git worktree add -B main {root}/wb feature && git push origin main",
        )
        _ = g(2, repo, "git bisect start feature main && git push origin HEAD:main")

    def test_computed_names(self) -> None:
        """A name or subcommand from a variable is read as its value, or held."""
        repo, wt, g = self.r, self.wt, self.guard
        # a command name or git subcommand from a variable is read as its value
        _ = g(2, wt, "G=git; $G push origin feature")
        _ = g(2, wt, "P=push; git $P origin feature")
        _ = g(0, repo, "P=push; git $P origin main")
        _ = g(2, wt, "git $UNSET_DSP_X origin feature")
        _ = g(2, wt, "git $'push' origin feature")
        _ = g(2, wt, r"git $'\x70ush' origin feature")
        _ = g(2, wt, 'git $"push" origin feature')
        # a value bash splits into words, or an empty one bash drops, is no single word:
        # held
        _ = g(2, wt, "X='push origin feature'; git $X")
        _ = g(2, wt, "X=; git $X push origin feature")
        # escapes that hide `git` and `push` from the raw text are read too
        _ = g(2, wt, r"g\it p\ush origin feature")
        # text a shell runs that the guard cannot read is held when it may push
        _ = g(2, wt, "X='git push origin feature'; bash -c \"$X\"")
        _ = g(2, wt, "X='git push origin feature'; eval \"$X\"")
        _ = g(2, wt, "echo 'git push origin feature' | bash")
        _ = g(2, wt, "bash <<EOF\ngit push origin feature\nEOF")
        _ = g(2, wt, "source ./push.sh")
        _ = g(0, wt, "bash -c 'git log -1' && echo pushed")

    def test_scripts(self) -> None:
        """A script the command runs is read as the command is."""
        repo, root, wt, scripts, g = self.r, self.t, self.wt, self.S, self.guard
        # text that only names push is no push: the live false holds of 2026-10-31
        _ = self.write(
            scripts / "env.sh",
            'export NVM_DIR=x\nnvm_ls() { git -C "$NVM_DIR" fetch; }\n',
        )
        _ = g(
            0,
            wt,
            f"cat > {root}/wf.yml <<EOF\non: {{events: push,schedule}}\nEOF\n"
            f"source {root}/scripts/env.sh && ls",
        )
        _ = g(
            0,
            wt,
            f"for ev in push:none pull_request:none; do . {root}/scripts/env.sh; "
            "echo $ev; done",
        )
        _ = g(0, wt, "node -e 'const a=[]; a.push(1)' & X=$(echo ls); bash -c \"$X\"")
        # a script file the command runs is read as the command is
        _ = self.write(scripts / "ship.sh", f"cd {root}/wt\ngit push origin feature\n")
        _ = g(2, repo, f"bash {root}/scripts/ship.sh")
        _ = g(2, wt, f"S={root}/scripts; bash $S/ship.sh")
        _ = g(2, wt, f". {root}/scripts/ship.sh")
        _ = self.write(scripts / "outer.sh", f"bash {root}/scripts/ship.sh\n")
        _ = g(2, repo, f"sh {root}/scripts/outer.sh")
        _ = g(0, wt, f"bash {root}/scripts/env.sh && echo push")
        # a script run by its path is read too; one in another language is not shell
        # text
        self.chmod_x(scripts / "ship.sh", scripts / "env.sh")
        _ = g(2, repo, f"{root}/scripts/ship.sh")
        _ = g(0, wt, f"chmod +x {root}/scripts/env.sh && {root}/scripts/env.sh")
        _ = self.write(
            scripts / "py.sh",
            '#!/usr/bin/env python3\nprint("git push origin feature")\n',
        )
        self.chmod_x(scripts / "py.sh")
        _ = g(0, wt, f"{root}/scripts/py.sh")
        # a script the command writes before it runs it is held when the command may
        # push
        _ = self.write(scripts / "w.sh", "ls\n")
        _ = g(
            2,
            wt,
            f"printf 'git push origin feature\\n' >{root}/scripts/w.sh; "
            f"bash {root}/scripts/w.sh",
        )
        _ = g(0, wt, f"printf 'ls\\n' >{root}/scripts/w.sh; bash {root}/scripts/w.sh")
        # the command's own state reaches the script it runs; a sourced script's comes
        # back
        _ = self.write(scripts / "main.sh", "git push origin main\n")
        _ = g(0, repo, f"bash {root}/scripts/main.sh")
        _ = g(2, repo, f"export GIT_DIR={repo}/.git; bash {root}/scripts/main.sh")
        _ = self.write(scripts / "moves.sh", "git branch -f main feature\n")
        _ = g(2, repo, f"bash {root}/scripts/moves.sh; git push origin main")
        # a script's own text naming push does not make its computed names pushes
        _ = self.write(scripts / "noisy.sh", "X=$(ls); $X; echo push\n")
        _ = g(0, wt, f"bash {root}/scripts/noisy.sh")
        # ...but a computed name or eval in it whose own words or values name push is
        # held
        _ = self.write(scripts / "hid1.sh", "$(echo git) push origin feature\n")
        _ = self.write(scripts / "hid2.sh", 'X="git push origin feature"; $X\n')
        _ = self.write(scripts / "hid3.sh", 'X="git push origin feature"; eval "$X"\n')
        for s in ("hid1", "hid2", "hid3"):
            _ = g(2, wt, f"bash {root}/scripts/{s}.sh")
        # a child shell gets only exported variables: an unexported ref is empty there
        _ = self.write(scripts / "ref.sh", "git push origin $DSP_REF\n")
        _ = g(2, repo, f"DSP_REF=main; bash {root}/scripts/ref.sh")
        _ = g(0, repo, f"export DSP_REF=main; bash {root}/scripts/ref.sh")
        _ = g(0, repo, f"DSP_REF=main; source {root}/scripts/ref.sh")
        # a probe shown then run from a review directory named for the push
        _ = self.write(scripts / "p1-push7/probe.sh", "ls\n")
        _ = g(
            0,
            wt,
            f"cat {root}/scripts/p1-push7/probe.sh; "
            f"bash {root}/scripts/p1-push7/probe.sh",
        )
        _ = self.write(scripts / "genv.sh", f"export GIT_DIR={repo}/.git\n")
        _ = g(2, repo, f"source {root}/scripts/genv.sh; git push origin main")
        _ = self.write(scripts / "towt.sh", f"cd {root}/wt\n")
        _ = g(2, OUTSIDE, f". {root}/scripts/towt.sh; git push origin feature")
        _ = g(0, OUTSIDE, f"bash {root}/scripts/towt.sh; git push origin feature")
        # a directory the command names before it changes into it may be one it
        # creates
        self.rm(self.T / "lane-y", self.T / "wt/out", self.T / "wt/build")
        _ = g(
            2,
            repo,
            "git worktree add ../lane-y feature && cd ../lane-y && "
            "git push -u origin feature",
        )
        _ = g(
            2,
            repo,
            "git worktree add ../lane-y feature && "
            "git -C ../lane-y push -u origin feature",
        )
        _ = g(
            2, wt, "mkdir -p out && cd out && make && cd .. && git push origin feature"
        )
        _ = g(2, wt, "mkdir -p build && cd build; cd .. && git push origin feature")
        _ = g(
            0, repo, "mkdir -p out && cd out && make && cd .. && git push origin main"
        )

    def test_wrappers(self) -> None:
        """Wrappers, their flags and GIT_* prefixes hide no push."""
        repo, root, wt, scripts, g = self.r, self.t, self.wt, self.S, self.guard
        # a one-line `function f { … }`, `time`'s options, wrappers' flags hide no push
        for c in (
            "function f { git push origin feature; }; f",
            "time -p git push origin feature",
            "time -- git push origin feature",
            "timeout -v 120 git push origin feature",
            "ssh-agent bash -c 'ssh-add -q k; git push origin feature'",
            "op run -- git push origin feature",
            "direnv exec . git push origin feature",
            "nix develop -c git push origin feature",
            "chronic git push origin feature",
            "unbuffer git push origin feature",
            "strace -f -o /tmp/t git push origin feature",
            "taskset -c 0 git push origin feature",
            "uv run git push origin feature",
            "coproc git push origin feature",
            "env -S 'git push origin feature'",
            "strace -fo /tmp/t git push origin feature",
            "strace --output /tmp/t git push origin feature",
            "timeout -s9 5 git push origin feature",
            "env -vS 'git push origin feature'",
            "env '-Sgit push origin feature'",
            r"env -S 'git\_push origin feature'",
            "coproc P { git push origin feature; }",
            "coproc { git push origin feature; }",
        ):
            _ = g(2, wt, c)
        _ = g(2, OUTSIDE, f"env -C {root}/wt git push origin feature")
        _ = g(2, OUTSIDE, f"env --chdir={root}/wt git push origin feature")
        _ = g(2, OUTSIDE, f"env -iC{root}/wt git push origin feature")
        # a GIT_* prefix holds in the script, shell string or sourced file it runs
        _ = self.write(scripts / "pm.sh", "git push origin main\n")
        self.chmod_x(scripts / "pm.sh")
        _ = g(0, repo, f"bash {root}/scripts/pm.sh")
        for c in (
            f"GIT_DIR={repo}/.git bash {root}/scripts/pm.sh",
            f"GIT_DIR={repo}/.git {root}/scripts/pm.sh",
            f"GIT_DIR={repo}/.git bash -c 'git push origin main'",
            f"GIT_DIR={repo}/.git source {root}/scripts/pm.sh",
            f"env GIT_DIR={repo}/.git bash {root}/scripts/pm.sh",
        ):
            _ = g(2, repo, c)
        # env -S reads `\t` as a separator and fills in `${VAR}`; getopt's long-option
        # prefixes
        for c in (
            r"env -S 'git\tpush origin main'",
            "env -S 'git push ${R:-origin} main'",
            "strace --bogus git push origin main",
        ):
            _ = g(2, repo, c)
        _ = g(0, repo, "strace --str 64 git push origin main")
        _ = g(2, repo, "strace --out /tmp/t git push origin main")
        _ = g(0, repo, "timeout --preserve-status 5 git push origin main")
        _ = g(2, wt, "strace --str 64 git push origin feature")
        _ = self.write(scripts / "noop.sh", "true\n")
        _ = g(
            2,
            OUTSIDE,
            f"export D={root}/wt; D=/tmp source {root}/scripts/noop.sh; "
            'cd "$D" && git push origin feature',
        )
        # a `cd` that fails leaves OLDPWD where the last one that worked set it
        _ = g(2, wt, f"cd /tmp; cd {root}/no-such-dir; cd - && git push origin feature")
        _ = g(0, repo, "command -v git && git push origin main")
        # a script only read, shown or made executable before it runs is not written by
        # it
        _ = self.write(scripts / "build.sh", "echo hi\n")
        self.chmod_x(scripts / "build.sh")
        for c in (
            (
                f"chmod +x {root}/scripts/build.sh && {root}/scripts/build.sh "
                "&& git push origin main"
            ),
            (
                f"cat {root}/scripts/build.sh; bash {root}/scripts/build.sh; "
                "git push origin main"
            ),
            (
                f"test -f {root}/scripts/build.sh && source {root}/scripts/build.sh "
                "&& git push origin main"
            ),
            (
                f"git stash push && cat {root}/scripts/build.sh && "
                f"bash {root}/scripts/build.sh"
            ),
        ):
            _ = g(0, repo, c)
        # a shell string read from a file runs that file's push
        _ = g(2, repo, f'sh -c "$(cat {root}/scripts/pm.sh)"')
        _ = g(2, repo, f'bash -c "$(<{root}/scripts/pm.sh)"')
        _ = g(0, repo, f'sh -c "$(cat {root}/scripts/build.sh)"')
        # one the command writes first, or one the guard cannot read, may hold anything
        _ = g(
            2,
            repo,
            f"printf 'echo hi\\\\n' >{root}/scripts/gen.sh; "
            f'sh -c "$(cat {root}/scripts/gen.sh)"',
        )
        _ = g(2, repo, f'sh -c "$(cat {root}/scripts/no-such.sh)"')

    def test_prefixes_refspecs_and_logs(self) -> None:
        """Prefixes, refspecs and odd gate logs, each read as git and gate.py mean."""
        repo, wt, lanes, g = self.r, self.wt, self.lanes, self.guard
        # a GIT_* prefix sets the variable for its own command only; deleting a branch
        # moves no ref the push sends; `cd -` goes back where the last `cd` left
        for c in (
            "GIT_PAGER=cat git log --oneline -3 && git push origin main",
            "GIT_EDITOR=true git stash list; git push origin main",
            "git branch -d lane-x && git push origin main",
            "git branch -D old-lane; git push origin main",
            "cd /tmp && ls && cd - && git push origin main",
        ):
            _ = g(0, repo, c)
        _ = g(2, repo, "GIT_PAGER=cat git push origin main")
        _ = g(2, repo, "cd - && git push origin main")
        _ = g(2, wt, "cd /tmp && cd - && git push origin feature")
        # git's own `tag <name>` refspec; a computed refspec named as such; a held
        # form's hold says no gate log clears it; a bare `-C` is no crash
        _ = self.git("-C", repo, "tag", "v1", "main")
        _ = g(0, repo, "git push origin tag v1")
        _ = self.git("-C", repo, "tag", "-d", "v1")
        out = self.gmsg(repo, 'git push -u origin "$(git branch --show-current)"')
        self.ok(
            "the hold names a computed refspec",
            grep(out, "a refspec the command computes"),
            out,
        )
        out = self.gmsg(OUTSIDE, f"git --git-dir={repo}/.git push origin main")
        self.ok(
            "a held form's hold says a gate log will not clear it",
            grep(out, "No gate log clears")
            and not grep(out, "no full gate has passed"),
            out,
        )
        out = self.gmsg(repo, "git -C")
        self.ok(
            "a bare git -C is no guard crash", not grep(out, "the guard failed"), out
        )
        # every command is read now, so a long line of git commands stays fast. Timed
        # untraced: coverage's tracer, which reaches each script through the COVERAGE_
        # variables, tripled the guard's time on 3.11 and failed CI
        event = {"tool_input": {"command": "git x; " * 3000}, "cwd": str(wt)}
        untraced = [k for k in self.env if k.startswith("COVERAGE_")]
        start = time.monotonic()
        r = self.py(support.GUARD, input=json.dumps(event), merge=True, unset=untraced)
        took = time.monotonic() - start
        self.ok(
            f"3,000 git commands in one line are read in {took:.1f} s",
            r.code == 0 and not r.out and took < FAST,
            f"exit {r.code}: {r.out[:600]}",
        )
        # a CI harness's log is no full gate; a marker that names no planning dir holds
        _ = self.write(
            lanes / "f-it-gate.log",
            f"sha={self.FEAT} dirty=0\nharness=it\nok\nexit=0\n",
        )
        _ = g(2, wt, "git push origin feature")
        self.rm(lanes / "f-it-gate.log")
        mk = self.MK(self.R)
        keep = mk.read_text()
        _ = mk.write_text("{}\n")
        _ = g(2, repo, "git push origin main")
        _ = mk.write_text(keep)
        # a gate whose codegen/build steps print before the sha= line
        late = lanes / "late-gate.log"
        builds = "".join(f"build {i}\n" for i in range(1, 21))
        _ = self.write(late, builds + GREEN.format(self.FEAT))
        _ = g(2, wt, "git push origin feature")
        builds = "".join(f"build {i}\n" for i in range(1, 6))
        _ = self.write(late, builds + GREEN.format(self.FEAT))
        _ = g(0, wt, "git push origin feature")
        self.rm(late)
        # a rerun's log named after the first one (`-gate2.log`) counts
        _ = self.write(lanes / "p1-01-a-gate2.log", GREEN.format(self.FEAT))
        _ = g(0, wt, "git push origin feature")
        self.rm(lanes / "p1-01-a-gate2.log")
        self.big_gate_log_is_read_by_line()

    def big_gate_log_is_read_by_line(self) -> None:
        """A gate log larger than the report's memory is read line by line."""
        big = self.lanes / "big-gate.log"
        # `yes 'build output line' | head -c 300M`, then the exit line
        line = b"build output line\n"
        lines, rest = divmod(300 * 1024 * 1024, len(line))
        with big.open("wb") as f:
            _ = f.write(f"sha={self.FEAT} dirty=0\n".encode())
            f.writelines(line * 50000 for _ in range(lines // 50000))
            _ = f.write(line * (lines % 50000) + line[:rest])
            _ = f.write(b"\nexit=0\n")
        try:
            r = self.py(
                RS,
                self.P,
                "--phase",
                "1",
                "--repo",
                self.r,
                merge=True,
                memory=250000 * 1024,
            )
        finally:
            self.rm(big)
        self.ok(
            "a 300 MB gate log is reported under a 250 MB memory cap",
            not grep(r.out, "Traceback") and grep(r.out, "gates +[0-9]+ green", E=True),
            r.out[-600:],
        )


if __name__ == "__main__":
    _ = unittest.main()
