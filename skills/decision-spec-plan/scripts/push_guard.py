#!/usr/bin/env python3
"""PreToolUse:Bash — while a decision-spec-plan route is active in a repository
(<git-common-dir>/dsp-route-<id>.json, written by `route_state.py --activate`), a `git push` may only
send commits the full gate passed: a gate log under <planning-dir>/lanes/ that names no CI harness,
whose first `sha=` line, within its first 20 lines (codegen or a build may print first), is
`sha=<that commit> dirty=0` and whose last `exit=` line is `exit=0`.

With the sins on (`--sins on` in the marker: rung L's phase-end push, or a review the user asked
for) the push also needs a seven-sins review that covers it: a verdict under
<planning-dir>/reviews/ whose first 10 lines hold `reviewed=<sha> base=<sha> blocking=0` (full
SHAs), the reviewed commit an ancestor of the pushed one, every commit between them on an `after=`
line (fixes made after the review), and the base an ancestor of the remote-tracking ref — or, for
a branch the remote lacks, of one of that remote's tracking refs (nothing older than the base is
unsent). A review of more than 30 commits counts only with a `slices=` line whose ranges, each at
most 30 commits, cover every commit of it (sins/lead.md: one review per slice).

With a CI harness in the marker (`--ci-harness <label>`: a suite CI runs that the local gate does
not) the push also needs a passing gate log for that commit whose first 20 lines hold
`harness=<label>`.

Every `git push` the command runs is checked — inside `if`/`for`, `( )`, `$( )`, `bash -c`, `eval`
and pass-through wrappers (`env`, `timeout`, …) too — each in the repository its `cd`s and `-C`s
reach (shell_cmd.py reads the command as bash does: a pipeline's `cd` stays in its subshell, a `cd`
that fails skips only its `&&` chain), and a git alias is read as what it runs. What a push would
send must be readable from the command, so these are held: a push with no refspec or the matching
refspec `:`, git options before `push` other than `-C <dir>`, a GIT_* variable set before it, a
`pushd`/`popd`, a directory the command computes (`cd "$(…)"`, a variable it does not set), a
push run through `sudo`, `xargs` or the like, a command name or git subcommand the command
computes, a shell alias that runs git, a script, stdin or computed string fed to a shell (when
the command names `push`), and a ref-moving git command (`commit`, `fetch . a:b`, `checkout -B`,
…) earlier in the command. A held form is held wherever it runs while any route on the account is
active, since it can point at a route's repository from outside it. A `cd` to a fresh `mktemp`
directory leaves the push in no route's repository.

Why: on 2026-10-07 a lead pushed main twice without a gate and both CI runs went red; CI confirms a
state already proven green locally, it never discovers one (failure-modes F56). A finished lane
whose full gate was green still carried two new high defects a review found (F70). The bash guard
read the command with regexes until 2026-10-30, and a probe passed `timeout 60 git push`,
`git fetch . lane:main && git push`, `(cd x && ls) && git push`, `git push origin :` and a quoted
`-C` path, while it held `if …; then git push` and `git log --grep push`.

Bypass, only on the user's explicit word: DSP_SKIP_PUSH_GUARD=1 in the command skips both checks;
DSP_SKIP_REVIEW=1 skips only the review.
"""

import functools
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys

from shell_cmd import TEMP, Cmd, events, git_args, literal

REGISTRY = pathlib.Path.home() / ".claude" / "dsp-routes"
SLICE_MAX = 30
# Git commands that move a ref the push may name: read now, the ref is not what the push sends.
MOVES = {
    "commit",
    "merge",
    "rebase",
    "reset",
    "cherry-pick",
    "revert",
    "am",
    "pull",
    "checkout",
}
MOVES |= {
    "switch",
    "update-ref",
    "branch",
    "fetch",
    "symbolic-ref",
    "replace",
    "filter-branch",
    "bisect",
}
# Frequent git commands, so an alias lookup runs only for a rare name: git runs no alias named
# like a command of its own.
COMMON = MOVES | {
    "push",
    "tag",
    "status",
    "log",
    "diff",
    "show",
    "add",
    "rm",
    "mv",
    "config",
}
COMMON |= {
    "rev-parse",
    "rev-list",
    "init",
    "clone",
    "remote",
    "stash",
    "grep",
    "worktree",
}
COMMON |= {"ls-files", "describe", "restore", "notes", "blame", "clean", "merge-base"}
# `git branch` options that only list.
BRANCH_LISTS = re.compile(
    r"-[arlv]+|--(all|remotes|list|verbose|show-current|no-color|no-column|ignore-case|omit-empty)"
    r"|--(color|column|abbrev|format|sort|contains|no-contains|merged|no-merged|points-at)(=.*)?"
)
# Commands that run their arguments as a command line this guard cannot follow.
OPAQUE = {
    "sudo",
    "doas",
    "su",
    "runuser",
    "xargs",
    "parallel",
    "watch",
    "ssh",
    "flock",
    "chroot",
}
OPAQUE |= {"nsenter", "unshare", "script", "find", "watchexec", "entr"}
MISSING_DIR = "\0missing"


