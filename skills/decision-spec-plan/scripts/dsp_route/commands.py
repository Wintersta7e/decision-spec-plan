# SPDX-License-Identifier: MIT
"""The `git`, `gh` and `glab` commands a Bash tool call runs.

Read as bash reads it (shell_cmd.py), with a word-by-word fallback for text the reader
cannot follow.
"""

import collections
import os
import pathlib
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

import shell_cmd

# Git commands that make a commit: one made before the agent re-reads a ruling skips it
# (F59).
COMMITTING = {"commit", "merge", "cherry-pick", "revert", "am", "pull", "rebase"}
# Plumbing that makes a commit or points a ref at one: held for a hunter alone, beside
# COMMITTING. A saving `git stash` is held only inside the hunted repository, where
# _reads_only passes `stash list` and `show` alone: in its own clone a hunter stashes.
PLUMBING = {"commit-tree", "update-ref"}
# The config keys that pull in more config (`include.path`, `includeIf.<cond>.path`)
# or define an alias, and the variables that pass git config through the environment.
CONFIG_INDIRECT = ("alias.", "include.", "includeif.")
CONFIG_VARS = re.compile(r"(?<![\w$])GIT_CONFIG_(?:PARAMETERS|COUNT|KEY_\d+)=")
# Variables that point git at another config, so an alias read now may not be the one
# git runs; and a subcommand word git can run (a computed one read as text is not).
CONFIG_HOMES = re.compile(r"(?<![\w$])(?:HOME|XDG_CONFIG_HOME|GIT_\w+)=")
GIT_WORD = re.compile(r"[A-Za-z0-9][\w.-]*")
# The git a hunter may run inside the hunted repository: these subcommands, and the
# read forms _reads_only judges (config, branch, tag, worktree, remote, stash).
READ_ONLY_GIT = {
    "",  # `git --version`
    "status",
    "log",
    "show",
    "diff",
    "blame",
    "grep",
    "ls-files",
    "ls-tree",
    "ls-remote",
    "cat-file",
    "rev-parse",
    "rev-list",
    "describe",
    "shortlog",
    "name-rev",
    "merge-base",
    "for-each-ref",
    "show-ref",
}
# `git tag`'s options that only list (push_guard.BRANCH_LISTS is `git branch`'s).
TAG_LISTS = re.compile(
    r"-[ln]\d*|-i|--(list|ignore-case|column|no-column|color)"
    r"|--(sort|format|contains|no-contains|merged|no-merged|points-at)(=.*)?"
)
# `git clone`'s options that take a value — a long one, or any abbreviation of it,
# from the next word unless after an `=`; a short letter from the rest of its word,
# else the next.
CLONE_VALUED = (
    "template",
    "server-option",
    "filter",
    "origin",
    "branch",
    "revision",
    "upload-pack",
    "reference",
    "reference-if-able",
    "depth",
    "shallow-since",
    "shallow-exclude",
    "separate-git-dir",
    "ref-format",
    "jobs",
    "config",
    "bundle-uri",
)
CLONE_SHORT = "objuc"
# Words that run the next word as a command (`sudo tee f`).
RUNS_NEXT = {"sudo", "doas", "env", "command", "exec", "nohup", "nice", "stdbuf"}
# What sets a variable past `NAME=value`, for _Writes: an assignment or a setter's
# argument (`b=1`, `b+=1`, `read b`), arithmetic (`b=1`, `b+=1`, `b++`, `--b`), a
# default (`${b:=x}`, `${b=x}`), and the builtins that may set any (`eval`, `source`).
SETS = re.compile(r"([A-Za-z_]\w*)(\+?)=")
SET_NAME = re.compile(r"[A-Za-z_]\w*(?=\+?=|$)")
ARITH_SETS = re.compile(
    r"(?<!\w)([A-Za-z_]\w*)\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))"
    r"|(?:\+\+|--)\s*([A-Za-z_]\w*)"
)
DEFAULT_SETS = re.compile(r"\$\{([A-Za-z_]\w*):?=")
SETS_ANY = {"eval", "source", "."}
# `git config`'s read actions, the options that only shape a read (those in
# CONFIG_VALUED take a value), and the subcommands that write (_config_writes).
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
CONFIG_MODIFIERS = {
    "--show-origin",
    "--show-scope",
    "--name-only",
    "-z",
    "--null",
    "--global",
    "--local",
    "--system",
    "--worktree",
}
CONFIG_VALUED = {"-f", "--file", "--type", "--default"}
CONFIG_WRITE_SUBCOMMANDS = {"set", "unset", "rename-section", "remove-section", "edit"}
# Tools that publish to a package registry or an image registry, with the verbs that do:
# what they send cannot be taken back, and one lead published five immutable packages on
# a bare "go" (F81). A verb counts anywhere in the command's words, and so does `--push`
# (`docker buildx build --push`) or a computed word (outward.py); a false match only
# asks.
PUBLISHERS = {
    "gradle": {"publish"},
    "gradlew": {"publish"},
    "skopeo": {"copy"},
    "crane": {"push", "copy"},
    "npm": {"publish"},
    "pnpm": {"publish"},
    "yarn": {"publish"},
    "bun": {"publish"},
    "deno": {"publish"},
    "vsce": {"publish"},
    "cargo": {"publish"},
    "twine": {"upload"},
    "poetry": {"publish"},
    "uv": {"publish"},
    "flit": {"publish"},
    "hatch": {"publish"},
    "gem": {"push"},
    "dotnet": {"push"},
    "nuget": {"push"},
    "mvn": {"deploy"},
    "docker": {"push"},
    "podman": {"push"},
    "helm": {"push"},
}
# How many script files deep a command's scripts are read.
SCRIPT_DEPTH = 3
# The hosts' command-line tools: `glab`'s review notes are held like `gh`'s (F104).
HOSTS = ("gh", "glab")
# How many words after a `git`, `gh`, `glab` or publisher's word text_commands reads.
TEXT_WORDS = 40


