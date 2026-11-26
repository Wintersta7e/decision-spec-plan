# SPDX-License-Identifier: MIT
"""The lead's own writes to the route's repository from its activation (F68).

An edit tool's file, or the files a Bash command writes: redirections, `tee`, `sed -i`,
`perl -i`, `patch` and `git apply`, read as bash reads them (shell_cmd.py).
"""

import itertools
import json
import os
import pathlib
from collections.abc import Mapping, Sequence
from typing import NamedTuple, cast

import shell_cmd

from .common import (
    REGISTRY,
    RegistryEntry,
    RouteArgs,
    as_dict,
    git,
    load_json,
    route_args,
)

# A rebase, merge or cherry-pick in progress: a conflict the lead resolves itself is
# cheaper than a group's checkpoint — while the branch never reached a remote (R9).
IN_PROGRESS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")
# The files the lead may write itself in a route before the hold: a one-line fix is
# cheaper than a group; a third file is execution.
FREE = 2
# The largest patch file read for its target files.
PATCH_MAX = 1_000_000
# sed's and perl's short options that take the next word when nothing follows them in
# their cluster, and perl's that take only an attached value.
SED_VALUED, PERL_CODE, PERL_ATTACHED = "efl", "eE", "IMmxl0CdDF"
# `git apply` options that only read the patch, unless `--apply` is given too.
APPLY_READS = {"--check", "--stat", "--numstat", "--summary", "--cached"}
# `patch` options that take the next word as their value, and the long names of three.
PATCH_VALUED = {"-p", "-i", "-d", "-o", "-r", "-B", "-D", "-F", "-g", "-V", "-Y", "-z"}
PATCH_LONG = {"--strip": "-p", "--input": "-i", "--directory": "-d", "--output": "-o"}
DIR_CHANGES = ("cd", "pushd", "popd")


class Tally(NamedTuple):
    """The repository files one tool call writes and the route run's tally.

    files are (path, whether in a linked worktree); seen, the files already counted.
    """

    files: list[tuple[pathlib.Path, bool]]
    run: str
    seen: list[str]
    path: pathlib.Path


def _resolving(where: pathlib.Path, gitdir: pathlib.Path) -> bool:
    """Return whether a rebase, merge or cherry-pick is in progress, branch unpushed.

    The branch is the one being rebased, else the current one; pushed once any
    `refs/remotes/<remote>/<branch>` exists (R9).
    """
    if not any((gitdir / n).exists() for n in IN_PROGRESS):
        return False
    heads = [gitdir / d / "head-name" for d in IN_PROGRESS[:2]]
    if head := next((h for h in heads if h.is_file()), None):
        branch = head.read_text(errors="replace").strip()
    else:
        branch = git(where, "symbolic-ref", "-q", "HEAD")[1]
    branch = branch.removeprefix("refs/heads/")
    fmt = "--format=%(refname:lstrip=3)"
    return branch not in git(where, "for-each-ref", fmt, "refs/remotes")[1].splitlines()


def repo_edit(path: pathlib.Path, route: RouteArgs) -> tuple[pathlib.Path, bool] | None:
    """Return the written file and whether it is in a linked worktree, else None.

    A file of the route's repository or of a worktree of it, outside the planning dir,
    not ignored, with no unpushed rebase or merge in progress there.
    """
    if path.is_relative_to(pathlib.Path(route.planning_dir)):
        return None
    where = ("rev-parse", "--path-format=absolute", "--git-common-dir", "--git-dir")
    rc, out = git(path.parent, *where)
    _, own = git(route.repo or route.planning_dir, *where)
    if rc or not own or out.splitlines()[0] != own.splitlines()[0]:
        return None
    gitdir = pathlib.Path(out.splitlines()[-1])
    if _resolving(path.parent, gitdir):
        return None
    if git(path.parent, "check-ignore", "-q", str(path))[0] == 0:
        return None
    # another checkout than the route's own is a lane's worktree
    return path, str(gitdir) != own.splitlines()[-1]