def git(repo, *args):
    p = subprocess.run(
        ["git", "-C", repo, *args], check=False, capture_output=True, text=True
    )
    return p.stdout.strip() if p.returncode == 0 else None


def commit(repo, rev):
    return git(repo, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}")


def head_lines(path, n):
    with open(path, errors="replace", newline="\n") as f:
        return [ln.rstrip("\n").replace("\r", "") for _, ln in zip(range(n), f)]


def gated(planning, sha, harness=None):
    """A gate log for sha that passed; with harness, one that names it, else one that names none."""
    for log in sorted(pathlib.Path(planning, "lanes").glob("*-gate*.log")):
        if not log.is_file():
            continue
        head = head_lines(log, 20)
        if (
            next((ln for ln in head if ln.startswith("sha=")), None)
            != f"sha={sha} dirty=0"
        ):
            continue
        named = [ln for ln in head if ln.startswith("harness=")]
        if (f"harness={harness}" not in named) if harness else named:
            continue
        last = None
        with open(log, errors="replace", newline="\n") as f:
            for ln in f:
                if re.fullmatch(r"exit=[0-9]+\s*", ln):
                    last = ln.strip()
        if last == "exit=0":
            return True
    return False


def covered(repo, base, reviewed, slices):
    """A review of more than SLICE_MAX commits counts only as slices (`<from>..<to>`, full SHAs) of
    at most SLICE_MAX that cover every commit: review recall collapses on a large diff. Merge commits
    are not counted — a lane split along its own history leaves its merge in no two-dot range."""

    def commits(spec):
        return set((git(repo, "rev-list", "--no-merges", spec) or "").split())

    if not slices:
        return len(commits(f"{base}..{reviewed}")) <= SLICE_MAX
    seen = set()
    for s in slices:
        if not re.fullmatch(r"[0-9a-f]{40}\.\.[0-9a-f]{40}", s):
            return False
        part = commits(s)
        if len(part) > SLICE_MAX:
            return False
        seen |= part
    return commits(f"{base}..{reviewed}") <= seen


def reviewed(repo, planning, sha, remote, onto):
    """A verdict that covers sha; onto is the remote-tracking commit of the pushed branch, if any."""
    for v in sorted(pathlib.Path(planning, "reviews").glob("*-verdict.md")):
        if not v.is_file():
            continue
        head = head_lines(v, 10)
        stamp = next(
            (
                m
                for ln in head
                if (
                    m := re.fullmatch(
                        r"reviewed=([0-9a-f]{40}) base=([0-9a-f]{40}) blocking=0\s*", ln
                    )
                )
            ),
            None,
        )
        if not stamp:
            continue
        r, b = stamp.groups()
        if git(repo, "merge-base", "--is-ancestor", r, sha) is None:
            continue
        after = next((ln for ln in head if ln.startswith("after=")), "after=")
        fixes = set(re.split(r"[ ,]+", after.partition("=")[2].strip()))
        if set((git(repo, "rev-list", f"{r}..{sha}") or "").split()) - fixes:
            continue
        if onto:
            if git(repo, "merge-base", "--is-ancestor", b, onto) is None:
                continue
        # a branch the remote lacks: the base must be on the remote already, under any of its refs
        elif git(repo, "rev-list", "-n1", b, "--not", f"--remotes={remote}") != "":
            continue
        line = next((ln for ln in head if ln.startswith("slices=")), "slices=")
        slices = [s for s in re.split(r"[ ,]+", line.partition("=")[2].strip()) if s]
        if covered(repo, b, r, slices):
            return True
    return False


