"""The `git` and `gh` commands a Bash tool call runs, read as bash reads it (shell_cmd.py), with a
word-by-word fallback for text the reader cannot follow."""

import os
import re

import shell_cmd

# Git commands that make a commit: one made before the agent re-reads a ruling skips it (F59).
COMMITTING = {"commit", "merge", "cherry-pick", "revert", "am", "pull", "rebase"}
# Tools that publish to a package registry or an image registry, with the verbs that do: what
# they send cannot be taken back, and one lead published five immutable packages on a bare "go"
# (F81). A verb counts anywhere in the command's words, and so does `--push` (`docker buildx
# build --push`) or a computed word (outward.py); a false match only asks.
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


def bash_commands(command, cwd=None, depth=0):
    """Each `git`, `gh` and PUBLISHERS command the Bash command runs, from that word on (`sudo git commit`),
    read as bash reads it (shell_cmd.py): regexes over the text missed wrapped and quoted forms and
    backtracked for 36 s on a long line. A script file it runs is read in turn, three deep. None
    when a part cannot be read — stdin or an unreadable script fed to a shell, a computed `bash -c`
    or `eval`, a computed git subcommand — or the reader fails on it (nesting too deep): the
    caller then reads the words (text_commands). A computed command name the command's own
    assignments do not fill (`$PY -m pytest`) has only its own words read so: read with the whole
    text, a commit message naming `gh release create` beside it was held."""
    try:
        found = shell_cmd.events(command)
        # the words a script is named by: those of the commands run, and the files written
        named = [w.text for k, c in found if k == "cmd" for w in c.words]
        named += [c.script.text for k, c in found if k == "opaque" and c.script]
        named = [os.path.basename(t) for t in named]
        named += [os.path.basename(t.text) for t, _ in shell_cmd.redirects(command)]
    except Exception:  # noqa: BLE001 — unreadable text falls back to the text check
        return None
    out = []
    # each shell's directory, where a script path is read from: None after a `cd` to a computed path
    dirs = [cwd]
    env = {}  # the command's own `NAME=value` assignments (`G=gh; $G pr merge 5`)
    for kind, c in found:
        if kind == "open":
            dirs.append(dirs[-1])
            continue
        if kind == "close":
            dirs = dirs[:-1] or dirs
            continue
        here = dirs[-1]
        if kind == "opaque":
            script = c.script
            text = shell_cmd.read_script(script, here) if depth < 3 else None
        else:
            if not c.words:
                env |= {n: x for n, v in c.assigns if (x := v.expand(env)) is not None}
            elif not c.words[0].static:
                # a variable the command sets once is read as that value; one it sets more
                # than once, in a loop or by `read` sends the whole text to the word read
                refs = re.findall(r"\$\{?([A-Za-z_]\w*)", c.words[0].text)
                sets = sum(
                    len(re.findall(rf"(?<![\w${{]){v}(?!\w)", command)) for v in refs
                )
                name = c.words[0].expand(env) if sets == 1 else None
                if name is None and sets:
                    return None
                if name is None:
                    out += text_commands(" ".join(w.text for w in c.words))
                    continue
                if re.search(r"[*?\[]", name):  # a glob the shell expands against files
                    return None
                # bash splits the value into words (`G='gh pr merge'; $G 5`, `E=; $E gh …`) on
                # IFS. A command that touches IFS splits on the value read and on any
                # punctuation too: one set again where it cannot be read (`unset`, `export`,
                # `read`, a subshell) then only splits more than bash would, never less.
                if not re.search(r"\bIFS\b", command):
                    parts = name.split()
                else:
                    ifs = "|[" + re.escape(env["IFS"]) + "]" if env.get("IFS") else ""
                    parts = [p for p in re.split(r"[^\w./-]" + ifs, name) if p]
                words = [*map(shell_cmd.literal, parts), *c.words[1:]]
                if not words:
                    continue
                c = shell_cmd.Cmd(c.assigns, words)
            script = c.words[0] if c.words and depth < 3 else None
            text = shell_cmd.run_script(script, here)
        if kind == "opaque" or text is not None:
            inner = None if text is None else bash_commands(text, here, depth + 1)
            if inner is None:
                return None
            out += inner
            assert script is not None  # text was read from it
            if named.count(os.path.basename(script.text)) > 1:
                # written by the command before it runs: the words it writes count too
                out += text_commands(command)
            continue
        if c.name == "cd":
            to = next(
                (w for w in c.words[1:] if w.text not in ("-L", "-P", "--")), None
            )
            path = os.path.expanduser(to.text if to else "~")
            if (
                to
                and (not to.static or to.text == "-")
                or not (here or os.path.isabs(path))
            ):
                dirs[-1] = None
            else:
                dirs[-1] = os.path.normpath(os.path.join(here or "", path))
        elif c.name in ("pushd", "popd"):
            dirs[-1] = None
        names = [os.path.basename(w) for w in c.argv]
        for i, name in enumerate(names):
            # every `git` word (`sudo -u git git push`); only the first `gh` or publisher, whose
            # check reads all the words after it (each later one took the line to quadratic time)
            if name == "git" or (name in ("gh", *PUBLISHERS) and name not in names[:i]):
                cmd = shell_cmd.Cmd([], c.words[i:])
                if (g := shell_cmd.git_args(cmd)) and g[1] is None:
                    return None
                out.append(cmd)
    return out


def text_commands(command):
    """Each `git`, `gh` and PUBLISHERS command in text the reader cannot follow, read word by word:
    from that word to the next such word, at most 40 words. A regex over the text for `gh` or
    `push` held a stub `gh` on PATH, a JS `.push(` and a plain push (2026-10-31). The blank-split
    words, ends trimmed, count too: a heredoc's body is text to the reader but commands to a shell
    fed it (`bash <<EOF`), and the reader fails on nesting too deep."""
    texts = [re.sub(r"^[$(`'\"]+|[)`'\";&|]+$", "", t) for t in command.split()]
    try:
        read = [w.text for w in shell_cmd.words(command)]
    except Exception:  # noqa: BLE001 — the blank-split words alone
        read = []
    texts = read + texts
    # a NAME=value word is read as its value (`X='gh pr close 5'`)
    names = [os.path.basename(re.sub(r"^[A-Za-z_]\w*=", "", t)) for t in texts]
    out = []
    for i, name in enumerate(names):
        if name in ("git", "gh", *PUBLISHERS):
            # only a git or gh word ends one: a publisher's may be a value (`gh -R npm pr merge`)
            end = min(len(names), i + 41)
            end = next((k for k in range(i + 1, end) if names[k] in ("git", "gh")), end)
            cmd = shell_cmd.Cmd(
                [], [shell_cmd.literal(t) for t in [name, *texts[i + 1 : end]]]
            )
            cmd.loose = True  # words in no known order: outward_cmd reads them loosely
            out.append(cmd)
    return out


def makes_commit(command, cwd=None):
    """Whether the command makes a commit of its own: a fast-forward-only merge makes none (the
    last of --ff, --no-ff and --ff-only is the one git uses)."""
    cmds = bash_commands(command, cwd)
    if cmds is None:
        cmds = text_commands(command)

    def ff_only(args):
        modes = [a.text for a in args if a.text in ("--ff", "--no-ff", "--ff-only")]
        return modes[-1:] == ["--ff-only"]

    return any(
        (g := shell_cmd.git_args(c))
        and g[1] in COMMITTING
        and not (g[1] == "merge" and ff_only(g[2]))
        for c in cmds
    )