class _Text(NamedTuple):
    """A command being read, its script depth, and the script names it uses twice.

    A script so named may be written by the command before it runs.
    """

    command: str
    depth: int
    twice: frozenset[str]


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


def _read(command: str) -> tuple[list[shell_cmd.Event], frozenset[str]] | None:
    """Return the command's events and script names used twice; None if unreadable.

    A script is named by the words of the commands run and by the files written.
    """
    try:
        found = shell_cmd.events(command)
        named = [
            w.text for _, c in found if isinstance(c, shell_cmd.Cmd) for w in c.words
        ]
        named += [
            c.script.text
            for _, c in found
            if isinstance(c, shell_cmd.Opaque) and c.script
        ]
        named = [_basename(t) for t in named]
        named += [_basename(t.text) for t, _ in shell_cmd.redirects(command)]
    except Exception:  # noqa: BLE001 — unreadable text falls back to the text check
        return None
    counts = collections.Counter(named)
    return found, frozenset(n for n, k in counts.items() if k > 1)


def _computed(
    c: shell_cmd.Cmd, env: dict[str, str], command: str
) -> shell_cmd.Cmd | list[shell_cmd.Cmd] | None:
    """Return the command bash runs for a computed name, or the commands in its words.

    A variable the command sets once is read as that value; one it sets more than once,
    in a loop or by `read` sends the whole text to the word read (None). A name the
    command's own assignments do not fill has only its own words read (text_commands).
    """
    refs = [m[1] for m in re.finditer(r"\$\{?([A-Za-z_]\w*)", c.words[0].text)]
    sets = sum(len(re.findall(rf"(?<![\w${{]){v}(?!\w)", command)) for v in refs)
    name = c.words[0].expand(env) if sets == 1 else None
    if name is None and sets:
        return None
    if name is None:
        return text_commands(" ".join(w.text for w in c.words))
    if re.search(r"[*?\[]", name):  # a glob the shell expands against files
        return None
    # bash splits the value into words (`G='gh pr merge'; $G 5`, `E=; $E gh …`) on IFS.
    # A command that touches IFS splits on the value read and on any punctuation too:
    # one set again where it cannot be read (`unset`, `export`, `read`, a subshell) then
    # only splits more than bash would, never less.
    if not re.search(r"\bIFS\b", command):
        parts = name.split()
    else:
        ifs = "|[" + re.escape(env["IFS"]) + "]" if env.get("IFS") else ""
        parts = [p for p in re.split(r"[^\w./-]" + ifs, name) if p]
    words = [*map(shell_cmd.literal, parts), *c.words[1:]]
    return shell_cmd.Cmd(c.assigns, words) if words else []