def active_route():
    """The marker of any route registered on this account (route_state.py --activate) that is
    still active."""
    for f in sorted(REGISTRY.glob("*.json")):
        try:
            marker = json.loads(f.read_text(errors="replace")).get("marker")
        except (ValueError, AttributeError):
            continue
        if marker and os.path.isfile(marker):
            return marker
    return None


def route_marker(repo, session):
    """The pushing session's own route when it runs in repo, else the newest route there: two
    routes in one repository each have a marker (route_state.py --activate, F93)."""
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return None
    try:
        mine = json.loads((REGISTRY / f"{session}.json").read_text()).get("marker")
    except (OSError, ValueError, AttributeError):
        mine = None
    if mine and os.path.isfile(mine) and os.path.dirname(mine) == common:
        return mine
    found = sorted(
        pathlib.Path(common).glob("dsp-route*.json"), key=lambda p: p.stat().st_mtime
    )
    return str(found[-1]) if found else None


def cd(state, target):
    """The directory after `cd target` from state: a path, None (computed by the command) or
    MISSING_DIR (a directory that does not exist, or a fresh temp one)."""
    if target is None:
        return None
    if TEMP in target:
        return MISSING_DIR
    if not target.startswith("/"):
        if state is None or state == MISSING_DIR:
            return state
        target = os.path.join(state, target)
    return os.path.normpath(target) if os.path.isdir(target) else MISSING_DIR


def new_tags(repo, tags):
    """{name: commit} of the tags `git tag` earlier in the command creates, or None. Only
    `git tag [-a|-s] [-m <msg>|-F <file>|-u <key>] <new name> [<rev>]` is read, and a listing
    passes; any other `git tag` (a move, a delete, clustered flags, git options) is None, which
    holds the push. Why: `git tag v1 <sha> && git push origin v1` was held because v1 did not exist
    yet."""
    out = {}
    for opts, args in tags:
        if opts:
            return None
        name = rev = None
        skip = False
        for w in args:
            if skip:
                skip = False
            elif re.fullmatch(
                r"-l|--list|-n.*|--(points-at|contains|no-contains|merged|no-merged)(=.*)?",
                w,
            ):
                break
            elif w in ("-a", "-s", "--annotate", "--sign"):
                pass
            elif w in ("-m", "-F", "-u", "--message", "--file", "--local-user"):
                skip = True
            elif w.startswith("-"):
                return None
            elif name is None:
                name = w
            elif rev is None:
                rev = w
            else:
                return None
        else:
            # `git tag` alone lists; a name that exists already or twice is a move or a refusal
            if name is None:
                continue
            if name in out or commit(repo, f"refs/tags/{name}"):
                return None
            out[name] = commit(repo, rev or "HEAD")
    return out


def moves(sub, args):
    """Whether `git <sub> <args>` moves a ref."""
    if sub == "branch":
        listing = all(BRANCH_LISTS.fullmatch(a) for a in args if a.startswith("-"))
        positional = [a for a in args if not a.startswith("-")]
        return not (listing and (not positional or {"-l", "--list"} & set(args)))
    if sub == "checkout":
        return "--" not in args or bool(
            {"-b", "-B", "--orphan", "--detach"} & set(args)
        )
    if sub == "worktree":
        return args[:1] == ["add"] and bool({"-b", "-B", "--orphan"} & set(args))
    if sub == "fetch":
        # a refspec with a destination, or the repository itself as the remote, writes local refs
        positional = [a for a in args if not a.startswith("-")]
        return positional[:1] == ["."] or any(":" in a for a in positional[1:])
    return sub in MOVES


@functools.cache
def builtins():
    """Every git command's name: git never runs an alias named like one."""
    return set((git(os.path.expanduser("~"), "--list-cmds=main,others") or "").split())


def unalias(repo, sub, args, opts, git_env):
    """(subcommand, args, None) with an alias replaced by what it runs, from `-c alias.<name>=` or
    the config; a held form in the third place when the alias cannot be read: a shell alias
    (`!…`) that runs git, a config the command line or a GIT_* variable may set, a loop."""
    for _ in range(10):
        if not sub or sub in COMMON or sub in builtins():
            return sub, args, None
        value = None
        for opt, w in opts:
            if opt.startswith("--config-env") or (opt == "-c" and not (w and w.static)):
                return sub, args, "git config set on the command line before an alias"
            if opt == "-c" and w.text.lower().startswith(f"alias.{sub.lower()}="):
                value = w.text.partition("=")[2]
        if value is None:
            if git_env:
                return sub, args, "a GIT_* variable set before a git alias"
            real = repo not in (None, MISSING_DIR) and os.path.isdir(repo)
            value = git(
                repo if real else os.path.expanduser("~"),
                "config",
                "--get",
                f"alias.{sub}",
            )
        if not value:
            return sub, args, None
        if value.startswith("!"):
            runs_git = re.search(r"\bgit\b|\bpush\b", value)
            return (
                sub,
                args,
                f"a shell alias `git {sub}` = `{value}`" if runs_git else None,
            )
        words = shlex.split(value)
        sub, args = (words[0] if words else ""), words[1:] + args
    return sub, args, "a git alias loop"


