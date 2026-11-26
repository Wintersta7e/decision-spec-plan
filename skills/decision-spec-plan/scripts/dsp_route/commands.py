# SPDX-License-Identifier: MIT
"""The `git`, `gh` and `glab` commands a Bash tool call runs.

Read as bash reads it (shell_cmd.py), with a word-by-word fallback for text the reader
cannot follow.
"""

import collections
import os
import pathlib
import re
from collections.abc import Sequence
from typing import NamedTuple

import shell_cmd

# Git commands that make a commit: one made before the agent re-reads a ruling skips it
# (F59).
COMMITTING = {"commit", "merge", "cherry-pick", "revert", "am", "pull", "rebase"}
# The config keys that pull in more config (`include.path`, `includeIf.<cond>.path`)
# or define an alias, and the variables that pass git config through the environment.
CONFIG_INDIRECT = ("alias.", "include.", "includeif.")
CONFIG_VARS = re.compile(r"(?<![\w$])GIT_CONFIG_(?:PARAMETERS|COUNT|KEY_\d+)=")
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
# Commands that run the command after their options (`sudo -u x bash -c '…'`), with the
# options that take the next word as their value; find runs one after each FIND_RUNS
# word. The reader unwraps none of them, so a shell or `eval` they run is read here.
RUNNERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T", "-R"},
    "doas": {"-u", "-C"},
    "xargs": {"-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a"},
}
FIND_RUNS = {"-exec", "-execdir", "-ok", "-okdir"}


