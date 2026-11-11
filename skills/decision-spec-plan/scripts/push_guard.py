#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Let a `git push` send only commits the full gate passed (a PreToolUse:Bash hook).

PreToolUse:Bash — while a decision-spec-plan route is active in a repository
(<git-common-dir>/dsp-route-<id>.json, written by `route_state.py --activate`), a `git
push` may only send commits the full gate passed: a gate log under <planning-dir>/lanes/
that names no CI harness, whose first `sha=` line, within its first 20 lines (codegen or
a build may print first), is `sha=<that commit> dirty=0` and whose last `exit=` line is
`exit=0`.

With the sins on (`--sins on` in the marker: rung L's phase-end push, or a review the
user asked for) the push also needs a seven-sins review that covers it: a verdict under
<planning-dir>/reviews/ whose first 10 lines hold `reviewed=<sha> base=<sha> blocking=0`
(full SHAs), the reviewed commit an ancestor of the pushed one, every commit between
them on an `after=` line (fixes made after the review), and the base an ancestor of the
remote-tracking ref — or, for a branch the remote lacks, of one of that remote's
tracking refs (nothing older than the base is unsent). A review of more than 30 commits
counts only with a `slices=` line whose ranges, each at most 30 commits, cover every
commit of it (sins/lead.md: one review per slice).

With a CI harness in the marker (`--ci-harness <label>`: a suite CI runs that the local
gate does not) a push also needs a passing gate log for that commit whose first 20 lines
hold `harness=<label>`, except one to `refs/heads/<branch>` other than main — the push
that starts the CI run, which needs only the full gate (a bare name may be a tag on the
remote).

Every `git push` the command runs is checked — inside `if`/`for`, `( )`, `$( )`, `bash
-c`, `eval` and pass-through wrappers (`env`, `timeout`, …) too — each in the repository
its `cd`s and `-C`s reach (shell_cmd.py reads the command as bash does: a pipeline's
`cd` stays in its subshell, a `cd` that fails skips only its `&&` chain), and a git
alias is read as what it runs. What a push would send must be readable from the command,
so these are held: a push with no refspec or the matching refspec `:`, git options
before `push` other than `-C <dir>`, a GIT_* variable set before it, a `pushd`/`popd`, a
directory the command computes (`cd "$(…)"`, a variable it does not set), a push run
through `sudo`, `xargs` or the like, a command name or git subcommand the command
computes (or whose value bash would split or drop), a shell alias (`!…`), an alias after
a git option other than `-C` or in a command that sets GIT_*, HOME or XDG_CONFIG_HOME or
names `config` (it may define the alias first), stdin or a computed string fed to a
shell when the command has `push` as a word or a line running git with push after it,
and a ref-moving git command (`commit`, `fetch . a:b`, `checkout -B`, …) earlier in the
command. A script file the command runs (`bash x.sh`, `source x`) is read and checked
the same way, three files deep; one that cannot be read now (computed, missing) is held
like a computed string. A held form is held wherever it runs while any route on the
account is active, since it can point at a route's repository from outside it. A `cd` to
a fresh `mktemp` directory leaves the push in no route's repository.

Why: on 2026-10-07 a lead pushed main twice without a gate and both CI runs went red; CI
confirms a state already proven green locally, it never discovers one (failure-modes
F56). A finished lane whose full gate was green still carried two new high defects a
review found (F70). The bash guard read the command with regexes until 2026-10-30, and a
probe passed `timeout 60 git push`, `git fetch . lane:main && git push`, `(cd x && ls)
&& git push`, `git push origin :` and a quoted `-C` path, while it held `if …; then git
push` and `git log --grep push`.

Git's own hook: `route_state.py --activate` installs a pre-push hook in the repository
(the repository's own pre-push hook, if any, is kept as `pre-push.dsp-orig` and runs
after it; none is written where core.hooksPath is set). It runs `push_guard.py
--pre-push`, which applies the same gate, harness and review checks to the exact refs
and commits git is about to send — so `--all`, a push with no refspec and a ref the
command moved first are read as they are, not held. It acts only in a Claude Code shell
(CLAUDECODE set) while a route's marker is in the repository; a push from a terminal
passes. While that hook is in place the command guard leaves a push to it and holds only
what would skip it: `--no-verify`, and a command that names CLAUDECODE or hooks.

Bypass, only on the user's explicit word: DSP_SKIP_PUSH_GUARD=1 in the command skips
both checks; DSP_SKIP_REVIEW=1 skips only the review. Both reach the hook as environment
variables. While a route is active, the command guard asks the user to approve a push
that names either one, and blocks it outright for a route agent.
"""

import collections
import dataclasses
import functools
import itertools
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Collection, Iterable, Sequence
from typing import NamedTuple, cast

from shell_cmd import (
    TEMP,
    Assign,
    Cmd,
    Event,
    GitOptions,
    Opaque,
    Word,
    events,
    git_args,
    literal,
    read_script,
    redirects,
    run_script,
    words,
)

StrPath = str | os.PathLike[str]
# A shell's variables: None for one set to what the reader cannot compute.
Env = dict[str, str | None]
# A `git tag` earlier in the command: its git options and its arguments.
Tag = tuple[list[str], list[str]]
# Where a `cd` that failed left the shell, as (dir,).
Failed = tuple[str | None] | None
# A shell's directory, its variables, and where a `cd` that failed left it.
Frame = tuple[str | None, Env, Failed]
# (marker, planning, rung, harness) of the push that failed.
Blocked = tuple[str, str, str, str]

REGISTRY = pathlib.Path.home() / ".claude" / "dsp-routes"
SLICE_MAX = 30
SCRIPT_DEPTH = 3
# The fields of a line git hands its pre-push hook.
PRE_PUSH_FIELDS = 4
# A line that runs git with a push word after it: a heredoc's text no word holds.
GIT_PUSH_LINE = re.compile(r"\bgit\b[^\n]*?(?<![\w.$-])push(?![\w(-])")
# Git commands that move a ref the push may name: read now, the ref is not what the push
# sends.
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
    "switch",
    "update-ref",
    "branch",
    "fetch",
    "symbolic-ref",
    "replace",
    "filter-branch",
    "bisect",
}
# Variables that point git at another config, which may define an alias.
CONFIG_HOMES = {"HOME", "XDG_CONFIG_HOME"}
# Frequent git commands, so an alias lookup runs only for a rare name: git runs no alias
# named like a command of its own.
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
    "rev-parse",
    "rev-list",
    "init",
    "clone",
    "remote",
    "stash",
    "grep",
    "worktree",
    "ls-files",
    "describe",
    "restore",
    "notes",
    "blame",
    "clean",
    "merge-base",
}
# `git branch` options that only list.
BRANCH_LISTS = re.compile(
    r"-[arlv]+"
    r"|--(all|remotes|list|verbose|show-current|no-color|no-column|ignore-case|omit-empty)"
    r"|--(color|column|abbrev|format|sort|contains|no-contains|merged|no-merged|points-at)"
    r"(=.*)?"
)
# `git tag` options that list.
TAG_LISTS = re.compile(
    r"-l|--list|-n.*|--(points-at|contains|no-contains|merged|no-merged)(=.*)?"
)
# Commands that run their arguments as a command line this guard cannot follow:
# `op run --`, `direnv exec .`, `nix develop -c`, `uv run` among them.
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
    "nsenter",
    "unshare",
    "script",
    "find",
    "watchexec",
    "entr",
    "op",
    "direnv",
    "nix",
    "uv",
}
# Commands that write no file they name: a script named by one is not written before it
# runs.
READ_ONLY = {
    "cat",
    "chmod",
    "test",
    "[",
    "ls",
    "stat",
    "file",
    "head",
    "tail",
    "wc",
    "grep",
    "rg",
    "less",
    "bat",
    "shellcheck",
    "diff",
    "cmp",
    "echo",
    "printf",
    "realpath",
}
# Builtins whose words may set a variable the shell exports.
DECLARERS = ("export", "declare", "typeset", "local", "readonly")
MISSING_DIR = "\0missing"
VARIABLE = re.compile(r"[A-Za-z_]\w*")


def _basename(text: str) -> str:
    """Return the last `/`-separated part of text, as os.path.basename does."""
    return text.rpartition("/")[2]


def _home(text: str) -> str:
    """Return text with a leading `~` read as a home; an unknown user's stays as is."""
    if not text.startswith("~"):
        return text
    try:
        return str(pathlib.Path(text).expanduser())
    except RuntimeError:
        return text