def resolved(word, env):
    """word as a static word of its value when the command sets each variable in it."""
    value = None if word.static else word.expand(env)
    return literal(value) if value is not None and TEMP not in value else word


def walk(command, cwd):
    """Each push the command runs, as a dict of what the check needs."""
    pushes = []
    # each shell's directory, its variables, and (dir,) where a `cd` that failed left it
    stack = [(cwd, dict(os.environ), None)]
    seen = {"git_env": False, "pushd": False, "moved": False, "tags": []}
    pushing = "push" in command
    for kind, c in events(command):
        if kind == "open":
            here, env, failed = stack[-1]
            stack.append((here, dict(env), failed))
            continue
        if kind == "close":
            if len(stack) > 1:
                stack.pop()
            continue
        here, env, failed = stack[-1]
        if kind == "opaque":
            if pushing:
                pushes.append({"form": f"a push run through {c}", "dir": here})
            continue
        if failed and c.after == "||" and c.name in ("exit", "return"):
            # `cd x || exit`: what follows runs only where the `cd` went
            stack[-1] = (here, env, None)
            continue
        if failed and c.after != "&&":
            # a `cd` that fails leaves the shell where it was; only its `&&` chain is skipped
            here, failed = failed[0], None
            stack[-1] = (here, env, None)
        c = Cmd(c.assigns, [resolved(w, env) for w in c.words], c.after)
        if c.words and not c.words[0].static:
            if pushing:
                pushes.append(
                    {"form": "a command name the command computes", "dir": here}
                )
            continue
        argv = c.argv
        git_env = seen["git_env"] or any(n.startswith("GIT_") for n, _ in c.assigns)
        if not argv:
            for name, value in c.assigns:
                env[name] = value.expand(env)
            seen["git_env"] = git_env
            continue
        if c.name in ("export", "declare", "typeset", "local", "readonly"):
            for w in c.words[1:]:
                name, eq, _ = w.text.partition("=")
                git_env |= bool(eq) and name.startswith("GIT_")
                if eq and re.fullmatch(r"[A-Za-z_]\w*", name):
                    value = w.expand(env)
                    env[name] = value.partition("=")[2] if value is not None else None
        seen["git_env"] = git_env
        if c.name in ("pushd", "popd"):
            seen["pushd"] = True
        elif c.name == "cd":
            target = next(
                (w for w in c.words[1:] if w.text not in ("-L", "-P", "--")), None
            )
            if target is None:
                to = env.get("HOME")
            elif target.text == "-":
                to = None
            else:
                to = target.expand(env)
            new = cd(here, to)
            if new == MISSING_DIR and to is not None and TEMP not in to:
                failed = failed or (here,)
            stack[-1] = (new, env, failed)
        elif c.name in OPAQUE:
            rest = " ".join(argv[1:])
            git_at = re.search(r"\bgit\b", rest)
            aliased = any(
                (g := git_args(Cmd([], c.words[i:])))
                and unalias(here, g[1], [], g[0], git_env)[0] in ("push", None)
                for i in range(1, len(c.words))
            )
            if aliased or (git_at and re.search(r"\bpush\b", rest[git_at.end() :])):
                pushes.append({"form": f"a push run through `{c.name}`", "dir": here})
        elif parsed := git_args(c):
            opts, sub, args = parsed
            repo = here
            for opt, value in opts:
                if opt == "-C":
                    repo = cd(repo, value.expand(env))
            sub, texts, form = unalias(repo, sub, [w.text for w in args], opts, git_env)
            if form or sub is None:
                form = form or "a git subcommand the command computes"
                pushes.append({"form": form, "dir": repo})
            elif sub == "push":
                pushes.append(
                    {
                        "dir": repo,
                        "opts": [o for o, _ in opts if o != "-C"],
                        "args": texts,
                        **seen,
                        "git_env": git_env,
                        "tags": list(seen["tags"]),
                    }
                )
            elif sub == "tag":
                seen["tags"].append(([o for o, _ in opts], texts))
            elif moves(sub, texts):
                seen["moved"] = True
    return pushes