class Body(shell_cmd.Cmd):
    """A computed `eval` or shell `-c` body: it may run any command (outward.py)."""

    loose: bool = True


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

    One the command writes before it runs has the command's own words read too, and
    one the reader cannot follow has its words read (text_commands): read from the
    command's text, its `eval "$CMD"` passed unseen.
    """
    if text is None or script is None:  # script is set wherever text was read
        return None
    inner = bash_commands(text, here, read.depth + 1)
    if inner is None:
        inner = text_commands(text)
    if _basename(script.text) in read.twice:
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


def _tools(c: shell_cmd.Cmd) -> list[shell_cmd.Cmd] | None:
    """Return each `git` command in c and its first host tool or publisher, from there.

    None when a git subcommand is computed. Every `git` word counts (`sudo -u git git
    push`); only the first `gh`, `glab` or publisher, whose check reads all the words
    after it (each later one took the line to quadratic time).
    """
    out: list[shell_cmd.Cmd] = []
    names = [_basename(w) for w in c.argv]
    for i, name in enumerate(names):
        if name == "git" or (name in (*HOSTS, *PUBLISHERS) and name not in names[:i]):
            cmd = shell_cmd.Cmd([], c.words[i:])
            if (g := shell_cmd.git_args(cmd)) and g[1] is None:
                return None
            out.append(cmd)
    return out


def _positions(words: Sequence[shell_cmd.Word]) -> list[int]:
    """Return where the words name a command: the first, and each one a RUNNERS runs.

    After a runner's options (`sudo -u x cmd`, `xargs -I{} cmd`), or after each of
    find's FIND_RUNS words. Only there does an `eval` or shell word run a body:
    anywhere in the words, `echo eval` dropped the line and the script after it.
    """
    out: list[int] = []
    i = 0
    while i < len(words):
        out.append(i)
        name = _basename(words[i].text)
        if name == "find":
            return out + [k + 1 for k, w in enumerate(words) if w.text in FIND_RUNS]
        if name not in RUNNERS:
            break
        j = i + 1
        while (
            j < len(words) and words[j].text.startswith("-") and words[j].text != "--"
        ):
            j += 2 if words[j].text in RUNNERS[name] else 1
        i = j + (j < len(words) and words[j].text == "--")
    return out


def _body_of(e: shell_cmd.Opaque, command: str) -> Body | None:
    """Return a Body for text a shell runs that the reader cannot see, when computed.

    A computed `eval` or `-c` string (`eval $Z`), a shell's computed script path
    (`bash "$F"`), or a shell reading stdin in a command with an expansion (`echo "$C"
    | bash`, `bash <<< "$C"`): each may run any command. None for a static one.
    """
    if e.script is not None:
        computed = not (e.sourced or e.script.static)
        return Body([], [shell_cmd.literal(str(e)), e.script]) if computed else None
    stdin = not e.words or e.words[0].text == "-"
    if any(not w.static for w in e.words) or (
        stdin and not e.sourced and re.search(r"[$`]", command)
    ):
        return Body([], [shell_cmd.literal(str(e)), *e.words])
    return None


def _runs(
    c: shell_cmd.Cmd, read: _Text, here: str | None, env: dict[str, str]
) -> tuple[list[shell_cmd.Cmd], bool]:
    """Return the commands of each shell or `eval` c runs, and whether one is unread.

    Only where c's words name a command (_positions): `sudo bash -c '…'`, `xargs sh -c
    "$C"`, read as bash reads them.
    """
    out: list[shell_cmd.Cmd] = []
    unread = False
    for i in _positions(c.words):
        if _basename(c.words[i].text) in ("eval", *shell_cmd.SHELLS):
            ran, missed = _walk(shell_cmd.command_events(c.words[i:]), read, here, env)
            out += ran
            unread |= missed
    return out, unread


def _cmd(
    event: shell_cmd.Cmd, read: _Text, here: str | None, env: dict[str, str]
) -> tuple[list[shell_cmd.Cmd], bool, str | None]:
    """Return a simple command's commands, whether a part is unread, and the dir after.

    A script it runs by path is read in turn (_nested), a shell or `eval` it runs
    through a runner too (_runs).
    """
    c = _resolve(event, env, read.command)
    if c is None:
        return [], True, here
    if isinstance(c, list):
        return c, False, here
    script, text = _script(c, here, read.depth)
    if text is not None:
        more = _nested(read, script, text, here)
        return more or [], more is None, here
    tools = _tools(c)
    ran, missed = _runs(c, read, here, env)
    return [*(tools or []), *ran], tools is None or missed, _dir_after(c, here)


def _opaque(
    e: shell_cmd.Opaque, read: _Text, here: str | None
) -> tuple[list[shell_cmd.Cmd], bool]:
    """Return the commands of text a shell runs and whether it is unread.

    A script read in turn; one the reader cannot see adds a Body when computed
    (_body_of).
    """
    script, text = _script(e, here, read.depth)
    if (more := _nested(read, script, text, here)) is not None:
        return more, False
    body = _body_of(e, read.command)
    return [body] if body else [], True


def _walk(
    found: Sequence[shell_cmd.Event],
    read: _Text,
    cwd: str | None,
    env: dict[str, str],
) -> tuple[list[shell_cmd.Cmd], bool]:
    """Return the commands of the events found, and whether a part could not be read.

    A part that cannot be read leaves the rest read: dropped whole to the word reader,
    which reads no script, `echo ls | bash; bash pub.sh` passed its publish.
    """
    out: list[shell_cmd.Cmd] = []
    unread = False
    # each shell's directory, where a script path is read from: None after a `cd` to a
    # computed path or a sourced script the reader cannot see
    dirs = [cwd]
    for kind, event in found:
        if kind == "open":
            dirs.append(dirs[-1])
            continue
        if event is None:  # a subshell's close
            dirs = dirs[:-1] or dirs
            continue
        if isinstance(event, shell_cmd.Cmd):
            ran, missed, dirs[-1] = _cmd(event, read, dirs[-1], env)
        else:
            ran, missed = _opaque(event, read, dirs[-1])
            if missed and event.sourced:
                dirs[-1] = None
        out += ran
        unread |= missed
    return out, unread


def bash_commands(
    command: str, cwd: str | None = None, depth: int = 0
) -> list[shell_cmd.Cmd] | None:
    """Return each `git`, `gh`, `glab` and PUBLISHERS command the Bash command runs.

    Each is read from that word on (`sudo git commit`), as bash reads the command
    (shell_cmd.py): regexes over the text missed wrapped and quoted forms and
    backtracked for 36 s on a long line. A script file it runs is read in turn, three
    deep. A part that cannot be read — stdin or an unreadable script fed to a shell, a
    computed `bash -c` or `eval`, a computed git subcommand — adds the command's words
    (text_commands), and a computed body a Body (_body_of); None when the reader fails
    on the command (nesting too deep): the caller then reads the words. A computed
    command name the command's own assignments do not fill (`$PY -m pytest`) has only
    its own words read so: read with the whole text, a commit message naming `gh release
    create` beside it was held.
    """
    if (parsed := _read(command)) is None:
        return None
    found, twice = parsed
    # the command's own `NAME=value` assignments (`G=gh; $G pr merge 5`)
    out, unread = _walk(found, _Text(command, depth, twice), cwd, {})
    return out + text_commands(command) if unread else out


def text_commands(command: str) -> list[shell_cmd.Cmd]:
    """Return each `git`, HOSTS and PUBLISHERS command in text the reader cannot follow.

    Read word by word: from that word to the next such word (a publisher's: to the next
    HOSTS word), at most 40 words. A regex over the text for `gh` or `push` held a stub
    `gh` on PATH, a JS `.push(` and a plain push (2026-10-31). The blank-split words,
    ends trimmed, count too: a heredoc's body is text to the reader but commands to a
    shell fed it (`bash <<EOF`), and the reader fails on nesting too deep. Each word
    keeps whether it is computed: read as literal text, `eval $Z; npm $V` passed as no
    publish. A computed `eval` or shell `-c` body in the blank-split words adds a Body
    (_body).
    """
    try:
        read = shell_cmd.words(command)
    except Exception:  # noqa: BLE001 — the blank-split words alone
        read = []
    words = [*read, *map(_text_word, command.split())]
    # a NAME=value word is read as its value (`X='gh pr close 5'`)
    names = [_basename(re.sub(r"^[A-Za-z_]\w*=", "", w.text)) for w in words]
    out: list[shell_cmd.Cmd] = []
    for i, name in enumerate(names):
        if name in ("git", *HOSTS, *PUBLISHERS):
            # only a git, gh or glab word ends one: a publisher's may be a value
            # (`gh -R npm pr merge`). A publisher's own words go on past a git word,
            # which may be the command it runs (`uv run git $X`)
            # A run ends where the reader's words do: the blank-split copy after them
            # repeats the command, words before this one too
            end = min(len(read) if i < len(read) else len(names), i + TEXT_WORDS + 1)
            ends = HOSTS if name in PUBLISHERS else ("git", *HOSTS)
            end = next((k for k in range(i + 1, end) if names[k] in ends), end)
            cmd = shell_cmd.Cmd([], [shell_cmd.literal(name), *words[i + 1 : end]])
            cmd.loose = True  # words in no known order: outward_cmd reads them loosely
            out.append(cmd)
    return out + _body(words[len(read) :])


def _shell_body(words: Sequence[shell_cmd.Word], i: int) -> int | None:
    """Return the index of the `-c` string of the shell named by words[i], or None.

    Its options read as bash reads them (`sh -ec "$C"`).
    """
    if _basename(words[i].text) not in shell_cmd.SHELLS:
        return None
    j, shell_c = i + 1, False
    while j < len(words) and words[j].text[:1] in "-+" and words[j].text != "--":
        t = words[j].text
        shell_c |= not t.startswith("--") and "c" in t
        j += 2 if t in shell_cmd.SHELL_VALUED else 1
    j += j < len(words) and words[j].text == "--"
    return j if shell_c and j < len(words) else None


def _computed_at(words: Sequence[shell_cmd.Word], i: int) -> bool:
    """Return whether words[i] runs a computed body: `eval $Z`, `bash -c "$C"`.

    An `eval` whose next word is computed, or a shell's computed `-c` string.
    """
    if _basename(words[i].text) == "eval":
        return any(not w.static for w in words[i + 1 : i + 2])
    j = _shell_body(words, i)
    return j is not None and not words[j].static


def _body(blank: Sequence[shell_cmd.Word]) -> list[shell_cmd.Cmd]:
    """Return a Body for the first computed `eval` or `-c` body in blank-split words.

    Text the reader cannot follow has no command positions: a heredoc's body fed to a
    shell, a command nested too deep for the reader; there a false match only asks.
    """
    for i in range(len(blank)):
        if _computed_at(blank, i):
            return [Body([], list(blank[i : i + TEXT_WORDS + 1]))]
    return []


def _text_word(token: str) -> shell_cmd.Word:
    """Return a blank-split token, its ends trimmed, as a word: computed if it expands.

    A `$` or backtick anywhere in the token marks it, its own `$V` trimmed to `V` too.
    """
    w = shell_cmd.Word()
    w.add(
        "exp" if re.search(r"[$`]", token) else "q",
        re.sub(r"^[$(`'\"]+|[)`'\";&|]+$", "", token),
    )
    return w


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