def _resolve(
    c: shell_cmd.Cmd, env: dict[str, str], command: str
) -> shell_cmd.Cmd | list[shell_cmd.Cmd] | None:
    """Return c with its computed name read (_computed); a bare assignment sets env."""
    if not c.words:
        env |= {n: x for n, v in c.assigns if (x := v.expand(env)) is not None}
        return c
    return c if c.words[0].static else _computed(c, env, command)


def _script(
    target: shell_cmd.Cmd | shell_cmd.Opaque, here: str | None, depth: int
) -> tuple[shell_cmd.Word | None, str | None]:
    """Return the script file target runs and its text, None where it cannot be read."""
    if isinstance(target, shell_cmd.Opaque):
        script = target.script
        return script, (
            shell_cmd.read_script(script, here) if depth < SCRIPT_DEPTH else None
        )
    script = target.words[0] if target.words and depth < SCRIPT_DEPTH else None
    return script, shell_cmd.run_script(script, here)


def _nested(
    read: _Text, script: shell_cmd.Word | None, text: str | None, here: str | None
) -> list[shell_cmd.Cmd] | None:
    """Return the commands of a script file the command runs; None if unreadable.

    One the command writes before it runs has the command's own words read too.
    """
    if text is None or script is None:  # script is set wherever text was read
        return None
    inner = bash_commands(text, here, read.depth + 1)
    if inner is not None and _basename(script.text) in read.twice:
        inner += text_commands(read.command)
    return inner


def _dir_after(c: shell_cmd.Cmd, here: str | None) -> str | None:
    """Return the shell's directory after c: None after a `cd` to a computed path."""
    if c.name in ("pushd", "popd"):
        return None
    if c.name != "cd":
        return here
    to = next((w for w in c.words[1:] if w.text not in ("-L", "-P", "--")), None)
    path = _home(to.text if to else "~")
    if (to and (not to.static or to.text == "-")) or not (
        here or pathlib.Path(path).is_absolute()
    ):
        return None
    return os.path.normpath(pathlib.Path(here or "", path))


class Placed(shell_cmd.Cmd):
    """A command bash_commands read, with here, the directory it runs in.

    here is None where the reader cannot compute it (a `cd` to a computed path).
    """

    def __init__(self, words: list[shell_cmd.Word], here: str | None) -> None:
        """Hold the command's words and its directory."""
        super().__init__([], words)
        self.here: str | None = here


def _tools(c: shell_cmd.Cmd, here: str | None) -> list[shell_cmd.Cmd] | None:
    """Return each `git` command in c and its first host tool or publisher, from there.

    None when a git subcommand is computed. Every `git` word counts (`sudo -u git git
    push`); only the first `gh`, `glab` or publisher, whose check reads all the words
    after it (each later one took the line to quadratic time). Each is Placed in here.
    """
    out: list[shell_cmd.Cmd] = []
    names = [_basename(w) for w in c.argv]
    for i, name in enumerate(names):
        if name == "git" or (name in (*HOSTS, *PUBLISHERS) and name not in names[:i]):
            cmd = Placed(c.words[i:], here)
            if (g := shell_cmd.git_args(cmd)) and g[1] is None:
                return None
            out.append(cmd)
    return out


def bash_commands(
    command: str, cwd: str | None = None, depth: int = 0
) -> list[shell_cmd.Cmd] | None:
    """Return each `git`, `gh`, `glab` and PUBLISHERS command the Bash command runs.

    Each is read from that word on (`sudo git commit`), as bash reads the command
    (shell_cmd.py): regexes over the text missed wrapped and quoted forms and
    backtracked for 36 s on a long line. A script file it runs is read in turn, three
    deep. None when a part cannot be read — stdin or an unreadable script fed to a
    shell, a computed `bash -c` or `eval`, a computed git subcommand — or the reader
    fails on it (nesting too deep): the caller then reads the words (text_commands). A
    computed command name the command's own assignments do not fill (`$PY -m pytest`)
    has only its own words read so: read with the whole text, a commit message naming
    `gh release create` beside it was held.
    """
    if (parsed := _read(command)) is None:
        return None
    found, twice = parsed
    read = _Text(command, depth, twice)
    out: list[shell_cmd.Cmd] = []
    # each shell's directory, where a script path is read from: None after a `cd` to a
    # computed path
    dirs = [cwd]
    # the command's own `NAME=value` assignments (`G=gh; $G pr merge 5`)
    env: dict[str, str] = {}
    for kind, event in found:
        if kind == "open":
            dirs.append(dirs[-1])
            continue
        if event is None:  # a subshell's close
            dirs = dirs[:-1] or dirs
            continue
        here = dirs[-1]
        c = None
        if isinstance(event, shell_cmd.Cmd):
            c = _resolve(event, env, command)
            if c is None:
                return None
            if isinstance(c, list):
                out += c
                continue
        script, text = _script(event if c is None else c, here, depth)
        if c is not None and text is None:
            dirs[-1] = _dir_after(c, here)
            more = _tools(c, here)
        else:
            more = _nested(read, script, text, here)
        if more is None:
            return None
        out += more
    return out


