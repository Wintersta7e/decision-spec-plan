"""push_guard.py on a route's repository: which pushes it holds with no gate log, which gate logs
clear a push, and the command forms it reads as bash reads them (shell_cmd.py)."""

import json
import shutil
import time
import unittest

import support
from support import RS, grep

GREEN = "sha={} dirty=0\nok\nexit=0\n"


class GuardNoGateLog(support.Route):
    """A route of s1 on R, no gate log yet."""

    def test_route_active_no_gate_log(self):
        R, T = str(self.R), str(self.T)
        WT = f"{T}/wt"
        g = self.guard
        g(0, R, "ls -la")
        g(0, R, 'grep -rn "git push" .')
        g(2, R, "git push origin main")
        g(2, R, "git push")
        g(2, "/tmp", f"cd {R} && git push origin main")
        g(2, "/tmp", f"git -C {R} push origin main")
        g(2, WT, "git push origin feature")
        g(2, R, "git push --tags")
        g(0, R, "git push --dry-run origin main")
        g(0, R, "git push origin --delete old")
        g(0, R, "git push origin :old")
        # the bypass is the user's word: the lead's use asks them, a route agent never bypasses,
        # and a bypass spelled any other way is still checked
        g("ask", R, "DSP_SKIP_PUSH_GUARD=1 git push origin main")
        g(2, R, "DSP_SKIP_PUSH_GUARD=1 git push origin main", "a1")
        g(2, R, "DSP_SKIP_REVIEW=1 git push origin main", "a1")
        g(2, R, 'V=DSP_SKIP_PUSH_GUARD; env "$V=1" git push origin main')
        # a computed word that resolves to NAME=value is an assignment `env` makes, not the
        # command's name
        g(2, R, 'V=FOO; env "$V=1" git push origin main')
        # where the push runs: relative, chained and quoted `cd`s resolve from the cwd; an
        # unresolvable one is skipped, never replaced by the cwd
        g(2, T, "cd repo && git push origin main")
        g(2, "/tmp", f"cd {T} && cd repo && git push origin main")
        g(2, "/tmp", f'cd "{R}" && git push origin main')
        g(2, R, "echo abcd /tmp; git push origin main")
        g(0, R, "S=/tmp/x && cd $S && git push origin main")
        g(0, R, "cd /no-such-dir-dsp && git push origin main")
        # every push of a command is checked: a first push that sends nothing used to pass it all
        g(2, R, "git push --dry-run origin main && git push origin main")
        g(2, R, "git push origin --delete old; git push origin main")
        g(2, R, "git status && git push -n origin main\ngit push origin main")
        g(
            2,
            "/tmp",
            f"cd /no-such-dir-dsp && git push origin main; cd {R} && git push origin main",
        )
        g(2, R, f"cd $X && git push origin main; cd {R} && git push origin main")
        g(0, R, "git push --dry-run origin main && git push origin --delete old")

    def test_wrapped_and_escaped_pushes(self):
        # a `bash -c` or `eval` body after `&&` once took the outer operator for its every
        # command, so a failed `cd` inside it skipped the push; and `$'\u…'` was read as `u…`
        WT, g = f"{self.T}/wt", self.guard
        g(2, WT, "true && bash -c 'cd /no-such-dir-dsp; git push origin feature'")
        g(2, WT, "true && eval 'cd /no-such-dir-dsp; git push origin feature'")
        g(2, WT, "false || bash -c 'cd /no-such-dir-dsp; git push origin feature'")
        g(2, WT, f"git $'{chr(92)}u0070ush' origin feature")
        g(2, WT, f"git $'{chr(92)}U00000070ush' origin feature")
        g(2, WT, "git $'\\x70ush' origin feature")
        g(0, WT, "true && bash -c 'cd /no-such-dir-dsp && git push origin feature'")