def _path(word: shell_cmd.Word, here: str | None) -> pathlib.Path | None:
    """Return the file a word names from directory here; None when not known."""
    value = word.expand({"HOME": str(pathlib.Path.home())})
    if not value or shell_cmd.TEMP in value:
        return None
    if not (here or pathlib.Path(value).is_absolute()):
        return None
    return pathlib.Path(here or "", value)


def _dir_after(c: shell_cmd.Cmd, here: str | None) -> str | None:
    """Return the shell's directory after c: None after a computed `cd`, pushd, popd."""
    if c.name in ("pushd", "popd"):
        return None
    if c.name != "cd":
        return here
    to = next((w for w in c.words[1:] if w.text not in ("-L", "-P", "--")), None)
    if to is None:
        return str(pathlib.Path.home())
    if to.text == "-" or not (path := _path(to, here)):
        return None
    return os.path.normpath(path)


def _operands(
    words: Sequence[shell_cmd.Word], valued: str, attached: str = ""
) -> tuple[bool, bool, list[shell_cmd.Word]]:
    """Return (in place, a script given by option, operands) of sed's or perl's words.

    `-i` (any suffix after it in its cluster) or `--in-place` edits in place; a valued
    letter with nothing after it in its cluster takes the next word, `e`/`f`/`E` naming
    the script.
    """
    inplace = code = False
    operands: list[shell_cmd.Word] = []
    i = 0
    while i < len(words):
        t, i = words[i].text, i + 1
        if t == "--":
            operands += words[i:]
            break
        if t.startswith("--"):
            inplace |= t.startswith("--in-place")
            code |= t.startswith(("--expression", "--file"))
            i += t in ("--expression", "--file", "--line-length")
        elif t.startswith("-") and len(t) > 1:
            for j, ch in enumerate(t[1:], 2):
                if ch in "i" + valued + attached:
                    inplace |= ch == "i"
                    code |= ch in "efE"
                    i += ch in valued and j == len(t)
                    break
        else:
            operands.append(words[i - 1])
    return inplace, code, operands


def _in_place(c: shell_cmd.Cmd) -> list[shell_cmd.Word]:
    """Return the files a `sed -i` or `perl -i` command edits, else []."""
    if c.name == "sed":
        inplace, code, operands = _operands(c.words[1:], SED_VALUED)
    else:
        inplace, code, operands = _operands(c.words[1:], PERL_CODE, PERL_ATTACHED)
    if not inplace:
        return []
    return operands if code else operands[1:]


def _targets(text: str, strip: int | None) -> list[str]:
    """Return the files a unified diff writes, strip leading parts cut from each name.

    strip None is `patch` with no `-p`: a git diff's `a/`/`b/` cut, else the base name.
    """
    if strip is None and "\ndiff --git " not in f"\n{text}":
        return [pathlib.PurePosixPath(n).name for n in _targets(text, 0)]
    cut = 1 if strip is None else strip
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith(("--- ", "+++ ")):
            name = line[4:].split("\t")[0].strip().strip('"')
            parts = pathlib.PurePosixPath(name).parts[cut:]
            if name != "/dev/null" and parts:
                out.append(str(pathlib.PurePosixPath(*parts)))
    return list(dict.fromkeys(out))


def _read_patch(path: pathlib.Path | None) -> str:
    """Return a patch file's text, "" when it cannot be read."""
    try:
        if path and path.is_file() and path.stat().st_size <= PATCH_MAX:
            return path.read_text(errors="replace")
    except OSError:
        pass
    return ""