def text_commands(command: str) -> list[shell_cmd.Cmd]:
    """Return each `git`, HOSTS and PUBLISHERS command in text the reader cannot follow.

    Read word by word: from that word to the next such word, at most 40 words. A regex
    over the text for `gh` or `push` held a stub `gh` on PATH, a JS `.push(` and a plain
    push (2026-10-31). The blank-split words, ends trimmed, count too: a heredoc's body
    is text to the reader but commands to a shell fed it (`bash <<EOF`), and the reader
    fails on nesting too deep.
    """
    texts = [re.sub(r"^[$(`'\"]+|[)`'\";&|]+$", "", t) for t in command.split()]
    try:
        read = [w.text for w in shell_cmd.words(command)]
    except Exception:  # noqa: BLE001 — the blank-split words alone
        read = []
    texts = read + texts
    # a NAME=value word is read as its value (`X='gh pr close 5'`)
    names = [_basename(re.sub(r"^[A-Za-z_]\w*=", "", t)) for t in texts]
    out: list[shell_cmd.Cmd] = []
    for i, name in enumerate(names):
        if name in ("git", *HOSTS, *PUBLISHERS):
            # only a git, gh or glab word ends one: a publisher's may be a value
            # (`gh -R npm pr merge`)
            end = min(len(names), i + TEXT_WORDS + 1)
            ends = ("git", *HOSTS)
            end = next((k for k in range(i + 1, end) if names[k] in ends), end)
            cmd = shell_cmd.Cmd(
                [], [shell_cmd.literal(t) for t in [name, *texts[i + 1 : end]]]
            )
            cmd.loose = True  # words in no known order: outward_cmd reads them loosely
            out.append(cmd)
    return out


def _ff_only(args: Sequence[shell_cmd.Word]) -> bool:
    """Return whether the last of --ff, --no-ff and --ff-only in args is --ff-only."""
    modes = [a.text for a in args if a.text in ("--ff", "--no-ff", "--ff-only")]
    return modes[-1:] == ["--ff-only"]


def makes_commit(command: str, cwd: str | None = None) -> bool:
    """Return whether the command makes a commit of its own.

    A fast-forward-only merge makes none (the last of --ff, --no-ff and --ff-only is the
    one git uses).
    """
    cmds = bash_commands(command, cwd)
    if cmds is None:
        cmds = text_commands(command)
    return any(
        (g := shell_cmd.git_args(c))
        and g[1] in COMMITTING
        and not (g[1] == "merge" and _ff_only(g[2]))
        for c in cmds
    )


def _config_writes(args: Sequence[shell_cmd.Word]) -> bool:
    """Return whether `git config` with these arguments writes.

    A read is a read action (CONFIG_READS, or the `get` and `list` subcommands) or
    exactly one key and no value, either beside the modifiers that only shape a read
    (CONFIG_MODIFIERS, CONFIG_VALUED). Every other `git config` with arguments writes:
    a hunter's hooks-path change once passed every hold (F109).
    """
    rest: list[str] = []
    words = iter(args)
    for w in words:
        if w.text in CONFIG_VALUED:
            _ = next(words, None)
        elif w.text not in CONFIG_MODIFIERS and w.text.partition("=")[0] not in (
            CONFIG_VALUED  # `--file=<f>`
        ):
            rest.append(w.text)
    if not args or rest[:1] in (["get"], ["list"]):
        return False
    if rest[:1] and rest[0] in CONFIG_WRITE_SUBCOMMANDS:
        return True
    if flags := [t for t in rest if t.startswith("-")]:
        return not set(flags) <= CONFIG_READS
    return len(rest) != 1