class GuardGateLogs(support.Route):
    """A route of s1 on R with the gate logs section 152 leaves: a red and a dirty log on main,
    then a green one (wave1-int) that clears main only. Each test restores what it changes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lanes = cls.P / "lanes"
        cls.write(lanes / "red-gate.log", f"sha={cls.MAIN} dirty=0\n...\nexit=1\n")
        cls.write(lanes / "dirty-gate.log", f"sha={cls.MAIN} dirty=3\n...\nexit=0\n")
        cls.write(lanes / "wave1-int-gate.log", GREEN.format(cls.MAIN))
        cls.FEAT = cls.rev(cls.R, "feature")
        cls.S = cls.T / "scripts"
        cls.S.mkdir()

    def setUp(self):
        self.r, self.t = str(self.R), str(self.T)
        self.wt = f"{self.t}/wt"
        self.lanes = self.P / "lanes"

    def test_logs_and_holds(self):
        R, T, WT, lanes, g = self.r, self.t, self.wt, self.lanes, self.guard
        green = (lanes / "wave1-int-gate.log").read_text()
        self.rm(lanes / "wave1-int-gate.log", lanes / "dirty-gate.log")
        g(2, R, "git push origin main")
        self.write(lanes / "dirty-gate.log", f"sha={self.MAIN} dirty=3\n...\nexit=0\n")
        g(2, R, "git push origin main")
        self.write(lanes / "wave1-int-gate.log", green)
        g(0, R, "git push origin main")
        g(0, R, "git push origin HEAD:main")
        g(0, R, "git push -u origin main 2>&1")
        g(0, R, "git push -o ci.skip origin main")
        g(0, "/tmp", f"cd {R} && git push origin main")
        g(2, R, "git push origin main feature")
        g(2, WT, "git push origin feature")
        g(2, R, f"git push origin main && git -C {T}/wt push origin feature")
        g(0, R, "git push origin main; git push origin HEAD:main")
        # a sha= line with more fields after dirty=0 passes; a hold names each log and why
        tree = self.git("-C", R, "rev-parse", "main^{tree}")
        gl = self.git("-C", R, "commit-tree", "-m", "gl", tree, "-p", "main")
        self.git("-C", R, "branch", "gl", gl)
        log = lanes / "gl-gate.log"
        self.write(log, f"sha={gl} dirty=0 wt=lane-a\nok\nexit=0\n")
        g(0, R, "git push origin gl")
        self.write(log, f"sha={gl} dirty=2 wt=lane-b\nok\nexit=0\n")
        out = self.gmsg(R, "git push origin gl")
        self.ok(
            "the hold names a dirty log of the commit",
            grep(out, "gl-gate.log: .*dirty=2"),
            out,
        )
        self.write(log, f"sha={gl} dirty=0\nok\n")
        out = self.gmsg(R, "git push origin gl")
        self.ok(
            "the hold names a log with no exit= line",
            grep(out, "gl-gate.log: no exit= line"),
            out,
        )
        out = self.gmsg(WT, "git push origin feature")
        self.ok(
            "the hold says when no log names the commit",
            grep(out, "no gate log under .* names"),
            out,
        )
        self.rm(log)
        self.git("-C", R, "branch", "-q", "-D", "gl")
        # a directory named like a gate log is no log; a guard that crashes holds the push
        (lanes / "odd-gate.log").mkdir()
        g(0, R, "git push origin main")
        (lanes / "odd-gate.log").rmdir()
        stdin = json.dumps(
            {"tool_input": {"command": "git push origin main"}, "cwd": R}
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
            r.code == 2
            and grep(r.out, "the guard failed on this command (OSError: injected)"),
            r.out,
        )

    def test_tags_and_moved_refs(self):
        R, MAIN, g = self.r, self.MAIN, self.guard
        # a tag the same command creates before pushing it: its target is what goes out
        g(0, R, f"git tag v9 {MAIN} && git push origin v9 2>&1 | tail -2")
        g(0, R, 'git tag -a v9 -m "Release 9" main && git push origin v9')
        g(0, R, "git tag v9; git push origin v9")
        g(2, R, "git tag v9 feature && git push origin v9")
        g(2, R, "git tag -d v9 && git push origin v9")
        g(2, R, "git tag v8 main && git push origin v9")
        g(2, R, "git tag --merged=main v9 main && git push origin v9")
        g(2, R, "git tag v9 feature && git tag v9 main; git push origin v9")
        g(2, R, "git tag feature main && git push origin feature")
        g(0, R, "git tag -l 'v*' && git push origin main")
        # any other `git tag` holds: moving, deleting or re-making a tag, clustered flags
        self.git("-C", R, "tag", "v7", MAIN)
        g(2, R, "git tag -f v7 feature && git push origin v7")
        g(2, R, "git tag -af v7 -m x feature && git push origin v7")
        g(2, R, "git tag -d v7 && git tag v7 feature && git push origin v7")
        g(2, R, f"git -C {R} tag -f v7 feature && git push origin v7")
        g(2, R, "git tag v7 main; git push origin refs/tags/v7")
        self.git("-C", R, "tag", "-d", "v7")
        # a ref moved earlier in the command is not the one read now
        g(2, R, "git commit -qam x && git push origin main")
        g(2, R, "git checkout -q main; git push origin HEAD:main")
        g(2, R, f"git -C {R} merge -q feature && git push origin main")

    def test_unreadable_pushes(self):
        R, WT, g = self.r, self.wt, self.guard
        # what a push sends must be readable from the command: held otherwise
        g(2, R, "git push")
        g(2, R, "git push origin")
        g(2, R, "git -c remote.origin.mirror=true push origin main")
        g(2, R, "git --no-pager push origin main")
        g(2, R, f"git --git-dir={R}/.git push origin main")
        g(2, R, f"GIT_DIR={R}/.git git push origin main")
        g(
            2,
            R,
            "true && GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=push.default "
            "GIT_CONFIG_VALUE_0=matching git push origin main",
        )
        g(0, R, "DSP_X=1 git push origin main")
        g(0, R, "MY_GIT_X=1 true; git push origin main")
        g(0, "/tmp", f"git -C {R} push origin main")
        # from outside the route's repository, a held form may still push it
        g(2, "/tmp", f"git --git-dir={R}/.git push origin main")
        g(2, "/tmp", "git -c core.x=1 push origin main")
        g(2, "/tmp", f"export GIT_DIR={R}/.git; git push origin main")
        g(2, "/tmp", f"pushd {R} && git push origin main")
        # the command is read as bash reads it (shell_cmd.py)
        g(2, WT, "timeout 60 git push origin feature")
        g(2, WT, "env FOO=1 nice -n 5 git push origin feature")
        g(2, WT, "command git push origin feature")
        g(2, WT, "bash -c 'git push origin feature'")
        g(2, WT, "eval git push origin feature")
        g(2, WT, "for b in feature; do git push origin $b; done")
        g(2, WT, "! git push origin feature")
        g(2, WT, "{ git push origin feature; }")
        g(2, WT, r"\git push origin feature")
        g(2, WT, f"{shutil.which('git', path=self.env['PATH'])} push origin feature")
        g(2, WT, "'git' push origin feature")
        g(2, WT, "git \\\npush origin feature")
        g(2, WT, "echo $(git push origin feature)")
        g(2, WT, "echo `git push origin feature`")
        g(2, WT, "sudo git push origin feature")
        g(2, WT, "echo feature | xargs git push origin")
        g(2, WT, "if true; then git push origin feature; fi")
        g(0, R, "if true; then git push origin main; fi")
        g(0, R, 'git push origin "main"')
        g(0, R, 'echo "now run git push"')
        g(0, WT, "echo 'git push origin feature'; git log -1 --oneline")
        g(0, WT, "cat <<EOF\ngit push origin feature\nEOF")
        g(0, R, "git --no-pager log --grep push")
        g(0, "/tmp", "git --no-pager log --grep push")

    def test_where_it_runs(self):
        R, T, WT, g = self.r, self.t, self.wt, self.guard
        # a `cd` inside a subshell leaves the push where it was; a quoted `-C` path is read whole
        g(2, WT, "(cd /tmp && ls) && git push origin feature")
        self.git("-C", R, "worktree", "add", "-q", "--detach", f"{T}/w t", "feature")
        g(2, "/tmp", f'git -C "{T}/w t" push origin HEAD:feature')
        self.git("-C", R, "worktree", "remove", f"{T}/w t")
        # a directory the command computes is held; one it sets, or a fresh mktemp one, followed
        g(2, "/tmp", f"D={T}/wt; cd $D && git push origin feature")
        g(2, WT, 'cd "$(git rev-parse --show-toplevel)" && git push origin feature')
        g(0, WT, 'W=$(mktemp -d) && cd "$W" && git push origin feature')
        # refs moved earlier in the command, read-only uses of the same git commands
        g(2, R, "git fetch . feature:main && git push origin main")
        g(2, R, "git symbolic-ref HEAD refs/heads/feature && git push origin HEAD:main")
        g(0, R, "git fetch origin && git push origin main")
        g(0, R, "git branch --show-current && git push origin main")
        g(0, R, "git branch -a; git push origin main")
        g(2, R, "git branch tmp && git push origin main")
        g(0, R, "git checkout -- x.txt && git push origin main")
        # the matching refspec sends every branch both sides have
        g(2, R, "git push origin :")
        g(2, R, "git push origin +:")
        # a pipeline's commands and a backgrounded one run in subshells: their `cd` stays there
        g(2, WT, "cd /tmp | true; git push origin feature")
        g(2, WT, "cd /tmp & git push origin feature")
        g(2, WT, "{ cd /tmp; } | cat; git push origin feature")
        g(0, WT, "git log -1 | cat; cd /tmp && git push origin feature")
        # a `cd` that fails leaves the shell where it was; only an `&&` chain after it is skipped
        g(2, WT, "cd /no-such-dir-dsp; git push origin feature")
        g(2, WT, "cd /no-such-dir-dsp || true; git push origin feature")
        g(2, WT, "cd /no-such-dir-dsp && cd /no-such-dir-dsp2; git push origin feature")
        g(0, WT, "cd /no-such-dir-dsp && git push origin feature")
        g(0, WT, "cd /no-such-dir-dsp || exit 1; git push origin feature")

    def test_aliases(self):
        R, T, WT, g = self.r, self.t, self.wt, self.guard
        # an alias runs what it names: from the config, from `-c`, or a shell one
        self.git("-C", R, "config", "alias.pu", "push")
        self.git("-C", R, "config", "alias.sp", "!git push")
        g(2, WT, "git pu origin feature")
        g(0, R, "git pu origin main")
        g(2, WT, "git -c alias.x=push x origin feature")
        g(2, R, "git sp origin main")
        g(0, R, "git log -1 --oneline && git status --short")
        self.git("-C", R, "config", "--unset", "alias.pu")
        self.git("-C", R, "config", "--unset", "alias.sp")
        # any shell alias runs anything; a config the command points at may define one
        self.git("-C", R, "config", "alias.st", "!true")
        g(2, R, "git st")
        self.git("-C", R, "config", "--unset", "alias.st")
        self.write(self.T / "h/.gitconfig", "[alias]\n\tp = push\n")
        g(2, WT, f"git -c include.path={T}/h/.gitconfig p origin feature")
        g(2, WT, f"HOME={T}/h git p origin feature")
        g(2, WT, f"export XDG_CONFIG_HOME={T}/h; git p origin feature")
        # another repository's config (`--git-dir`), or one the command writes first
        self.git("-C", R, "config", "alias.p2", "push")
        g(2, "/tmp", f"git --git-dir={R}/.git p2 origin feature")
        self.git("-C", R, "config", "--unset", "alias.p2")
        g(2, WT, "git config alias.p3 push && git p3 origin feature")
        g(
            2,
            WT,
            r"printf '[alias]\n\tp3 = push\n' >>.git/config; git p3 origin feature",
        )
        g(
            2,
            WT,
            r"printf '[alias]\n\tp3 = push\n' >>.git/co\nfig; git p3 origin feature",
        )
        g(
            2,
            WT,
            r"""bash -c "printf '[alias]\\n\\tp3 = push\\n' >>.git/co\\nfig"; git p3 origin feature""",
        )
        g(2, WT, r"bash -c '$(echo git) p\ush origin feature'")
        # however deep the `bash -c` strings nest
        deep = r"$(echo git) p\ush origin feature"
        for _ in range(6):
            deep = "bash -c " + support.bash_q(deep)
        g(2, WT, deep)
        # ref moves the `--` rule missed
        g(2, R, "git checkout -B main feature -- && git push origin main")
        g(2, R, f"git worktree add -B main {T}/wb feature && git push origin main")
        g(2, R, "git bisect start feature main && git push origin HEAD:main")

    def test_computed_names(self):
        R, WT, g = self.r, self.wt, self.guard
        # a command name or git subcommand from a variable is read as its value
        g(2, WT, "G=git; $G push origin feature")
        g(2, WT, "P=push; git $P origin feature")
        g(0, R, "P=push; git $P origin main")
        g(2, WT, "git $UNSET_DSP_X origin feature")
        g(2, WT, "git $'push' origin feature")
        g(2, WT, r"git $'\x70ush' origin feature")
        g(2, WT, 'git $"push" origin feature')
        # a value bash splits into words, or an empty one bash drops, is no single word: held
        g(2, WT, "X='push origin feature'; git $X")
        g(2, WT, "X=; git $X push origin feature")
        # escapes that hide `git` and `push` from the raw text are read too
        g(2, WT, r"g\it p\ush origin feature")
        # text a shell runs that the guard cannot read is held when it may push
        g(2, WT, "X='git push origin feature'; bash -c \"$X\"")
        g(2, WT, "X='git push origin feature'; eval \"$X\"")
        g(2, WT, "echo 'git push origin feature' | bash")
        g(2, WT, "bash <<EOF\ngit push origin feature\nEOF")
        g(2, WT, "source ./push.sh")
        g(0, WT, "bash -c 'git log -1' && echo pushed")

    def test_scripts(self):
        R, T, WT, S, g = self.r, self.t, self.wt, self.S, self.guard
        # text that only names push is no push: the live false holds of 2026-10-31
        self.write(
            S / "env.sh", 'export NVM_DIR=x\nnvm_ls() { git -C "$NVM_DIR" fetch; }\n'
        )
        g(
            0,
            WT,
            f"cat > {T}/wf.yml <<EOF\non: {{events: push,schedule}}\nEOF\n"
            f"source {T}/scripts/env.sh && ls",
        )
        g(
            0,
            WT,
            f"for ev in push:none pull_request:none; do . {T}/scripts/env.sh; "
            "echo $ev; done",
        )
        g(0, WT, "node -e 'const a=[]; a.push(1)' & X=$(echo ls); bash -c \"$X\"")
        # a script file the command runs is read as the command is
        self.write(S / "ship.sh", f"cd {T}/wt\ngit push origin feature\n")
        g(2, R, f"bash {T}/scripts/ship.sh")
        g(2, WT, f"S={T}/scripts; bash $S/ship.sh")
        g(2, WT, f". {T}/scripts/ship.sh")
        self.write(S / "outer.sh", f"bash {T}/scripts/ship.sh\n")
        g(2, R, f"sh {T}/scripts/outer.sh")
        g(0, WT, f"bash {T}/scripts/env.sh && echo push")
        # a script run by its path is read too; one in another language is not shell text
        self.chmod_x(S / "ship.sh", S / "env.sh")
        g(2, R, f"{T}/scripts/ship.sh")
        g(0, WT, f"chmod +x {T}/scripts/env.sh && {T}/scripts/env.sh")
        self.write(
            S / "py.sh", '#!/usr/bin/env python3\nprint("git push origin feature")\n'
        )
        self.chmod_x(S / "py.sh")
        g(0, WT, f"{T}/scripts/py.sh")
        # a script the command writes before it runs it is held when the command may push
        self.write(S / "w.sh", "ls\n")
        g(
            2,
            WT,
            f"printf 'git push origin feature\\n' >{T}/scripts/w.sh; bash {T}/scripts/w.sh",
        )
        g(0, WT, f"printf 'ls\\n' >{T}/scripts/w.sh; bash {T}/scripts/w.sh")
        # the command's own state reaches the script it runs; a sourced script's comes back
        self.write(S / "main.sh", "git push origin main\n")
        g(0, R, f"bash {T}/scripts/main.sh")
        g(2, R, f"export GIT_DIR={R}/.git; bash {T}/scripts/main.sh")
        self.write(S / "moves.sh", "git branch -f main feature\n")
        g(2, R, f"bash {T}/scripts/moves.sh; git push origin main")
        # a script's own text naming push does not make its computed names pushes
        self.write(S / "noisy.sh", "X=$(ls); $X; echo push\n")
        g(0, WT, f"bash {T}/scripts/noisy.sh")
        # ...but a computed name or eval in it whose own words or values name push is held
        self.write(S / "hid1.sh", "$(echo git) push origin feature\n")
        self.write(S / "hid2.sh", 'X="git push origin feature"; $X\n')
        self.write(S / "hid3.sh", 'X="git push origin feature"; eval "$X"\n')
        for s in ("hid1", "hid2", "hid3"):
            g(2, WT, f"bash {T}/scripts/{s}.sh")
        # a child shell gets only exported variables: an unexported ref is empty there
        self.write(S / "ref.sh", "git push origin $DSP_REF\n")
        g(2, R, f"DSP_REF=main; bash {T}/scripts/ref.sh")
        g(0, R, f"export DSP_REF=main; bash {T}/scripts/ref.sh")
        g(0, R, f"DSP_REF=main; source {T}/scripts/ref.sh")
        # a probe shown then run from a review directory named for the push
        self.write(S / "p1-push7/probe.sh", "ls\n")
        g(
            0,
            WT,
            f"cat {T}/scripts/p1-push7/probe.sh; bash {T}/scripts/p1-push7/probe.sh",
        )
        self.write(S / "genv.sh", f"export GIT_DIR={R}/.git\n")
        g(2, R, f"source {T}/scripts/genv.sh; git push origin main")
        self.write(S / "towt.sh", f"cd {T}/wt\n")
        g(2, "/tmp", f". {T}/scripts/towt.sh; git push origin feature")
        g(0, "/tmp", f"bash {T}/scripts/towt.sh; git push origin feature")
        # a directory the command names before it changes into it may be one it creates
        self.rm(self.T / "lane-y", self.T / "wt/out", self.T / "wt/build")
        g(
            2,
            R,
            "git worktree add ../lane-y feature && cd ../lane-y && git push -u origin feature",
        )
        g(
            2,
            R,
            "git worktree add ../lane-y feature && git -C ../lane-y push -u origin feature",
        )
        g(2, WT, "mkdir -p out && cd out && make && cd .. && git push origin feature")
        g(2, WT, "mkdir -p build && cd build; cd .. && git push origin feature")
        g(0, R, "mkdir -p out && cd out && make && cd .. && git push origin main")

    def test_wrappers(self):
        R, T, WT, S, g = self.r, self.t, self.wt, self.S, self.guard
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
            g(2, WT, c)
        g(2, "/tmp", f"env -C {T}/wt git push origin feature")
        g(2, "/tmp", f"env --chdir={T}/wt git push origin feature")
        g(2, "/tmp", f"env -iC{T}/wt git push origin feature")
        # a GIT_* prefix holds in the script, shell string or sourced file it runs
        self.write(S / "pm.sh", "git push origin main\n")
        self.chmod_x(S / "pm.sh")
        g(0, R, f"bash {T}/scripts/pm.sh")
        for c in (
            f"GIT_DIR={R}/.git bash {T}/scripts/pm.sh",
            f"GIT_DIR={R}/.git {T}/scripts/pm.sh",
            f"GIT_DIR={R}/.git bash -c 'git push origin main'",
            f"GIT_DIR={R}/.git source {T}/scripts/pm.sh",
            f"env GIT_DIR={R}/.git bash {T}/scripts/pm.sh",
        ):
            g(2, R, c)
        # env -S reads `\t` as a separator and fills in `${VAR}`; getopt's long-option prefixes
        for c in (
            r"env -S 'git\tpush origin main'",
            "env -S 'git push ${R:-origin} main'",
            "strace --bogus git push origin main",
        ):
            g(2, R, c)
        g(0, R, "strace --str 64 git push origin main")
        g(2, R, "strace --out /tmp/t git push origin main")
        g(0, R, "timeout --preserve-status 5 git push origin main")
        g(2, WT, "strace --str 64 git push origin feature")
        self.write(S / "noop.sh", "true\n")
        g(
            2,
            "/tmp",
            f"export D={T}/wt; D=/tmp source {T}/scripts/noop.sh; "
            'cd "$D" && git push origin feature',
        )
        # a `cd` that fails leaves OLDPWD where the last one that worked set it
        g(2, WT, f"cd /tmp; cd {T}/no-such-dir; cd - && git push origin feature")
        g(0, R, "command -v git && git push origin main")
        # a script only read, shown or made executable before it runs is not written by it
        self.write(S / "build.sh", "echo hi\n")
        self.chmod_x(S / "build.sh")
        for c in (
            f"chmod +x {T}/scripts/build.sh && {T}/scripts/build.sh && git push origin main",
            f"cat {T}/scripts/build.sh; bash {T}/scripts/build.sh; git push origin main",
            (
                f"test -f {T}/scripts/build.sh && source {T}/scripts/build.sh "
                "&& git push origin main"
            ),
            f"git stash push && cat {T}/scripts/build.sh && bash {T}/scripts/build.sh",
        ):
            g(0, R, c)
        # a shell string read from a file runs that file's push
        g(2, R, f'sh -c "$(cat {T}/scripts/pm.sh)"')
        g(2, R, f'bash -c "$(<{T}/scripts/pm.sh)"')
        g(0, R, f'sh -c "$(cat {T}/scripts/build.sh)"')
        # one the command writes first, or one the guard cannot read, may hold anything
        g(
            2,
            R,
            f"printf 'echo hi\\\\n' >{T}/scripts/gen.sh; "
            f'sh -c "$(cat {T}/scripts/gen.sh)"',
        )
        g(2, R, f'sh -c "$(cat {T}/scripts/no-such.sh)"')

    def test_prefixes_refspecs_and_logs(self):
        R, WT, lanes, g = self.r, self.wt, self.lanes, self.guard
        # a GIT_* prefix sets the variable for its own command only; deleting a branch moves no
        # ref the push sends; `cd -` goes back where the last `cd` left
        for c in (
            "GIT_PAGER=cat git log --oneline -3 && git push origin main",
            "GIT_EDITOR=true git stash list; git push origin main",
            "git branch -d lane-x && git push origin main",
            "git branch -D old-lane; git push origin main",
            "cd /tmp && ls && cd - && git push origin main",
        ):
            g(0, R, c)
        g(2, R, "GIT_PAGER=cat git push origin main")
        g(2, R, "cd - && git push origin main")
        g(2, WT, "cd /tmp && cd - && git push origin feature")
        # git's own `tag <name>` refspec; a computed refspec named as such; a held form's hold
        # says no gate log clears it; a bare `-C` is no crash
        self.git("-C", R, "tag", "v1", "main")
        g(0, R, "git push origin tag v1")
        self.git("-C", R, "tag", "-d", "v1")
        out = self.gmsg(R, 'git push -u origin "$(git branch --show-current)"')
        self.ok(
            "the hold names a computed refspec",
            grep(out, "a refspec the command computes"),
            out,
        )
        out = self.gmsg("/tmp", f"git --git-dir={R}/.git push origin main")
        self.ok(
            "a held form's hold says a gate log will not clear it",
            grep(out, "No gate log clears")
            and not grep(out, "no full gate has passed"),
            out,
        )
        out = self.gmsg(R, "git -C")
        self.ok(
            "a bare git -C is no guard crash", not grep(out, "the guard failed"), out
        )
        # every command is read now, so a long line of git commands stays fast
        start = time.monotonic()
        g(0, WT, "git x; " * 3000)
        took = int(time.monotonic() - start)
        self.ok(f"3,000 git commands in one line are read in {took} s", took < 2)
        # a CI harness's log is no full gate; a marker that names no planning dir holds
        self.write(
            lanes / "f-it-gate.log",
            f"sha={self.FEAT} dirty=0\nharness=it\nok\nexit=0\n",
        )
        g(2, WT, "git push origin feature")
        self.rm(lanes / "f-it-gate.log")
        mk = self.MK(self.R)
        keep = mk.read_text()
        mk.write_text("{}\n")
        g(2, R, "git push origin main")
        mk.write_text(keep)
        # a gate whose codegen/build steps print before the sha= line
        late = lanes / "late-gate.log"
        builds = "".join(f"build {i}\n" for i in range(1, 21))
        self.write(late, builds + GREEN.format(self.FEAT))
        g(2, WT, "git push origin feature")
        builds = "".join(f"build {i}\n" for i in range(1, 6))
        self.write(late, builds + GREEN.format(self.FEAT))
        g(0, WT, "git push origin feature")
        self.rm(late)
        # a rerun's log named after the first one (`-gate2.log`) counts
        self.write(lanes / "p1-01-a-gate2.log", GREEN.format(self.FEAT))
        g(0, WT, "git push origin feature")
        self.rm(lanes / "p1-01-a-gate2.log")
        # a gate log larger than the memory the report may use is read line by line
        big = lanes / "big-gate.log"
        # `yes 'build output line' | head -c 300M`, then the exit line
        line = b"build output line\n"
        lines, rest = divmod(300 * 1024 * 1024, len(line))
        with open(big, "wb") as f:
            f.write(f"sha={self.FEAT} dirty=0\n".encode())
            f.writelines(line * 50000 for _ in range(lines // 50000))
            f.write(line * (lines % 50000) + line[:rest])
            f.write(b"\nexit=0\n")
        try:
            r = self.py(
                RS,
                self.P,
                "--phase",
                "1",
                "--repo",
                R,
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
    unittest.main()