def _apply_args(
    args: Sequence[shell_cmd.Word], here: str
) -> tuple[int, str, list[pathlib.Path]]:
    """Return a `git apply`'s strip count, `--directory` and patch files."""
    strip, root, patches = 1, "", list[pathlib.Path]()
    for i, w in enumerate(args):
        t = w.text
        if t.startswith("-p") and t[2:].isdigit():
            strip = int(t[2:])
        elif t == "-p" and i + 1 < len(args) and args[i + 1].text.isdigit():
            strip = int(args[i + 1].text)
        elif t.startswith("--directory="):
            root = t.partition("=")[2]
        elif not t.startswith("-") and (p := _path(w, here)):
            patches.append(p)
    return strip, root, patches


def _git_apply(
    c: shell_cmd.Cmd, here: str | None, stdin: list[pathlib.Path]
) -> list[pathlib.Path]:
    """Return the files a `git apply` writes, from its patch files or stdin."""
    parsed = shell_cmd.git_args(c)
    if not parsed or parsed[1] != "apply":
        return []
    opts, _, args = parsed
    for name, value in opts:
        if name == "-C" and value:
            here = str(p) if (p := _path(value, here)) else None
    texts = {w.text for w in args}
    if not here or (APPLY_READS & texts and "--apply" not in texts):
        return []
    strip, root, patches = _apply_args(args, here)
    rc, top = git(here, "rev-parse", "--show-toplevel")
    if rc:
        return []
    text = "".join(_read_patch(p) for p in patches or stdin)
    return [pathlib.Path(top, root, n) for n in _targets(text, strip)]


def _patch_args(
    words: Sequence[shell_cmd.Word],
) -> tuple[dict[str, str], list[shell_cmd.Word]] | None:
    """Return a `patch`'s valued options by short name and its operands; None dry."""
    opts: dict[str, str] = {}
    operands: list[shell_cmd.Word] = []
    i = 0
    while i < len(words):
        t, i = words[i].text, i + 1
        if t == "--dry-run":
            return None
        if t in PATCH_VALUED and i < len(words):
            opts[t], i = words[i].text, i + 1
        elif t.startswith("--") and "=" in t:
            name, _, value = t.partition("=")
            opts[PATCH_LONG.get(name, name)] = value
        elif t[:2] in PATCH_VALUED and t[2:]:
            opts[t[:2]] = t[2:]
        elif not t.startswith("-"):
            operands.append(words[i - 1])
    return opts, operands


def _patch(
    c: shell_cmd.Cmd, here: str | None, stdin: list[pathlib.Path]
) -> list[pathlib.Path]:
    """Return the files a `patch` writes: its output or named file, else its targets."""
    if not here or not (parsed := _patch_args(c.words[1:])):
        return []
    opts, operands = parsed
    base = str(pathlib.Path(here, opts.get("-d", "")))
    named = [shell_cmd.literal(opts["-o"])] if "-o" in opts else operands[:1]
    if named:
        return [p for w in named if (p := _path(w, base))]
    source = opts.get("-i") or (operands[1].text if len(operands) > 1 else None)
    patches = [_path(shell_cmd.literal(source), here)] if source else stdin
    strip = int(opts["-p"]) if opts.get("-p", "").isdigit() else None
    text = "".join(_read_patch(p) for p in patches)
    return [pathlib.Path(base, n) for n in _targets(text, strip)]


def _writes(
    c: shell_cmd.Cmd, here: str | None, stdin: list[pathlib.Path]
) -> list[pathlib.Path]:
    """Return the files one simple command writes, from directory here."""
    if c.name == "patch":
        return _patch(c, here, stdin)
    if c.name == "git":
        return _git_apply(c, here, stdin)
    if c.name == "tee":
        words = [w for w in c.words[1:] if not w.text.startswith("-")]
    elif c.name in ("sed", "perl"):
        words = _in_place(c)
    else:
        return []
    return [p for w in words if (p := _path(w, here))]


def _stdin(command: str, cwd: str) -> list[pathlib.Path]:
    """Return the files the command's top-level `<` redirections read."""
    tokens = shell_cmd.scan(command)[0]
    return [
        pathlib.Path(cwd, t.text)
        for op, t in itertools.pairwise(tokens)
        if op == "<" and isinstance(t, shell_cmd.Word) and t.static
    ]