def _inline_alias(opts: shell_cmd.GitOptions) -> bool:
    """Return whether git's options set an alias or include config (CONFIG_INDIRECT).

    The alias hides the subcommand it runs: `git -c alias.sv=commit sv` commits while
    makes_commit reads `sv`; `-c include.path=<file>` may define one.
    """
    for opt, value in opts:
        if opt in ("-c", "--config-env") and value is not None:
            key = value.text
        elif opt.startswith("--config-env="):
            key = opt.removeprefix("--config-env=")
        else:
            continue
        if key.lower().startswith(CONFIG_INDIRECT):
            return True
    return False


def _git_commands(command: str, cwd: str | None) -> list[shell_cmd.Cmd]:
    """Return the commands makes_commit reads: bash_commands, else text_commands."""
    cmds = bash_commands(command, cwd)
    return text_commands(command) if cmds is None else cmds


def writes_git_config(command: str, cwd: str | None = None) -> bool:
    """Return whether the command writes git's config or runs git with an inline alias.

    Read as makes_commit reads it; any other `-c k=v` is judged by its subcommand. A
    git command beside a GIT_CONFIG_* assignment (CONFIG_VARS) counts as an inline
    alias: read in the text, so `export` and `env` set it alike.
    """
    found = False
    for c in _git_commands(command, cwd):
        if (g := shell_cmd.git_args(c)) is None:
            continue
        found = True
        opts, sub, args = g
        if _inline_alias(opts) or (sub == "config" and _config_writes(args)):
            return True
    return found and bool(CONFIG_VARS.search(command))


def _hunter_writes(sub: str, args: Sequence[shell_cmd.Word]) -> str | None:
    """Return what `git <sub> <args>` writes that a hunter may not, anywhere."""
    if sub in COMMITTING and not (sub == "merge" and _ff_only(args)):
        return "a commit"
    if sub in PLUMBING:
        return f"a commit by `git {sub}`"
    if sub == "config" and _config_writes(args):
        return "a git config write"
    return None


def _reads_only(sub: str, args: Sequence[shell_cmd.Word]) -> bool:
    """Return whether `git <sub> <args>` only reads: READ_ONLY_GIT, or a read form.

    `config` reads, `branch` and `tag` in list forms, `worktree list`, `remote` bare,
    `-v`, `show` or `get-url`, `stash list` and `show`.
    """
    import push_guard  # loaded by hunter_git, its one caller

    texts = [w.text for w in args]
    first = texts[0] if texts else ""
    flags = [t for t in texts if t.startswith("-")]
    listed = len(flags) == len(texts) or bool({"-l", "--list"} & set(texts))
    forms: dict[str, Callable[[], bool]] = {
        "config": lambda: not _config_writes(args),
        "branch": lambda: (
            listed and all(push_guard.BRANCH_LISTS.fullmatch(t) for t in flags)
        ),
        "tag": lambda: listed and all(TAG_LISTS.fullmatch(t) for t in flags),
        "worktree": lambda: first == "list",
        "remote": lambda: (
            set(texts) <= {"-v", "--verbose"} or first in ("show", "get-url")
        ),
        "stash": lambda: first in ("list", "show"),
    }
    form = forms.get(sub)
    return form() if form else sub in READ_ONLY_GIT


def _git_dir(here: str | None, opts: shell_cmd.GitOptions) -> str | None:
    """Return the directory git runs in from here after its `-C` options.

    None when here or a `-C` is one the hook cannot compute.
    """
    for opt, value in opts:
        if opt != "-C":
            continue
        to = _home(value.text) if value and value.static else None
        if to is None or (here is None and not pathlib.Path(to).is_absolute()):
            return None
        here = str(pathlib.Path(here or "/") / to)
    return here