class Guard:
    def __init__(self, session, review_skip):
        self.session = session
        self.review_skip = review_skip
        self.missing, self.no_harness, self.unreviewed = [], [], []
        self.blocked = None  # (marker, planning, rung, harness) of the push that failed

    def check(self, p):
        form = None
        if p.get("opts"):
            form = f"git options before push ({' '.join(p['opts'])})"
        if p.get("git_env"):
            form = "a GIT_* variable set before the push"
        if p.get("pushd"):
            form = "pushd/popd before the push"
        if p.get("form"):
            form = p["form"]
        if p["dir"] is None:
            form = (
                "a directory the command computes (a `cd` or `-C` to a variable it does not set, "
                "or to a command's output) — cd to a literal path"
            )
        if p["dir"] == MISSING_DIR:
            return
        marker = route_marker(p["dir"], self.session) if p["dir"] else None
        # a held form may push a route's repository from anywhere (`--git-dir=`, `GIT_DIR=`, `pushd`)
        if not marker and form:
            marker = active_route()
        if not marker:
            return
        repo = p["dir"]
        if not form and p.get("moved"):
            form = "a git command that moves refs earlier in the command — push in a command of its own"
        tags = new_tags(repo, p.get("tags", [])) if not form else {}
        if tags is None:
            form = "a `git tag` other than creating a new tag earlier in the command — push in a command of its own"
        try:
            m = json.loads(pathlib.Path(marker).read_text(errors="replace"))
        except (OSError, ValueError):
            m = None
        planning = m.get("planning_dir") if isinstance(m, dict) else None
        if not planning:
            self.missing.append(
                "the route's marker names no planning dir — re-run route_state.py --activate"
            )
            self.blocked = (marker, "<planning-dir>", "", "")
            return
        rung, harness = m.get("rung") or "", m.get("ci_harness") or ""
        review = m.get("sins") == "on" and not self.review_skip
        had = len(self.missing) + len(self.no_harness) + len(self.unreviewed)
        if form:
            self.missing.append(
                f"{form} — push with plain `git [-C <dir>] push <remote> <refs>`"
            )
        else:
            self.refspecs(repo, planning, harness, review, p["args"], tags)
        if len(self.missing) + len(self.no_harness) + len(self.unreviewed) > had:
            # the message names the route of the push that failed
            self.blocked = (marker, planning, rung, harness)

    def refspecs(self, repo, planning, harness, review, args, tags):
        pos, skip = [], False
        for w in args:
            if skip:
                skip = False
            elif w in ("--dry-run", "-n", "--help", "-h", "--delete", "-d"):
                return  # sends nothing, or sends no commit
            elif w in ("--all", "--mirror", "--tags", "--branches"):
                self.missing.append(
                    "every ref (--all/--mirror/--tags/--branches) — push explicit refs"
                )
                return
            elif w in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
                skip = True  # the option's value is the next word
            elif not w.startswith("-"):
                pos.append(w)
        if len(pos) < 2:
            # what goes out depends on push.default, push refspecs, mirror and pushRemote config
            self.missing.append(
                "a push with no refspec — name the remote and the refs: git push <remote> <ref>"
            )
            return
        remote, branch = pos[0], git(repo, "symbolic-ref", "-q", "--short", "HEAD")
        for spec in pos[1:]:
            src, colon, dst = spec.removeprefix("+").partition(":")
            if not src:
                if not dst:
                    self.missing.append(
                        f"the matching refspec `{spec}` — name the refs"
                    )
                continue  # `:ref` deletes a remote ref and sends no commit
            # a new tag made earlier in the command, and whatever the name resolves to now
            shas = {
                s
                for s in (tags.get(src.removeprefix("refs/tags/")), commit(repo, src))
                if s
            }
            if not shas:
                self.missing.append(f"{src} (does not resolve to a commit in {repo})")
            for sha in sorted(shas):
                if not gated(planning, sha):
                    self.missing.append(f"{src} = {sha[:12]}")
                elif harness and not gated(planning, sha, harness):
                    self.no_harness.append(f"{src} = {sha[:12]}")
                elif review:
                    to = dst if colon else src
                    to = ((branch or "") if to == "HEAD" else to).removeprefix(
                        "refs/heads/"
                    )
                    onto = commit(repo, f"refs/remotes/{remote}/{to}")
                    if not reviewed(repo, planning, sha, remote, onto):
                        tracking = (
                            f" (remote-tracking {remote}/{to} = {onto[:12]})"
                            if onto
                            else ""
                        )
                        self.unreviewed.append(f"{src} = {sha[:12]}{tracking}")

    def report(self):
        marker, planning, rung, harness = self.blocked
        out = []
        if self.missing:
            out.append(
                "[push_guard] `git push` of a commit no full gate has passed — BLOCKED "
                f"(decision-spec-plan route active: {marker}).\n"
            )
            out += [f"  not gated: {s}" for s in self.missing]
            out.append(f"""
CI confirms a state already proven green here; it never discovers one. Check out that exact commit
on a clean tree and run the full gate into a log under the planning dir:

  {{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | grep -c .)"; <full gate>; echo "exit=$?"; }} > {planning}/lanes/<name>-gate.log 2>&1

The push goes through once a log there starts with `sha=<the commit> dirty=0` and ends `exit=0`.
Bypass only on the user's explicit instruction: prefix the push with DSP_SKIP_PUSH_GUARD=1.""")
        if self.no_harness:
            out.append(
                f"[push_guard] `git push` of a commit the CI harness `{harness}` has not passed — "
                f"BLOCKED (route: {marker}).\n"
            )
            out += [f"  not passed by the CI harness: {s}" for s in self.no_harness]
            out.append(f"""
CI runs a suite the local full gate does not (route_state.py --ci-harness), and a commit green
locally went red there four times in one round. Run that suite on the exact commit, on a clean
tree, into a log that names it:

  {{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | grep -c .)"; echo "harness={harness}"; <the CI's command>; echo "exit=$?"; }} > {planning}/lanes/<name>-{harness}-gate.log 2>&1

The push goes through once such a log ends `exit=0`. If the suite cannot run here, tell the user;
bypass only on their explicit instruction: DSP_SKIP_PUSH_GUARD=1.""")
        if self.unreviewed:
            out.append(
                "[push_guard] `git push` of a commit no pre-push review covers — BLOCKED "
                f"(rung {rung} route: {marker}).\n"
            )
            out += [f"  not reviewed: {s}" for s in self.unreviewed]
            out.append(f"""
With the sins on (rung L's phase-end push, or a review the user asked for) a push first gets the
seven-sins review of what it sends (references/sins/lead.md, base = the remote's tip after a
`git fetch`); `route_state.py --activate --sins off` ends it once that push is out. Its verdict,
{planning}/reviews/<name>-verdict.md, opens with

  reviewed=<full SHA reviewed> base=<full SHA of the base> blocking=<new criticals and highs neither fixed nor waived>
  after=<full SHA of each fix committed after the review, space-separated>
  slices=<from>..<to> …   (over {SLICE_MAX} commits: the slices reviewed, each at most {SLICE_MAX} commits)

The push goes through once blocking=0, the reviewed commit is an ancestor of the pushed one, every
commit between them is on the after= line, the base is an ancestor of the remote-tracking ref (for
a new branch, of one of that remote's tracking refs), and a review of more than {SLICE_MAX} commits
has slices that cover every one.
Bypass only on the user's explicit instruction: DSP_SKIP_REVIEW=1 (the gate check still applies).""")
        return "\n".join(out)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    # an alias may push with no `push` in the text
    if not re.search("push|git", command) or "DSP_SKIP_PUSH_GUARD=1" in command:
        return 0
    guard = Guard(str(event.get("session_id") or ""), "DSP_SKIP_REVIEW=1" in command)
    try:
        for p in walk(command, event.get("cwd") or os.getcwd()):
            guard.check(p)
    except Exception as e:  # noqa: BLE001 — a hook that exits 1 lets the push through
        if not active_route():
            return 0
        print(
            f"[push_guard] the guard failed on this command ({type(e).__name__}: {e}) while a "
            "decision-spec-plan route is active — BLOCKED. Push with plain "
            "`git [-C <dir>] push <remote> <refs>` in a command of its own.",
            file=sys.stderr,
        )
        return 2
    if guard.blocked is None:
        return 0
    print(guard.report(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