def bash_writes(command: str, cwd: str) -> list[pathlib.Path]:
    """Return the files a Bash command writes, resolved against cwd.

    Output redirections, `tee`, `sed -i`, `perl -i`, `patch` and `git apply`. A file
    named by a computed word, or a relative redirection after a `cd`, is left out; a
    command the reader cannot read writes nothing: a hold on it would be a guess.
    """
    try:
        found = shell_cmd.events(command)
        redirects = shell_cmd.redirects(command)
        stdin = _stdin(command, cwd)
    except Exception:  # noqa: BLE001 — the reader failing on the text holds nothing
        return []
    out: list[pathlib.Path] = []
    dirs: list[str | None] = [cwd]
    moved = False
    for kind, c in found:
        if kind == "open":
            dirs.append(dirs[-1])
        elif kind == "close":
            dirs = dirs[:-1] or dirs
        elif isinstance(c, shell_cmd.Cmd):
            moved |= c.name in DIR_CHANGES
            dirs[-1] = _dir_after(c, dirs[-1])
            out += _writes(c, dirs[-1], stdin)
    out += [p for t, _ in redirects if (p := _path(t, None if moved else cwd))]
    return [p.resolve() for p in dict.fromkeys(out)]


def _written(event: Mapping[str, object]) -> list[pathlib.Path]:
    """Return the files a tool call writes: an edit tool's file or a Bash command's."""
    inp = as_dict(event.get("tool_input")) or {}
    cwd = str(event.get("cwd") or ".")
    if event.get("tool_name") == "Bash":
        return bash_writes(str(inp.get("command") or ""), cwd)
    raw = str(inp.get("file_path") or inp.get("notebook_path") or "")
    return [(pathlib.Path(cwd) / raw).resolve()] if raw else []


def _counted(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> Tally | None:
    """Return the lead's tool call's repository files and the run's tally, else None."""
    marker = load_json(pathlib.Path(entry["marker"]))
    route = route_args(marker)
    files = [hit for p in _written(event) if (hit := repo_edit(p, route))]
    if not files:
        return None
    run = str(marker.get("run") or "")
    tally = REGISTRY / f"{session}.edits"
    t = load_json(tally)
    listed = t.get("files") if t.get("run") == run else None
    seen = (
        [str(f) for f in cast("list[object]", listed)]
        if isinstance(listed, list)
        else []
    )
    return Tally(files, run, seen, tally)


def edit_hold(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> str | None:
    """Return the deny of the lead's write past FREE repository files, else None.

    In the main checkout as in a lane's worktree (U2); a file already counted passes.
    """
    if not (t := _counted(event, session, entry)):
        return None
    new = [(p, wt) for p, wt in t.files if str(p) not in t.seen]
    if not new or len(t.seen) + len(new) <= FREE:
        return None
    path, worktree = new[-1]
    where = (
        "a lane's worktree, which its group owns" if worktree else "the main checkout"
    )
    return (
        f"{path.name} in {where} would be repository file {len(t.seen) + len(new)} "
        f"you write yourself in this route. The lead writes at most {FREE} files of "
        "the repository itself, in the main checkout as in a lane's worktree: "
        "execution is a fresh group's, never yours — dispatch an `exec-` group with "
        "its own checkpoint for a fix, a post-merge bug, a real-data run or an "
        "investigation (execution.md). A rebase, merge or cherry-pick in progress "
        "passes until its branch is pushed. Why: after its last lane returned, one "
        "lead made 126 edits itself and spent 30.4M of its 45.4M there (F68)."
    )


def record_edit(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> None:
    """Add the repository files of a lead's write that ran to the run's tally."""
    if not (t := _counted(event, session, entry)):
        return
    files = list(dict.fromkeys([*t.seen, *(str(p) for p, _ in t.files)]))
    if files != t.seen:
        _ = t.path.write_text(json.dumps({"run": t.run, "files": files}))