def _clone_targets(args: Sequence[shell_cmd.Word]) -> list[shell_cmd.Word] | None:
    """Return the words naming where `git clone <args>` writes, else None.

    Its destination, the last word that is neither an option nor an option's value
    (CLONE_VALUED, CLONE_SHORT), and each `--separate-git-dir`. None when git names the
    destination itself (after the source, in the current directory) or a computed word
    may be an option.
    """
    targets: list[shell_cmd.Word] = []
    plain: list[shell_cmd.Word] = []
    words = iter(args)
    for w in words:
        t = w.text
        if not w.static:
            return None
        if t == "--":
            plain += words
        elif t.startswith("--"):
            name, eq, value = t[2:].partition("=")
            full = name if name in CLONE_VALUED else None
            full = full or next((o for o in CLONE_VALUED if o.startswith(name)), None)
            to = shell_cmd.literal(value) if eq else next(words, None) if full else None
            if full == "separate-git-dir":
                targets.append(to or shell_cmd.literal(""))
        elif t.startswith("-") and t != "-":
            short = [i for i, ch in enumerate(t) if ch in CLONE_SHORT]
            if short and short[0] == len(t) - 1:
                _ = next(words, None)
        else:
            plain.append(w)
    return [*targets, plain[-1]] if len(plain) > 1 else None


def _clone_out(
    here: str | None, args: Sequence[shell_cmd.Word], root: pathlib.Path
) -> bool:
    """Return whether every place `git clone <args>` run in here writes is out of root.

    False when one is a word the hook cannot compute, or relative to an unknown here.
    """
    targets = _clone_targets(args)
    for w in targets or ():
        to = pathlib.Path(_home(w.text)) if w.static and w.text else None
        if to is None or not (here or to.is_absolute()):
            return False
        if pathlib.Path(here or "/", to).resolve().is_relative_to(root):
            return False
    return targets is not None


def hunter_git(command: str, cwd: str | None, repo: str) -> str | None:
    """Return what the command's git does that a hunter may not, past makes_commit.

    Anywhere: a subcommand the hook cannot read (`git $x`), commit plumbing (PLUMBING),
    and an alias read as push_guard.unalias reads it in the command's directory, its
    command judged in turn; an alias it cannot read is held. Inside repo — the
    directory in effect for each command, after a `cd` and `-C`; one the hook cannot
    compute counts as inside — only what _reads_only passes: a denylist of writing
    forms never ends (notes, replace, symbolic-ref, reset, a saving stash, …) — and a
    `git clone` writing only outside repo (_clone_out), the brief's first step.
    None when nothing is held. For a hunter alone: other agents' commits are judged by
    COMMITTING.
    """
    import push_guard  # only a hunter's git command needs it

    config_env = bool(CONFIG_HOMES.search(command))
    cmds = bash_commands(command, cwd)
    # text the reader cannot follow: its directory is cwd unless it may change it
    moved = re.search(r"(?<![\w-])(?:cd|pushd|popd)(?![\w-])", command)
    if cmds is None:
        cmds = text_commands(command)
    root = pathlib.Path(repo).resolve()
    for c in cmds:
        if (g := shell_cmd.git_args(c)) is None:
            continue
        opts, sub, args = g
        if sub is None or (c.loose and sub and not GIT_WORD.fullmatch(sub)):
            return "a git subcommand the hook cannot read"
        if held := _hunter_writes(sub, args):
            return held
        here = c.here if isinstance(c, Placed) else (None if moved else cwd)
        here = _git_dir(here, opts)
        resolved, texts, form = push_guard.unalias(
            here, sub, [w.text for w in args], opts, config_env=config_env or not here
        )
        if form or resolved is None:
            return form or "a git alias the hook cannot read"
        words = args if resolved == sub else [shell_cmd.literal(t) for t in texts]
        if resolved != sub and (held := _hunter_writes(resolved, words)):
            return f"{held} through the alias `git {sub}`"
        inside = here is None or pathlib.Path(here).resolve().is_relative_to(root)
        clones_out = resolved == "clone" and _clone_out(here, words, root)
        if inside and not (_reads_only(resolved, words) or clones_out):
            return (
                f"`git {resolved}` in the hunted repository, where a hunter only reads"
            )
    return None