def _is_dir(path: StrPath) -> bool:
    """Return whether path is a directory; False where it cannot be read."""
    try:
        return pathlib.Path(path).is_dir()
    except OSError:  # one it may not read (EACCES): os.path.isdir's False
        return False


def _is_file(path: StrPath) -> bool:
    """Return whether path is a file; False where it cannot be read."""
    try:
        return pathlib.Path(path).is_file()
    except OSError:  # one it may not read (EACCES): os.path.isfile's False
        return False


def _json_object(text: str) -> dict[str, object]:
    """Return the JSON object text holds, an empty one for any other JSON value."""
    value = cast("object", json.loads(text))
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def git(repo: StrPath, *args: str) -> str | None:
    """Return git's stripped stdout in repo, or None when it fails."""
    p = subprocess.run(
        [shutil.which("git") or "git", "-C", os.fspath(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return p.stdout.strip() if p.returncode == 0 else None


def commit(repo: StrPath, rev: str) -> str | None:
    """Return the commit rev names in repo, or None."""
    return git(repo, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}")


def head_lines(path: pathlib.Path, n: int) -> list[str]:
    """Return the first n lines of the file, line ends removed."""
    with path.open(errors="replace", newline="\n") as f:
        return [ln.rstrip("\n").replace("\r", "") for ln in itertools.islice(f, n)]


def _last_exit(log: pathlib.Path) -> str | None:
    """Return the log's last `exit=` line, stripped, or None."""
    last = None
    with log.open(errors="replace", newline="\n") as f:
        for ln in f:
            if re.fullmatch(r"exit=[0-9]+\s*", ln):
                last = ln.strip()
    return last


def _logs_commit(head: Sequence[str], sha: str, harness: str | None) -> bool:
    """Return whether a log whose head is head is one of sha, naming harness or none."""
    first = next((ln for ln in head if ln.startswith("sha=")), "")
    if first.split(" ")[0] != f"sha={sha}":
        return False
    named = [ln for ln in head if ln.startswith("harness=")]
    return (f"harness={harness}" in named) if harness else not named


def gated(
    planning: str, sha: str, harness: str | None = None, why: list[str] | None = None
) -> bool:
    """Return whether a gate log for sha passed.

    With harness, one that names it, else one that names none. Its first sha= line may
    carry more fields after `dirty=0` (`wt=<lane>`). why, a list, gets each log of sha
    that fails and the reason: a hold that named none made a lead edit a log to fit
    (2026-10-31).
    """
    for log in sorted(pathlib.Path(planning, "lanes").glob("*-gate*.log")):
        if not log.is_file():
            continue
        head = head_lines(log, 20)
        if not _logs_commit(head, sha, harness):
            continue
        first = next((ln for ln in head if ln.startswith("sha=")), "")
        if not re.fullmatch(rf"sha={sha} dirty=0(\s.*)?", first):
            if why is not None:
                why.append(f"{log.name}: `{first[:80]}`, not dirty=0")
            continue
        last = _last_exit(log)
        if last == "exit=0":
            return True
        if why is not None:
            why.append(
                f"{log.name}: last line `{last}`"
                if last
                else f"{log.name}: no exit= line (still running, or piped through "
                "tail/tee)"
            )
    return False


def covered(repo: StrPath, base: str, reviewed: str, slices: Sequence[str]) -> bool:
    """Return whether a review of base..reviewed counts, as a whole or by its slices.

    A review of more than SLICE_MAX commits counts only as slices (`<from>..<to>`, full
    SHAs) of at most SLICE_MAX that cover every commit: review recall collapses on a
    large diff. Merge commits are not counted — a lane split along its own history
    leaves its merge in no two-dot range.
    """

    def commits(spec: str) -> set[str]:
        return set((git(repo, "rev-list", "--no-merges", spec) or "").split())

    if not slices:
        return len(commits(f"{base}..{reviewed}")) <= SLICE_MAX
    seen: set[str] = set()
    for s in slices:
        if not re.fullmatch(r"[0-9a-f]{40}\.\.[0-9a-f]{40}", s):
            return False
        part = commits(s)
        if len(part) > SLICE_MAX:
            return False
        seen |= part
    return commits(f"{base}..{reviewed}") <= seen


def reviewed(
    repo: StrPath, planning: str, sha: str, remote: str, onto: str | None
) -> bool:
    """Return whether a verdict covers sha.

    onto is the remote-tracking commit of the pushed branch, if any.
    """
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
        r, b = stamp[1], stamp[2]
        if git(repo, "merge-base", "--is-ancestor", r, sha) is None:
            continue
        after = next((ln for ln in head if ln.startswith("after=")), "after=")
        fixes = set(re.split(r"[ ,]+", after.partition("=")[2].strip()))
        if set((git(repo, "rev-list", f"{r}..{sha}") or "").split()) - fixes:
            continue
        if onto:
            if git(repo, "merge-base", "--is-ancestor", b, onto) is None:
                continue
        # a branch the remote lacks: the base must be on the remote already, under any
        # of its refs
        elif git(repo, "rev-list", "-n1", b, "--not", f"--remotes={remote}") != "":
            continue
        line = next((ln for ln in head if ln.startswith("slices=")), "slices=")
        slices = [s for s in re.split(r"[ ,]+", line.partition("=")[2].strip()) if s]
        if covered(repo, b, r, slices):
            return True
    return False


def active_route() -> str | None:
    """Return the marker of any route registered on this account that is still active.

    A route is registered by route_state.py --activate.
    """
    for f in sorted(REGISTRY.glob("*.json")):
        try:
            marker = _json_object(f.read_text(errors="replace")).get("marker")
        except ValueError:
            continue
        if isinstance(marker, str) and marker and _is_file(marker):
            return marker
    return None


def route_marker(repo: StrPath, session: str) -> str | None:
    """Return the pushing session's route when it runs in repo, else the newest there.

    Two routes in one repository each have a marker (route_state.py --activate, F93).
    """
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return None
    try:
        mine = _json_object((REGISTRY / f"{session}.json").read_text()).get("marker")
    except (OSError, ValueError):
        mine = None
    if (
        isinstance(mine, str)
        and mine
        and _is_file(mine)
        and str(pathlib.Path(mine).parent) == common
    ):
        return mine
    found = sorted(
        pathlib.Path(common).glob("dsp-route*.json"), key=lambda p: p.stat().st_mtime
    )
    return str(found[-1]) if found else None


HOOK_TAG = "# decision-spec-plan pre-push"
GATE = pathlib.Path(__file__).resolve().with_name("gate.py")
SHIM = """#!/bin/sh
{tag}, written by route_state.py --activate. In a Claude Code shell, while
# a decision-spec-plan route is active in this repository, it holds a push the route's \
gates have
# not passed (push_guard.py --pre-push); a push from a terminal passes. The \
repository's own
# pre-push hook, if it had one, is pre-push.dsp-orig and runs after it. To remove: \
delete this
# file and rename pre-push.dsp-orig back.
guard={guard}
input=$(cat)
if [ -n "$CLAUDECODE" ]; then
	if [ -f "$guard" ]; then
		printf '%s\\n' "$input" | python3 "$guard" --pre-push "$@" || exit 1
	elif ls "$(git rev-parse --git-common-dir)"/dsp-route*.json >/dev/null 2>&1; then
		echo "[push_guard] a decision-spec-plan route is active here, but its \
guard $guard is gone (the plugin moved or was removed) — BLOCKED. Re-run \
route_state.py --activate, or end the route by deleting its marker." >&2
		exit 1
	fi
fi
orig="$(dirname "$0")/pre-push.dsp-orig"
[ -x "$orig" ] || exit 0
if [ -n "$input" ]; then printf '%s\\n' "$input"; fi | "$orig" "$@"
"""


def shim() -> str:
    """Return the pre-push hook this guard installs."""
    return SHIM.format(
        tag=HOOK_TAG, guard=shlex.quote(str(pathlib.Path(__file__).resolve()))
    )


def hook_file(repo: StrPath) -> pathlib.Path | None:
    """Return git's pre-push hook in repo; None where core.hooksPath points elsewhere.

    A tracked hooks directory (husky's) is the project's, not the route's.
    """
    if git(repo, "config", "core.hooksPath") is not None:
        return None
    hooks = git(repo, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    return pathlib.Path(hooks, "pre-push") if hooks else None


def hook_installed(repo: StrPath) -> bool:
    """Return whether this guard's own hook is installed, byte for byte.

    One written by another copy of the plugin (an upgrade moves its path) may call a
    guard that is gone.
    """
    f = hook_file(repo)
    try:
        return bool(f and os.access(f, os.X_OK) and f.read_text() == shim())
    except (OSError, UnicodeDecodeError):
        return False


def install_hook(repo: StrPath) -> str:
    """Install the pre-push hook (route_state.py --activate); return the line it prints.

    Why: the command guard reads what a push would send from the command's text, so it
    holds whatever it cannot read (`--all`, no refspec, a ref moved earlier in the
    command) — live sessions met those holds on pushes that were gated. Git hands its
    pre-push hook the exact refs and commits instead.
    """
    f = hook_file(repo)
    if f is None:
        return (
            "core.hooksPath is set: no pre-push hook installed; push_guard.py reads "
            "each push command instead"
        )
    orig = f.with_name("pre-push.dsp-orig")
    if f.exists() and HOOK_TAG not in f.read_text(errors="replace"):
        if orig.exists():
            return (
                f"no pre-push hook installed: {f} and {orig} both exist; push_guard.py "
                "reads each push command instead"
            )
        _ = f.rename(orig)
    f.parent.mkdir(parents=True, exist_ok=True)
    _ = f.write_text(shim())
    f.chmod(0o755)
    kept = (
        f" (the repository's own runs after it: {orig.name})" if orig.exists() else ""
    )
    return f"pre-push hook installed: {f}{kept}"


def cd(state: str | None, target: str | None, made: Collection[str] = ()) -> str | None:
    """Return the directory after `cd target` from state.

    A path, None (computed by the command) or MISSING_DIR (a directory that does not
    exist, or a fresh temp one). A missing one whose name the command also uses
    elsewhere (made) is followed as one it may create first: `mkdir -p out && cd out`,
    `git worktree add ../x && cd ../x`.
    """
    if target is None:
        return None
    if TEMP in target:
        return MISSING_DIR
    if target.startswith("/"):
        path = os.path.normpath(target)
    elif state is None or state == MISSING_DIR:
        return state
    else:
        path = os.path.normpath(pathlib.Path(state, target))
    return path if _is_dir(path) or _basename(path) in made else MISSING_DIR


def _tag_words(args: Sequence[str]) -> tuple[str | None, str | None] | None:
    """Return (new name, rev) of a `git tag`'s arguments, (None, None) for a listing.

    None for any form other than `[-a|-s] [-m <msg>|-F <file>|-u <key>] <name> [<rev>]`.
    """
    name = rev = None
    skip = False
    for w in args:
        if skip:
            skip = False
        elif TAG_LISTS.fullmatch(w):
            return None, None
        elif w in ("-m", "-F", "-u", "--message", "--file", "--local-user"):
            skip = True
        elif w in ("-a", "-s", "--annotate", "--sign"):
            continue
        elif w.startswith("-"):
            return None
        elif name is None:
            name = w
        elif rev is None:
            rev = w
        else:
            return None
    return name, rev


def new_tags(repo: StrPath, tags: Iterable[Tag]) -> dict[str, str | None] | None:
    """Return {name: commit} of the tags a `git tag` earlier in the command creates.

    Only `git tag [-a|-s] [-m <msg>|-F <file>|-u <key>] <new name> [<rev>]` is read, and
    a listing passes; any other `git tag` (a move, a delete, clustered flags, git
    options) is None, which holds the push. Why: `git tag v1 <sha> && git push origin
    v1` was held because v1 did not exist yet.
    """
    out: dict[str, str | None] = {}
    for opts, args in tags:
        if opts:
            return None
        parsed = _tag_words(args)
        if parsed is None:
            return None
        name, rev = parsed
        # `git tag` alone lists; a name that exists already or twice is a move or a
        # refusal
        if name is None:
            continue
        if name in out or commit(repo, f"refs/tags/{name}"):
            return None
        out[name] = commit(repo, rev or "HEAD")
    return out


def moves(sub: str, args: Sequence[str]) -> bool:
    """Return whether `git <sub> <args>` moves a ref."""
    if sub == "branch":
        flags = {a for a in args if a.startswith("-")}
        if flags & {"-d", "-D", "--delete"} and flags <= {
            "-d",
            "-D",
            "--delete",
            "-q",
            "--quiet",
        }:
            return False  # a deleted branch sends nothing: a push of it fails
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
        # a refspec with a destination, or the repository itself as the remote, writes
        # local refs
        positional = [a for a in args if not a.startswith("-")]
        return positional[:1] == ["."] or any(":" in a for a in positional[1:])
    return sub in MOVES


@functools.cache
def builtins() -> set[str]:
    """Return every git command's name: git never runs an alias named like one."""
    return set((git(_home("~"), "--list-cmds=main,others") or "").split())


@functools.cache
def alias(repo: str | None, sub: str) -> str | None:
    """Return the config's `alias.<sub>` in repo, or in the home directory's config.

    The home directory's when repo is no directory; once per name, so a long line of
    `git x` runs no lookup per command.
    """
    real = repo is not None and repo != MISSING_DIR and _is_dir(repo)
    return git(
        repo if real and repo is not None else _home("~"),
        "config",
        "--get",
        f"alias.{sub}",
    )


def unalias(
    repo: str | None,
    sub: str | None,
    args: list[str],
    opts: GitOptions,
    *,
    config_env: bool,
) -> tuple[str | None, list[str], str | None]:
    """Return (subcommand, args, None) with an alias replaced by what it runs.

    A held form takes the third place when the alias cannot be read: a shell alias
    (`!…`, which runs anything), a git option before it other than `-C` (`-c
    include.path=`, `--git-dir`), a config the command may change (config_env), a loop.
    """
    for _ in range(10):
        if not sub or sub in COMMON or sub in builtins():
            return sub, args, None
        if any(o != "-C" for o, _ in opts):
            return (
                sub,
                args,
                "git options before an alias (another config or repository)",
            )
        if config_env:
            return sub, args, "a git alias the command's config change may define"
        value = alias(repo, sub)
        if not value:
            return sub, args, None
        if value.startswith("!"):
            return sub, args, f"a shell alias `git {sub}` = `{value}`"
        split = shlex.split(value)
        sub, args = (split[0] if split else ""), split[1:] + args
    return sub, args, "a git alias loop"


def may_push(cmd: Cmd, repo: str | None, *, config_env: bool) -> bool:
    """Return whether cmd, a git command run through another (`sudo git …`), may push.

    A subcommand that is push, computed, or an alias the guard cannot read.
    """
    g = git_args(cmd)
    if not g:
        return False
    sub, _, form = unalias(repo, g[1], [], g[0], config_env=config_env)
    return sub in ("push", None) or bool(form)


def resolved(word: Word, env: Env) -> Word:
    """Return word as a static word of its value when the command sets its variables."""
    value = None if word.static else word.expand(env)
    # an unquoted value with blanks or glob characters is split or globbed, an empty one
    # dropped
    if not value or TEMP in value or re.search(r"[\s*?\[]", value):
        return word
    return literal(value)


PUSH_WORD = re.compile(r"(?<![\w.$-])push(?![\w(-])")


FILE_SUB = re.compile(r"\$\(\s*(?:cat\s+|<\s*)([^\s()|;&<>`$]+)\s*\)")


def names_push(
    ws: Iterable[Word],
    env: Env,
    here: str | None = "",
    written: Collection[str] = (),
) -> bool:
    """Return whether a computed command's words may name push.

    Its own words, the values they expand to, or a file a `$(cat f)` or `$(<f)` in them
    reads (`$(echo git) push`, `X="git push …"; $X`, `sh -c "$(cat deploy.sh)"`). A file
    the guard cannot read, or one whose name the command writes (written: basenames)
    before it runs, may hold anything.
    """
    for w in ws:
        if PUSH_WORD.search(w.expand(env) or w.text):
            return True
        for sub in FILE_SUB.finditer(w.text):
            name = _home(sub[1].strip("'\""))
            if _basename(name) in written:
                return True
            try:
                with pathlib.Path(here or "", name).open(errors="replace") as f:
                    if PUSH_WORD.search(f.read(1_000_000)):
                        return True
            except (OSError, ValueError):  # missing, or MISSING_DIR's NUL in the path
                return True
    return False


# Builtins that set a variable they name (`export NAME`, `read NAME`, `declare -n
# r=NAME`), and `alias`, whose body runs in this shell.
SETTERS = {
    "export",
    "declare",
    "typeset",
    "local",
    "readonly",
    "read",
    "mapfile",
    "readarray",
    "getopts",
    "alias",
}
SKIP_NAMES = {"DSP_SKIP_PUSH_GUARD", "DSP_SKIP_REVIEW"}


def skip_names(command: str) -> set[str]:
    """Return the bypass variables (DSP_SKIP_*) the command may set.

    "?" for one it names by a part (`DSP_SKIP_$X`). A name sets one in an assignment (or
    its value: `V=DSP_SKIP_…; env "$V=1"`), in a word of a setter builtin or of
    `printf -v`, as a NAME=value word of a command that passes it on or writes it out
    (`make`, `env`, `echo … >env.sh`), in `${NAME:=}`, and anywhere in text the reader
    cannot follow. Text the shell sets nothing from is no bypass: `grep`,
    `git log --grep`, a commit message, a comment.
    """
    texts: list[str] = []
    for _, c in events(command):
        if isinstance(c, Cmd):
            argv = c.argv
            texts += [f"{n}={v.text}" for n, v in c.assigns]
            # `printf -v NAME` and `printf -vNAME` both set NAME
            printf_v = c.name == "printf" and any(a.startswith("-v") for a in argv[1:])
            if c.name in SETTERS or printf_v:
                texts += argv
            elif c.name not in READ_ONLY or c.name in ("echo", "printf"):
                texts += [a for a in argv if re.fullmatch(r"DSP_SKIP\w*=\S*", a)]
            texts += [a for a in argv if re.search(r"\$\{DSP_SKIP\w*:?=", a)]
        elif isinstance(c, Opaque):
            texts += [str(c), *(f"{n}={v.text}" for n, v in c.assigns)]
            texts += [w.text for w in [*c.words, c.script] if w is not None]
    found = [m[0] for m in re.finditer(r"DSP_SKIP\w*", " ".join(texts))]
    return {n if n in SKIP_NAMES else "?" for n in found}


@dataclasses.dataclass
class Seen:
    """What the command did before a push that changes how the push reads."""

    git_env: bool = False
    config_env: bool = False
    pushd: bool = False
    moved: bool = False
    tags: list[Tag] = dataclasses.field(default_factory=list[Tag])


@dataclasses.dataclass
class State:
    """A walk's variables, exported names, what it saw, and the directory it ends in."""

    env: Env
    exported: set[str]
    seen: Seen
    pushing: bool
    dir: str | None = None


@dataclasses.dataclass
class Push:
    """A push the command runs: what the check needs of it.

    form is set for a push whose target the command does not let the guard read.
    """

    dir: str | None
    form: str | None = None
    opts: list[str] = dataclasses.field(default_factory=list[str])
    args: list[str] = dataclasses.field(default_factory=list[str])
    computed: list[str] = dataclasses.field(default_factory=list[str])
    git_env: bool = False
    pushd: bool = False
    moved: bool = False
    tags: list[Tag] = dataclasses.field(default_factory=list[Tag])


def _fresh_state(command: str, decoded: Sequence[str]) -> State:
    r"""Return the state a walk of the whole command starts from.

    `push` as a word once its quotes and escapes are read (`p\ush`, a `bash -c` string's
    words), or a line that runs git with push after it (a heredoc fed to a shell): a
    word holding push (`events=push`, `push:none`, `a.push(`) held five agents' local
    work on 2026-10-31. A script's whole text does not count, only each computed
    command's own words (names_push): this test suite's held every computed name in it.
    """
    return State(
        # OLDPWD is the hook's, not the shell's: `cd -` before any `cd` is computed
        env={k: v for k, v in os.environ.items() if k != "OLDPWD"},
        exported=set(os.environ),
        seen=Seen(),
        pushing="push" in decoded or bool(GIT_PUSH_LINE.search(command)),
    )


class _Walk:
    """One walk of a command's events, with the shells' directories and variables."""

    def __init__(
        self, command: str, cwd: str | None, depth: int, state: State | None
    ) -> None:
        """Read the command, and what its words say about the files it writes."""
        self.found: list[Event] = events(command)
        decoded = [w.text for w in words(command)]
        self.state: State = state or _fresh_state(command, decoded)
        self.seen: Seen = self.state.seen
        self.pushing: bool = self.state.pushing
        self.depth: int = depth
        self.pushes: list[Push] = []
        # a GIT_*, HOME or XDG_CONFIG_HOME variable, or `config` anywhere (`git config
        # alias.p push`, `>> .git/config`): an alias read now may not be the one the
        # command runs
        self.seen.config_env |= "config" in " ".join([command, *decoded])
        # the names of files a command may write: a redirect target, a script a shell
        # runs, a word of a command that writes none it names is not one (`chmod +x x.sh
        # && ./x.sh` was held); a script so named twice may be written before it runs
        written = [t.text for t, _ in redirects(command)]
        for _, c in self.found:
            if isinstance(c, Cmd) and c.words and c.name not in READ_ONLY:
                written += [w.text for w in c.words]
            elif isinstance(c, Opaque) and c.script:
                written.append(c.script.text)
        self.named: list[str] = [_basename(t) for t in written]
        # a directory named twice may be made before a `cd` or `-C` into it (`mkdir -p
        # out && cd out`, `git clone <url>/x.git && cd x`)
        counts = collections.Counter(
            _basename(t.rstrip("/")).removesuffix(".git") for t in decoded
        )
        self.made: set[str] = {n for n, k in counts.items() if k > 1}
        # each shell's directory, its variables, and (dir,) where a `cd` that failed
        # left it
        self.stack: list[Frame] = [(cwd, self.state.env, None)]

    def walk(self) -> list[Push]:
        """Return each push the command runs; the state records where it ends."""
        for kind, c in self.found:
            if kind == "open":
                here, env, failed = self.stack[-1]
                self.stack.append((here, dict(env), failed))
            elif c is None:
                if len(self.stack) > 1:
                    _ = self.stack.pop()
            elif isinstance(c, Opaque):
                self._opaque(c)
            else:
                self._command(c)
        self.state.dir = self.stack[0][0]
        return self.pushes

    def _run(
        self,
        script: Word,
        text: str | None,
        *,
        sourced: bool,
        assigns: Sequence[Assign] = (),
    ) -> str | None:
        """Walk a script file the command runs; return the shell's directory after it.

        The prefixes assigns (`GIT_DIR=x ./deploy.sh`) hold while it runs; a sourced one
        shares the shell, and the directory it ends in is the command's after it.
        """
        here, env, _ = self.stack[-1]
        seen = self.seen
        pre = {n: v.expand(env) for n, v in assigns}
        git_pre = any(n.startswith("GIT_") for n in pre)
        config_pre = git_pre or any(n in CONFIG_HOMES for n in pre)
        before = {n: (n in env, env.get(n)) for n in pre}  # whether the shell set it
        if sourced:
            env.update(pre)
            seen.git_env |= git_pre
            seen.config_env |= config_pre
            inner = dataclasses.replace(self.state, env=env)
        else:
            # a child shell: it gets only exported variables and its prefixes, and what
            # it changes stays in it
            exported = self.state.exported
            inner = dataclasses.replace(
                self.state,
                env={**{k: v for k, v in env.items() if k in exported}, **pre},
                exported=set(exported) | set(pre),
                seen=dataclasses.replace(
                    seen,
                    tags=list(seen.tags),
                    git_env=seen.git_env or git_pre,
                    config_env=seen.config_env or config_pre,
                ),
            )
        if text is not None:
            self.pushes.extend(walk(text, here, self.depth + 1, inner))
            # a tag or ref it moves is the repository's, not the shell's
            seen.moved |= inner.seen.moved
            seen.tags[:] = inner.seen.tags
        # a prefix holds while the sourced file runs; a value the file set itself stays
        if sourced:
            for n, (was, old) in before.items():
                if n in env and env[n] == pre[n]:
                    if not was:
                        _ = env.pop(n, None)
                    else:
                        env[n] = old
        # a file named for push (`push.sh`); a directory so named holds a route's review
        # probes
        name = _basename(script.text)
        if (self.pushing or "push" in name) and (
            text is None or self.named.count(name) > 1
        ):
            # unreadable, or written by the command before it runs: not the file read
            # now
            self.pushes.append(Push(dir=here, form=f"a push run through {script.text}"))
        return inner.dir if sourced and text is not None else here

    def _opaque(self, c: Opaque) -> None:
        """Walk what a shell runs that the reader cannot see: a script file it reads."""
        here, env, failed = self.stack[-1]
        script = c.script and resolved(c.script, env)
        text = read_script(script, here) if self.depth < SCRIPT_DEPTH else None
        if script:
            after = self._run(script, text, sourced=c.sourced, assigns=c.assigns)
            self.stack[-1] = (after, env, failed)
        elif c.held or self.pushing or names_push(c.words, env, here, self.named):
            self.pushes.append(Push(dir=here, form=f"a push run through {c}"))

    def _command(self, c: Cmd) -> None:
        """Walk a simple command: after a failed `cd`, a computed name, assignments."""
        here, env, failed = self.stack[-1]
        if failed and c.after == "||" and c.name in ("exit", "return"):
            # `cd x || exit`: what follows runs only where the `cd` went
            self.stack[-1] = (here, env, None)
            return
        if failed and c.after != "&&":
            # a `cd` that fails leaves the shell where it was; only its `&&` chain is
            # skipped
            here, failed = failed[0], None
            self.stack[-1] = (here, env, None)
        # a computed first word that resolves to NAME=value is an assignment `env`
        # makes, which the reader left in place: the command's name is past it (`V=X;
        # env "$V=1" git push`)
        assigned = bool(
            c.words
            and not c.words[0].static
            and re.fullmatch(
                r"[A-Za-z_]\w*=.*", c.words[0].expand(env) or "", re.DOTALL
            )
        )
        cmd = Cmd(c.assigns, [resolved(w, env) for w in c.words], c.after)
        if cmd.words and (assigned or not cmd.words[0].static):
            if self.pushing or names_push(cmd.words, env, here, self.named):
                self.pushes.append(
                    Push(dir=here, form="a command name the command computes")
                )
            return
        if not cmd.argv:
            # set in the shell: they hold for every later command
            for name, value in cmd.assigns:
                env[name] = value.expand(env)
            self.seen.git_env |= any(n.startswith("GIT_") for n, _ in cmd.assigns)
            self.seen.config_env |= any(n in CONFIG_HOMES for n, _ in cmd.assigns)
            return
        self._simple(cmd, here, env, failed)

    def _declare(self, cmd: Cmd, env: Env) -> None:
        """Record the variables `export`, `declare` and the like set and export."""
        exports = cmd.name == "export" or any(
            re.fullmatch(r"-\w*x\w*", t) for t in cmd.argv[1:]
        )
        for w in cmd.words[1:]:
            name, eq, _ = w.text.partition("=")
            if exports and VARIABLE.fullmatch(name):
                self.state.exported.add(name)
            self.seen.git_env |= bool(eq) and name.startswith("GIT_")
            self.seen.config_env |= bool(eq) and name in CONFIG_HOMES
            if eq and VARIABLE.fullmatch(name):
                value = w.expand(env)
                env[name] = value.partition("=")[2] if value is not None else None

    def _simple(self, cmd: Cmd, here: str | None, env: Env, failed: Failed) -> None:
        """Walk a command with a name and words: `cd`, a wrapper, git, a script file."""
        prefix_git = any(n.startswith("GIT_") for n, _ in cmd.assigns)
        prefix_config = any(n in CONFIG_HOMES for n, _ in cmd.assigns)
        if cmd.name in DECLARERS:
            self._declare(cmd, env)
        # a prefix holds for its own command only (`GIT_PAGER=cat git log; git push`)
        git_env = self.seen.git_env or prefix_git
        config_env = self.seen.config_env or prefix_config or git_env
        if cmd.name in ("pushd", "popd"):
            self.seen.pushd = True
        elif cmd.name == "cd":
            self._cd(cmd, here, env, failed)
        elif cmd.name in OPAQUE:
            self._through(cmd, here, config_env=config_env)
        elif parsed := git_args(cmd):
            self._git(parsed, here, env, git_env=git_env, config_env=config_env)
        elif (
            self.depth < SCRIPT_DEPTH
            and (text := run_script(cmd.words[0], here)) is not None
        ):
            _ = self._run(cmd.words[0], text, sourced=False, assigns=cmd.assigns)

    def _cd(self, cmd: Cmd, here: str | None, env: Env, failed: Failed) -> None:
        """Move the shell's directory as `cd` does, and record a `cd` that fails."""
        target = next(
            (w for w in cmd.words[1:] if w.text not in ("-L", "-P", "--")), None
        )
        moved_to: bool | None = True  # whether the `cd` succeeds; None: it may not have
        if target is not None and target.text == "-":
            new = env.get("OLDPWD")  # where the last `cd` left; None before any
        else:
            to = env.get("HOME") if target is None else target.expand(env)
            new = cd(here, to, self.made)
            if new == MISSING_DIR and to is not None and TEMP not in to:
                failed, moved_to = failed or (here,), False
        if new is None:
            moved_to = None
        # a `cd` that fails leaves OLDPWD as it was
        if moved_to is not False:
            env["OLDPWD"] = here if moved_to else None
        self.stack[-1] = (new, env, failed)

    def _through(self, cmd: Cmd, here: str | None, *, config_env: bool) -> None:
        """Record a push a command runs through another (`sudo`, `xargs`, …)."""
        rest = " ".join(cmd.argv[1:])
        git_at = re.search(r"\bgit\b", rest)
        aliased = any(
            may_push(Cmd([], cmd.words[i:]), here, config_env=config_env)
            for i in range(1, len(cmd.words))
        )
        if aliased or (git_at and re.search(r"\bpush\b", rest[git_at.end() :])):
            self.pushes.append(Push(dir=here, form=f"a push run through `{cmd.name}`"))

    def _git(
        self,
        parsed: tuple[GitOptions, str | None, list[Word]],
        here: str | None,
        env: Env,
        *,
        git_env: bool,
        config_env: bool,
    ) -> None:
        """Record a git command: a push, a new tag, or a ref it moves."""
        opts, sub, args = parsed
        repo = here
        for opt, value in opts:
            if opt == "-C":
                # a bare `-C` is a usage error: git runs nothing
                repo = cd(repo, value.expand(env), self.made) if value else MISSING_DIR
        sub, texts, form = unalias(
            repo, sub, [w.text for w in args], opts, config_env=config_env
        )
        if form or sub is None:
            form = form or "a git subcommand the command computes"
            self.pushes.append(Push(dir=repo, form=form))
        elif sub == "push":
            self.pushes.append(
                Push(
                    dir=repo,
                    opts=[o for o, _ in opts if o != "-C"],
                    args=texts,
                    computed=[w.text for w in args if not w.static],
                    git_env=git_env,
                    pushd=self.seen.pushd,
                    moved=self.seen.moved,
                    tags=list(self.seen.tags),
                )
            )
        elif sub == "tag":
            self.seen.tags.append(([o for o, _ in opts], texts))
        elif moves(sub, texts):
            self.seen.moved = True


def walk(
    command: str, cwd: str | None, depth: int = 0, state: State | None = None
) -> list[Push]:
    """Return each push the command runs, with what the check needs of it.

    A script file it runs is walked in turn, SCRIPT_DEPTH deep, from the command's
    variables and flags (state); a sourced one shares them, and the directory it ends in
    (state.dir) is the command's after it.
    """
    return _Walk(command, cwd, depth, state).walk()


class Route(NamedTuple):
    """What a route's marker says about its pushes."""

    planning: str
    rung: str
    harness: str
    review: bool
    main: str | None


class Sent(NamedTuple):
    """A commit a push sends: from src to the remote's ref to, onto its known commit."""

    src: str
    sha: str
    to: str
    onto: str | None = None


def _held_form(p: Push) -> str | None:
    """Return why the guard cannot read the push's target from the command, if so."""
    form = None
    if p.opts:
        form = f"git options before push ({' '.join(p.opts)})"
    if p.git_env:
        form = "a GIT_* variable set before the push"
    if p.pushd:
        form = "pushd/popd before the push"
    if p.form:
        form = p.form
    if p.dir is None:
        form = (
            "a directory the command computes (a `cd` or `-C` to a variable it does "
            "not set, or to a command's output) — cd to a literal path"
        )
    elif p.dir and not _is_dir(p.dir):
        # one the command may create first (cd()): which repository it is in cannot be
        # read
        form = (
            "a push from a directory the command creates — push in a command of its own"
        )
    return form


def _push_specs(rest: list[str]) -> list[str]:
    """Return the refspecs of a push's words after the remote.

    git reads `tag <name>` as refs/tags/<name>:refs/tags/<name>.
    """
    specs: list[str] = []
    while rest:
        if rest[0] == "tag" and rest[1:]:
            specs.append(f"refs/tags/{rest[1]}")
            rest = rest[2:]
        else:
            specs.append(rest.pop(0))
    return specs


class Guard:
    """The checks of a command's or a pre-push hook's pushes, and the holds found."""

    def __init__(self, session: str, *, review_skip: bool, command: str = "") -> None:
        """Start with no holds, for the session's pushes in command."""
        self.session: str = session
        self.review_skip: bool = review_skip
        # a command that names these may skip git's pre-push hook: the guard reads its
        # pushes itself
        self.unhooked: bool = bool(re.search(r"hooks|CLAUDECODE", command))
        self.missing: list[str] = []
        self.no_harness: list[str] = []
        self.unreviewed: list[str] = []
        # pushes whose target the command does not let the guard read
        self.forms: list[str] = []
        self.blocked: Blocked | None = None  # the route of the push that failed

    def failures(self) -> int:
        """Return how many holds the checks found."""
        return (
            len(self.missing)
            + len(self.no_harness)
            + len(self.unreviewed)
            + len(self.forms)
        )

    def route(self, marker: str) -> Route | None:
        """Return what the route's marker says; None when it names no planning dir.

        A marker that names none is recorded as a hold.
        """
        try:
            m = _json_object(pathlib.Path(marker).read_text(errors="replace"))
        except (OSError, ValueError):
            m = {}
        planning = m.get("planning_dir")
        if not isinstance(planning, str) or not planning:
            self.missing.append(
                "the route's marker names no planning dir — re-run route_state.py "
                "--activate"
            )
            self.blocked = (marker, "<planning-dir>", "", "")
            return None
        args = m.get("args")
        args = cast("list[object]", args) if isinstance(args, list) else []
        given = args[args.index("--main") + 1] if "--main" in args[:-1] else None
        main = given if isinstance(given, str) else None
        return Route(
            planning,
            str(m.get("rung") or ""),
            str(m.get("ci_harness") or ""),
            m.get("sins") == "on" and not self.review_skip,
            main and main.removeprefix("refs/heads/"),
        )

    def pre_push(
        self, repo: str, marker: str, remote: str, lines: Iterable[str]
    ) -> None:
        """Check git's pre-push hook input.

        Each line is `<local ref> <local sha> <remote ref> <remote sha>`.
        """
        route = self.route(marker)
        if route is None:
            return
        for line in lines:
            parts = line.split()
            if len(parts) != PRE_PUSH_FIELDS or not parts[1].strip("0"):
                continue  # a deletion sends no commit
            local, sha, to, theirs = parts
            if (c := commit(repo, sha)) is None:
                self.missing.append(f"{local} = {sha[:12]} (not a commit)")
                continue
            onto = commit(repo, theirs) if theirs.strip("0") else None
            self.commit_ok(repo, route, remote, Sent(local, c, to, onto))
        if self.failures():
            self.blocked = (marker, route.planning, route.rung, route.harness)

    def _unread(
        self, p: Push, repo: str
    ) -> tuple[str | None, dict[str, str | None]] | None:
        """Return why a readable push is held and its new tags; None to leave it to git.

        Git's pre-push hook, where it is installed, reads the refs and commits the push
        sends.
        """
        if not self.unhooked and hook_installed(repo):
            # git reads an unambiguous abbreviation as the option: `--no-veri` is
            # `--no-verify`
            if not any(
                a.startswith("--no-v") and "--no-verify".startswith(a) for a in p.args
            ):
                return None
            return (
                "`--no-verify`, which skips the pre-push hook that checks what a push "
                "sends"
            ), {}
        if p.moved:
            return (
                "a git command that moves refs earlier in the command — push in a "
                "command of its own"
            ), {}
        tags = new_tags(repo, p.tags)
        if tags is None:
            return (
                "a `git tag` other than creating a new tag earlier in the command — "
                "push in a command of its own"
            ), {}
        return None, tags

    def check(self, p: Push) -> None:
        """Check one push the command runs, and record the holds it meets."""
        if p.dir == MISSING_DIR:
            return
        form = _held_form(p)
        marker = route_marker(p.dir, self.session) if p.dir else None
        # a held form may push a route's repository from anywhere (`--git-dir=`,
        # `GIT_DIR=`, `pushd`)
        if not marker and form:
            marker = active_route()
        if not marker:
            return
        tags: dict[str, str | None] = {}
        if not form and p.dir:
            read = self._unread(p, p.dir)
            if read is None:
                return
            form, tags = read
        route = self.route(marker)
        if route is None:
            return
        had = self.failures()
        if form:
            self.forms.append(form)
        elif p.dir:
            self.refspecs(p.dir, route, p, tags)
        if self.failures() > had:
            # the message names the route of the push that failed
            self.blocked = (marker, route.planning, route.rung, route.harness)

    def _positional(
        self, args: Sequence[str], computed: Collection[str]
    ) -> list[str] | None:
        """Return a push's positional words; None to stop, with the hold it met if any.

        A push that sends nothing, or no commit, stops with no hold.
        """
        pos: list[str] = []
        skip = False
        for w in args:
            if skip:
                skip = False
            elif w in computed:
                self.forms.append(
                    f"`{w}`, a refspec the command computes — name the refs"
                )
                return None
            elif w in ("--dry-run", "-n", "--help", "-h", "--delete", "-d"):
                return None  # sends nothing, or sends no commit
            elif w in ("--all", "--mirror", "--tags", "--branches"):
                self.missing.append(
                    "every ref (--all/--mirror/--tags/--branches) — push explicit refs"
                )
                return None
            elif w in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
                skip = True  # the option's value is the next word
            elif not w.startswith("-"):
                pos.append(w)
        return pos

    def refspecs(
        self, repo: str, route: Route, p: Push, tags: dict[str, str | None]
    ) -> None:
        """Check each commit a readable push sends, by its refspecs."""
        pos = self._positional(p.args, p.computed)
        if pos is None:
            return
        if not pos[1:]:
            # what goes out depends on push.default, push refspecs, mirror and
            # pushRemote config
            self.missing.append(
                "a push with no refspec — name the remote and the refs: "
                "git push <remote> <ref>"
            )
            return
        remote, branch = pos[0], git(repo, "symbolic-ref", "-q", "--short", "HEAD")
        for spec in _push_specs(pos[1:]):
            src, colon, dst = spec.removeprefix("+").partition(":")
            if not src:
                if not dst:
                    self.missing.append(
                        f"the matching refspec `{spec}` — name the refs"
                    )
                continue  # `:ref` deletes a remote ref and sends no commit
            # a new tag made earlier in the command, and whatever the name resolves to
            # now
            shas = {
                s
                for s in (tags.get(src.removeprefix("refs/tags/")), commit(repo, src))
                if s
            }
            if not shas:
                self.missing.append(f"{src} (does not resolve to a commit in {repo})")
            to = dst if colon else src
            to = (branch or "") if to == "HEAD" else to
            for sha in sorted(shas):
                self.commit_ok(repo, route, remote, Sent(src, sha, to))

    def commit_ok(self, repo: str, route: Route, remote: str, sent: Sent) -> None:
        """Record where a commit a push sends fails a check."""
        # the branch push that starts the CI run cannot carry its log: the harness
        # guards every push but one to `refs/heads/<x>`, x not main — the remote reads a
        # bare name against its own refs, which may hold a tag of that name
        branch_ref = sent.to.startswith("refs/heads/")
        to = sent.to.removeprefix("refs/heads/")
        main = route.main
        ci = route.harness and (main is None or not branch_ref or to == main)
        why: list[str] = []
        src, sha = sent.src, sent.sha
        if not gated(route.planning, sha, why=why):
            reason = (
                "; ".join(why) or f"no gate log under {route.planning}/lanes/ names it"
            )
            self.missing.append(f"{src} = {sha[:12]} — {reason}")
        elif ci and not gated(route.planning, sha, route.harness):
            self.no_harness.append(f"{src} = {sha[:12]}")
        elif route.review:
            onto = sent.onto or commit(repo, f"refs/remotes/{remote}/{to}")
            if not reviewed(repo, route.planning, sha, remote, onto):
                tracking = f" (remote {remote}/{to} = {onto[:12]})" if onto else ""
                self.unreviewed.append(f"{src} = {sha[:12]}{tracking}")

    def report(self, blocked: Blocked) -> str:
        """Return the message of the push that failed, blocked naming its route."""
        marker, planning, rung, harness = blocked
        out: list[str] = []
        if self.forms:
            out.append(
                "[push_guard] a push whose target the guard cannot read from the "
                f"command — BLOCKED (decision-spec-plan route active: {marker}).\n"
            )
            out += [f"  held: {s}" for s in self.forms]
            out.append("""
No gate log clears this hold: which commits go out, or to where, depends on what the \
command does
before the push. Run it as plain `git [-C <dir>] push <remote> <refs>`, in a command \
of its own.
Bypass only on the user's explicit instruction: prefix the push with \
DSP_SKIP_PUSH_GUARD=1.""")
        if self.missing:
            out.append(
                "[push_guard] `git push` of a commit no full gate has passed — BLOCKED "
                f"(decision-spec-plan route active: {marker}).\n"
            )
            out += [f"  not gated: {s}" for s in self.missing]
            out.append(f"""
CI confirms a state already proven green here; it never discovers one. Check out that \
exact commit
on a clean tree and run the full gate through the gate runner, which writes the log:

  {GATE} {planning} <name> -- '<full gate>'

The push goes through once a log there has `sha=<the commit> dirty=0` as its first \
`sha=` line,
within its first 20 lines (a build may print first), and `exit=0` as its last `exit=` \
line.
Bypass only on the user's explicit instruction: prefix the push with \
DSP_SKIP_PUSH_GUARD=1.""")
        if self.no_harness:
            out.append(
                "[push_guard] `git push` of a commit the CI harness "
                f"`{harness}` has not passed — BLOCKED (route: {marker}).\n"
            )
            out += [f"  not passed by the CI harness: {s}" for s in self.no_harness]
            out.append(f"""
CI runs a suite the local full gate does not (route_state.py --ci-harness), and a \
commit green
locally went red there four times in one round. Run that suite on the exact commit, on \
a clean
tree, through the gate runner, into a log that names it:

  {GATE} {planning} <name> --harness {harness} -- '<the CI's command>'

The push goes through once such a log ends `exit=0`. A suite only CI can run: push the \
commit to
another branch first as `<commit>:refs/heads/<branch>` (that push needs only the full \
gate), let
CI run it there, and record that run the same way, with `-- 'gh run watch <run-id> \
--exit-status'`
(or the CI's equivalent) as the command. Bypass only on the user's explicit \
instruction: DSP_SKIP_PUSH_GUARD=1.""")
        if self.unreviewed:
            out.append(
                "[push_guard] `git push` of a commit no pre-push review covers — "
                f"BLOCKED (rung {rung} route: {marker}).\n"
            )
            out += [f"  not reviewed: {s}" for s in self.unreviewed]
            out.append(f"""
With the sins on (rung L's phase-end push, or a review the user asked for) a push \
first gets the
seven-sins review of what it sends (references/sins/lead.md, base = the remote's tip \
after a
`git fetch`); `route_state.py --activate --sins off` ends it once that push is out. \
Its verdict,
{planning}/reviews/<name>-verdict.md, opens with

  reviewed=<full SHA reviewed> base=<full SHA of the base> blocking=<new criticals and \
highs neither fixed nor waived>
  after=<full SHA of each fix committed after the review, space-separated>
  slices=<from>..<to> …   (over {SLICE_MAX} commits: the slices reviewed, each at most \
{SLICE_MAX} commits)

The push goes through once blocking=0, the reviewed commit is an ancestor of the \
pushed one, every
commit between them is on the after= line, the base is an ancestor of the \
remote-tracking ref (for
a new branch, of one of that remote's tracking refs), and a review of more than \
{SLICE_MAX} commits
has slices that cover every one.
Bypass only on the user's explicit instruction: DSP_SKIP_REVIEW=1 (the gate check \
still applies).""")
        return "\n".join(out)


def _pre_push() -> int:
    """Run as git's pre-push hook, at the top of the worktree; a held push exits 1."""
    if os.environ.get("DSP_SKIP_PUSH_GUARD") == "1":
        return 0
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    top = str(pathlib.Path.cwd())
    if not (marker := route_marker(top, session)):
        return 0
    guard = Guard(session, review_skip=os.environ.get("DSP_SKIP_REVIEW") == "1")
    remote = sys.argv[2] if sys.argv[2:] else "origin"
    guard.pre_push(top, marker, remote, sys.stdin)
    if guard.blocked is None:
        return 0
    print(guard.report(guard.blocked), file=sys.stderr)
    return 1


def _ask(*, bypass: bool) -> None:
    """Print the hook's ask for a push that names a bypass."""
    what = "the push guard" if bypass else "the pre-push review"
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": "push_guard.py: this push skips "
                    f"{what} of the active decision-spec-plan route. Approve only if "
                    "you asked for that.",
                }
            }
        )
    )