class _Writes:
    """The files a command writes by an output redirect or `tee`, read as bash runs it.

    Each is read in the directory in effect where it is written — a `cd` before it
    moves it, a subshell's ends at its `)` — with the command's own assignments, HOME
    and PWD set; a `$( )` and a `bash -c` or `eval` string are read where they run. In
    the body of a `for` loop over literal words its variable takes each word in turn;
    over a computed list, in a body no `do` opens, once the body sets it again, and
    after its `done`, it is unknown. A subshell — a `( )`, a `$( )`, a `bash -c` or
    `eval` string, a pipeline stage — leaves each variable it sets unknown, and the
    variable of each loop it leaves open: never more readable than bash leaves it.
    """

    def __init__(self) -> None:
        """Start with no file and HOME known."""
        self.out: list[pathlib.Path | None] = []
        self.env: dict[str, str | None] = {"HOME": str(pathlib.Path.home())}
        # each loop open where the words are read: its variable, None for a `while`
        self.loops: list[str | None] = []
        # the variables of the open `for` loops over literal words, with their words
        self.each: dict[str, list[str]] = {}
        # the `for` header just read, its body not yet: its variable and its words
        self.header: tuple[str, list[str] | None] | None = None

    def place(self, w: shell_cmd.Word, here: str | None) -> None:
        """Record the files w names, read in here: None when one cannot be computed."""
        self.env["PWD"] = here
        for text in w.expand_each(self.env, self.each):
            if text is not None and shell_cmd.TEMP in text:
                continue  # a `$(mktemp)` directory, in no repository
            if text is None or (here is None and not pathlib.Path(text).is_absolute()):
                self.out.append(None)
            else:
                self.out.append((pathlib.Path(here or "/") / text).resolve())

    def unbind(self, name: str) -> None:
        """Make name unknown: set to a value the reader does not compute."""
        _ = self.each.pop(name, None)
        self.env[name] = None

    def forget(self, before: dict[str, str | None]) -> None:
        """Make unknown each variable set since before: a subshell's ends with it."""
        for name, value in list(self.env.items()):
            if before.get(name) != value:
                self.env[name] = None

    def open_loop(self, words: list[shell_cmd.Word]) -> None:
        """Open the `for` or `select` loop words open; its variable binds at `do`."""
        loop = shell_cmd.for_list(words)
        self.loops.append(loop[0] if loop else None)  # `for ((…))` has none
        if loop is None:
            return
        name, listed = loop
        values = [w.expand(self.env) for w in listed or ()]
        known = [v for v in values if v is not None]
        self.unbind(name)
        literal = listed is not None and len(known) == len(values)
        self.header = (name, known if literal else None)

    def open_body(self, t: shell_cmd.Word) -> None:
        """Bind the variable of the header just read when t, its body's first, is `do`.

        Another body (`{ …; }`) no `done` closes: its loop is left, its variable
        unknown.
        """
        if self.header is None:
            return
        name, values = self.header
        self.header = None
        if not (t.static and t.text == "do"):
            _ = self.loops.pop()
        elif values is not None:
            self.each[name] = values

    def close_loop(self) -> None:
        """Leave the innermost loop at its `done`: its variable is unknown after it."""
        self.header = None
        if self.loops and (name := self.loops.pop()):
            self.unbind(name)

    def close_loops(self, depth: int) -> None:
        """Leave each loop past the first depth, as a subshell that opened it ends."""
        while len(self.loops) > depth:
            self.close_loop()

    def sets(self, words: list[shell_cmd.Word]) -> None:
        """Record the variables a command sets.

        An assignment's value is computed; an append's, one to a bound loop variable,
        a SETTERS argument, `printf -v`'s and `let`'s are unknown, and every variable
        after a SETS_ANY builtin.
        """
        import push_guard  # loaded by hunter_git as well

        assigns = [(w, m) for w in words if (m := SETS.match(w.text))]
        if words and len(assigns) == len(words):
            for w, m in assigns:
                if m[2] or m[1] in self.each:
                    self.unbind(m[1])
                else:
                    value = w.expand(self.env)
                    self.env[m[1]] = value and value.partition("=")[2]
            return
        i = next(
            (i for i, w in enumerate(words) if not shell_cmd.ASSIGN.match(w.text)),
            len(words),
        )
        name = _basename(words[i].text) if i < len(words) else ""
        texts = [w.text for w in words[i + 1 :]]
        names: list[str] = []
        if name in SETS_ANY:
            names = [*self.env, *self.each]
        elif name in push_guard.SETTERS:
            names = [m[0] for t in texts if (m := SET_NAME.match(t))]
        elif name == "printf":
            pairs = zip(texts, [*texts[1:], ""], strict=True)
            names = [t[2:] or after for t, after in pairs if t.startswith("-v")]
        elif name == "let":
            names = [m[1] or m[2] for t in texts for m in ARITH_SETS.finditer(t)]
        for n in names:
            self.unbind(n)

    def word_sets(self, w: shell_cmd.Word, *, arith: bool) -> None:
        """Make unknown each variable w sets: a default, a `$((…))` sum, or w's own.

        With arith w is a word of a `((…))`, arithmetic.
        """
        exps = [s for k, s in w.parts if k == "exp"]
        sums = [w.text] if arith else [s for s in exps if s.startswith("$((")]
        names = [m[1] for s in exps for m in DEFAULT_SETS.finditer(s)]
        names += [m[1] or m[2] for s in sums for m in ARITH_SETS.finditer(s)]
        for name in names:
            self.unbind(name)

    def end(self, words: list[shell_cmd.Word], here: str | None) -> str | None:
        """Record a command's assignments and tee files; return the directory after."""
        while words and words[0].static and words[0].text in shell_cmd.KEYWORDS:
            if words[0].text in ("while", "until"):
                self.loops.append(None)
            words = words[1:]
        if words and words[0].static and words[0].text in ("for", "select"):
            self.open_loop(words)
        self.sets(words)
        names = [_basename(w.text) for w in words]
        if "tee" in names and (names[0] == "tee" or names[0] in RUNS_NEXT):
            for w in words[names.index("tee") + 1 :]:
                if not w.text.startswith("-"):
                    self.place(w, here)
        return _dir_after(shell_cmd.Cmd([], words), here)

    def add_word(
        self, t: shell_cmd.Word, words: list[shell_cmd.Word], here: str | None
    ) -> None:
        """Add t to a command's words, reading a `bash -c` or `eval` string in it.

        A `done` closes its loop first: bash opens a redirect on the loop before the
        loop sets its variable.
        """
        if not words:
            self.open_body(t)
        if t.static and t.text == "done" and not words:
            self.close_loop()
        nested = words and (words[-1].text == "-c" or words[0].text == "eval")
        if nested and t.static and shell_cmd.SYNTAX.search(t.text):
            self.walk(shell_cmd.scan(t.text)[0], here)
        words.append(t)

    def walk(self, tokens: list[shell_cmd.Token], here: str | None) -> None:
        """Record the files tokens write, run from here.

        Read as a subshell: the loops open outside are set aside and each variable set
        in tokens is unknown at their end; each `( )` and pipeline stage in them alike.
        A `cd` in a pipeline stage leaves the directory unknown (bash's `lastpipe`).
        """
        outer, header, before = self.loops, self.header, dict(self.env)
        self.loops, self.header = [], None
        stack: list[tuple[str | None, int, dict[str, str | None]]] = []
        words: list[shell_cmd.Word] = []
        op: str | None = None
        last: shell_cmd.Token | None = None
        arith: int | None = None  # the depth of the open `((`, whose words are sums
        piped = False  # the command being read follows a `|` or `&`
        for t in tokens:
            if isinstance(t, str):
                op = t if t in shell_cmd.REDIRECTS else None
                if op is None:
                    stage = piped or t in shell_cmd.ASYNC
                    env = dict(self.env)
                    after = self.end(words, here)
                    if stage:
                        self.forget(env)
                    here = None if stage and after != here else after
                    piped, words = t in shell_cmd.ASYNC, []
                    if t == "(":
                        arith = len(stack) if arith is None and last == "(" else arith
                        stack.append((here, len(self.loops), dict(self.env)))
                    elif t == ")" and stack:
                        here, depth, env = stack.pop()
                        self.close_loops(depth)
                        self.forget(env)
                        arith = (
                            None if arith is not None and len(stack) < arith else arith
                        )
                last = t
                continue
            for sub in t.subs:
                self.walk(sub, here)
            self.word_sets(t, arith=arith is not None)
            if op in shell_cmd.OUTPUTS:
                self.place(t, here)
            elif op is None:
                self.add_word(t, words, here)
            op, last = None, t
        _ = self.end(words, here)
        self.close_loops(0)
        self.forget(before)
        self.loops, self.header = outer, header


def written_paths(command: str, cwd: str | None) -> list[pathlib.Path | None] | None:
    """Return each file the command writes by an output redirect or `tee`, resolved.

    Read as _Writes reads them, from cwd. None in place of one the hook cannot compute
    (a name it cannot expand, a relative one in a directory it cannot compute), and
    for the whole when the reader fails.
    """
    writes = _Writes()
    try:
        writes.walk(shell_cmd.scan(command)[0], cwd)
    except Exception:  # noqa: BLE001 — text the reader fails on writes what it cannot see
        return None
    return writes.out