def _bash_hook() -> int:
    """Run as the PreToolUse:Bash hook on the event on stdin; a held push exits 2."""
    try:
        event = _json_object(sys.stdin.read())
    except ValueError:
        return 0
    given = event.get("tool_input")
    given = cast("dict[str, object]", given) if isinstance(given, dict) else {}
    command = str(given.get("command") or "")
    session = str(event.get("session_id") or "")
    # the bypass variables reach git's hook from the environment, so the words that set
    # them are read first, whatever the walk makes of the rest: a bypass is the user's
    # to give, never a route agent's (copied from a hold message), whatever runs the
    # push (a Makefile's reaches the hook with it set)
    try:
        names = skip_names(command) if active_route() else set[str]()
    except Exception:  # noqa: BLE001 — text the reader cannot split may still set one
        names = {"?"} if "DSP_SKIP" in command else set[str]()
    bypass = bool(names & {"DSP_SKIP_PUSH_GUARD", "?"})
    if names and event.get("agent_id"):
        print(
            "[push_guard] a route agent never skips the push guard or its review "
            "(DSP_SKIP_*) — BLOCKED. Name the push and what holds it in your return; "
            "the lead asks the user.",
            file=sys.stderr,
        )
        return 2
    guard = None
    try:
        guard = Guard(
            session, review_skip=bool(names & {"DSP_SKIP_REVIEW", "?"}), command=command
        )
        cwd = event.get("cwd")
        # every command is read: an alias pushes with no `push` in the text, escapes
        # hide `git`
        for p in (
            walk(
                command,
                cwd if isinstance(cwd, str) and cwd else str(pathlib.Path.cwd()),
            )
            if not bypass
            else ()
        ):
            guard.check(p)
    except Exception as e:  # noqa: BLE001 — a hook that exits 1 lets the push through
        if active_route() and re.search(r"push|git|\\", command):
            print(
                f"[push_guard] the guard failed on this command ({type(e).__name__}: "
                f"{e}) while a decision-spec-plan route is active — BLOCKED. Push with "
                "plain `git [-C <dir>] push <remote> <refs>` in a command of its own.",
                file=sys.stderr,
            )
            return 2
    if guard is not None and guard.blocked is not None:
        print(guard.report(guard.blocked), file=sys.stderr)
        return 2
    if names:
        _ask(bypass=bypass)
    return 0


def main() -> int:
    """Run as --help, as git's pre-push hook (--pre-push), or as the Bash hook."""
    if sys.argv[1:2] in (["--help"], ["-h"]):
        print(__doc__)
        return 0
    if sys.argv[1:2] == ["--pre-push"]:
        return _pre_push()
    return _bash_hook()


if __name__ == "__main__":
    sys.exit(main())
