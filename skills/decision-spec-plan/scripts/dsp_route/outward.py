# SPDX-License-Identifier: MIT
"""Outward actions on the hosted repository or a registry, and review comments.

The lead asks the user before each outward action, and a route agent never runs one
(F81). A review comment or note posted to GitHub or GitLab is held while the review's
decision document fails its check (F104).

Shapes held past the inert forms (F81):
- a `uv run` tool given by path (`./x/pytest`) may be any program: only a bare name;
- `coverage run` runs any script, so coverage is off the uv list;
- a computed `eval` or shell `-c` body (`eval $Z`, `sudo bash -c "$C"`) may run any;
- in text the reader cannot follow, every computed word may be a publisher's verb.
"""

import functools
import pathlib
import re
from collections.abc import Mapping, Sequence

import shell_cmd

from .commands import HOSTS, PUBLISHERS, Body, bash_commands, text_commands
from .common import as_dict

# Outward actions on the hosted repository: the lead asks the user each time and a route
# agent never runs one (F81). Each noun and verb may have any options between them, as
# gh accepts. A false match only asks.
GH_ACTIONS = {
    "pr": {"close", "merge"},
    "issue": {"close", "delete"},
    "release": {"create", "delete", "edit", "upload"},
    "repo": {"delete", "archive", "rename"},
}
# How much of an action and of its command a hold quotes.
EXCERPT = 120
# The commands that post a review comment or note: each tool's noun and verbs, and the
# REST paths a POST to which posts one (F104).
REVIEW_VERBS = {
    "gh": ("pr", {"review", "comment"}),
    "glab": ("mr", {"note", "comment"}),
}
REVIEW_PATHS = {
    "gh": re.compile(r"\b(?:issues|pulls)/[^/\s]+/(?:comments|reviews)\b"),
    "glab": re.compile(r"/(?:notes|discussions)\b"),
}
# the GraphQL mutations that post a pull request comment or review
REVIEW_MUTATION = re.compile(
    r"\b(?:addComment|addPullRequestReview\w*|submitPullRequestReview)\b"
)
# The subset that posts a review itself, held even where no index records one (F104).
REVIEW_SHAPES = {"gh": ("pr", {"review"})}
REVIEW_SHAPE_PATHS = {"gh": re.compile(r"\bpulls/[^/\s]+/reviews\b")}
REVIEW_SHAPE_MUTATION = re.compile(
    r"\b(?:addPullRequestReview\w*|submitPullRequestReview)\b"
)


# The subcommands after which a computed word is an argument (`cargo test $1`). After
# any other it may be the verb: a subcommand may run another (`npm run $X`), open a
# publish with a later word (`yarn npm $V`, `docker build --push`), or take every
# positional word as a task (`gradle build $T`, `mvn clean $GOAL`); a false match
# only asks. A container's `exec` or `run` stays off: its later words are a command
# (R8).
INERT = {
    "cargo": {
        "test",
        "build",
        "check",
        "clippy",
        "fmt",
        "doc",
        "bench",
        "nextest",
        "tree",
        "metadata",
    },
    **{tool: {"test"} for tool in ("npm", "pnpm", "yarn", "bun")},
    **{tool: {"inspect", "ps", "logs", "images"} for tool in ("docker", "podman")},
}
# The only tools after which a `uv run`'s computed word is an argument: each runs no
# command it is given. Any other may (a shell, an interpreter, `doas`, `uv` itself), and
# a list of those failed open for each one it missed; `python -m pytest` stays a verb.
# A path to one may be any program, and `coverage run` runs any script.
UV_TOOLS = {
    "pytest",
    "ruff",
    "mypy",
    "basedpyright",
    "pyright",
    "black",
    "isort",
    "deptry",
    "vulture",
    "lint-imports",
}


def _pair(tool: str, sub: str, second: shell_cmd.Word) -> bool:
    """Return whether `tool sub second` is a two-word inert form.

    An npm or pnpm package script (`npm run test:unit`) not named for git, a host
    tool or a publisher, the tool's own name too (`npm run npm $V`: bash_commands
    reads no second word of the same name as a command of its own), a UV_TOOLS tool
    under uv by its bare name, or a compose read (`docker compose ps`). `yarn run` and
    `bun run` run any installed bin, so neither has one. An option before the script
    or tool may take the next word as its value, so it leaves the form off.
    """
    t = second.text
    if not second.static or t.startswith("-"):
        return False
    name = t.rpartition("/")[2]
    if sub == "run" and tool in ("npm", "pnpm"):
        return name not in ("git", *HOSTS, *PUBLISHERS)
    if sub == "run" and tool == "uv":
        return t in UV_TOOLS
    return tool == "docker" and sub == "compose" and t in ("ps", "logs")


def _argued(tool: str, words: Sequence[shell_cmd.Word]) -> int | None:
    """Return the index of a PUBLISHERS command's first argument word, or None.

    Its words (after its name) from 1 on are arguments when the first is a static
    INERT subcommand of the tool, from 2 on when the first two are a two-word inert
    form (_pair). A word before it that may be an option's value or a toolchain
    (`pnpm --filter x $V`, `cargo +nightly $X`) leaves every computed word a verb.
    """
    first = words[0] if words else None
    if not (first and first.static):
        return None
    if first.text in INERT.get(tool, ()):
        return 1
    return 2 if len(words) > 1 and _pair(tool, first.text, words[1]) else None


def publish_word(
    tool: str, w: shell_cmd.Word, *, argument: bool = False, loose: bool = False
) -> bool:
    """Return whether word w of a PUBLISHERS command may publish.

    It may be its verb, a push flag or output (`--push=true`, `-o type=registry`), a
    gradle task that abbreviates `publish…` (`pTML`), or a computed word that may be the
    verb (`npm $V`). A computed word with a path or an `=` outside its expansions is a
    value (`-v $PWD:/app`, `-e K=$V`), and so is an argument, one after the command's
    inert subcommand (_argued: `cargo test $1`); a false match only asks. Loose (read
    from text the reader cannot follow), a computed word with a path or `=` may be the
    verb too.
    """
    t = w.text
    if t in PUBLISHERS[tool] or t.startswith("--push"):
        return True
    if re.search(r"(?i)\b(?:type=registry|push=(?:1|t|true))\b", t):
        return True
    # gradle runs a task by any camel or kebab abbreviation (`pTML`, `PTML`, `p-t-m-l`):
    # a task word that opens with p may be one
    if tool in ("gradle", "gradlew") and re.match(r"(?i)p", t.rpartition(":")[2]):
        return True
    bare = re.sub(r"\$\{[^}]*\}|\$\([^)]*\)|`[^`]*`", "", t)
    return not (w.static or argument or (not loose and re.search(r"[/=]", bare)))


def _api_call(rest: Sequence[str]) -> tuple[str | None, list[str]]:
    """Return an `api` command's method option, None without one, and its fields."""
    after = [*rest[rest.index("api") + 1 :], ""]
    method: str | None = None
    fields: list[str] = []
    for i, w in enumerate(after[:-1]):
        if m := re.fullmatch(r"(?:-X|--method)=?(.*)", w):
            method = (m[1] or after[i + 1]).upper()
        elif re.match(r"-[fF]|--(?:field|raw-field|input)\b", w):
            fields.append(w + " " + after[i + 1])
    return method, fields


def _gh_api(rest: Sequence[str], verb: Sequence[str]) -> bool:
    """Return whether `gh api` writes.

    A method other than GET writes, else a field (which makes it a POST), but a graphql
    query only when it is a mutation or read from a file.
    """
    method, fields = _api_call(rest)
    if method:
        return method in ("POST", "PATCH", "PUT", "DELETE")
    if verb[1:2] == ["graphql"]:
        # a computed query (`query="$Q"`) may be a mutation too
        return any(re.search(r"\bmutation\b|=@|^--input|[$`]", f) for f in fields)
    return bool(fields)


def _positional(rest: Sequence[str]) -> list[str]:
    """Return the words that are no option or `-R`'s value: the noun and verb first.

    (`gh -R o/r pr merge`, `gh pr -R o/r close`); a later word is a value (`--label
    delete`).
    """
    verb: list[str] = []
    skip = False
    for w in rest:
        if not (skip or w.startswith("-")):
            verb.append(w)
        skip = w in ("-R", "--repo")
    return verb


def _gh_outward(cmd: shell_cmd.Cmd) -> bool:
    """Return whether cmd, a `gh` command, acts on the hosted repository."""
    rest = cmd.argv[1:]
    if "--delete-branch" in rest:
        return True
    verb = _positional(rest)
    if cmd.loose:
        # words read from text the reader could not follow: a noun with its verb
        # anywhere after
        last = {w: i for i, w in enumerate(rest)}
        if any(
            w in GH_ACTIONS and any(last.get(v, -1) > i for v in GH_ACTIONS[w])
            for i, w in enumerate(rest)
        ):
            return True
    elif verb[:1] != ["api"]:
        return len(verb) > 1 and verb[1] in GH_ACTIONS.get(verb[0], ())
    return "api" in rest and _gh_api(rest, verb)


def outward_cmd(cmd: shell_cmd.Cmd) -> bool:
    """Return whether cmd, from a `gh`, `git` or publisher's word on, acts outward.

    A computed body (Body) may be any command. Loose, a publisher's words have no inert
    subcommand: every computed word may be the verb.
    """
    if isinstance(cmd, Body):
        return True
    if cmd.name in PUBLISHERS:
        rest = cmd.words[1:]
        start = None if cmd.loose else _argued(cmd.name, rest)
        return any(
            publish_word(
                cmd.name,
                w,
                argument=start is not None and i >= start,
                loose=cmd.loose,
            )
            for i, w in enumerate(rest)
        )
    if cmd.name == "gh":
        return _gh_outward(cmd)
    # remote refs deleted by `git push`: --delete, -d (alone or grouped), --prune,
    # --mirror, or a refspec with no source (`:<ref>`, `+:<ref>`)
    g = shell_cmd.git_args(cmd)
    return (
        bool(g)
        and g[1] == "push"
        and any(
            w in ("--delete", "--prune", "--mirror")
            or re.fullmatch(r"-[a-zA-Z]*d[a-zA-Z]*|\+?:.+", w)
            for w in (a.text for a in g[2])
        )
    )


def _api_posts(
    tool: str, rest: Sequence[str], verb: Sequence[str], *, shaped: bool
) -> bool:
    """Return whether a `gh api` or `glab api` call POSTs a review comment or note.

    A field makes the call a POST unless a method says otherwise; a graphql query
    posts one when it names a review mutation. Shaped, only a review itself counts.
    """
    method, fields = _api_call(rest)
    if (method or ("POST" if fields else "GET")) != "POST":
        return False
    mutation, path = (
        (REVIEW_SHAPE_MUTATION, REVIEW_SHAPE_PATHS[tool])
        if shaped
        else (REVIEW_MUTATION, REVIEW_PATHS[tool])
    )
    if tool == "gh" and verb[1:2] == ["graphql"]:
        return any(mutation.search(f) for f in fields)
    after = rest[rest.index("api") + 1 :]
    # a field's `key=value` is no path
    paths = [w for w in after if not re.match(r"[\w\[\]]+=", w)]
    return any(path.search(w) for w in paths)


def review_post_cmd(cmd: shell_cmd.Cmd, *, shaped: bool = False) -> bool:
    """Return whether cmd, from a `gh` or `glab` word on, posts a review comment.

    Shaped, whether it posts a review itself: `gh pr review`, a POST to a pull
    request's reviews, a review mutation.
    """
    table = REVIEW_SHAPES if shaped else REVIEW_VERBS
    if cmd.name not in table:
        return False
    noun, verbs = table[cmd.name]
    rest = cmd.argv[1:]
    verb = _positional(rest)
    if cmd.loose:
        # words in no known order: the noun with a verb anywhere after
        last = {w: i for i, w in enumerate(rest)}
        if noun in last and any(last.get(v, -1) > rest.index(noun) for v in verbs):
            return True
    elif verb[:1] != ["api"]:
        return len(verb) > 1 and verb[0] == noun and verb[1] in verbs
    return "api" in rest and _api_posts(cmd.name, rest, verb, shaped=shaped)


@functools.cache
def _commands(command: str, cwd: str | None) -> list[shell_cmd.Cmd]:
    """Return the commands a Bash command runs, read once for every check."""
    cmds = bash_commands(command, cwd)
    return text_commands(command) if cmds is None else cmds


def outward_in(command: str, cwd: str | None = None) -> str | None:
    """Return the first outward action the command runs, as its words, or None."""
    return next(
        (" ".join(c.argv) for c in _commands(command, cwd) if outward_cmd(c)), None
    )


def _bash(event: Mapping[str, object]) -> tuple[str, str | None]:
    """Return a Bash call's command and its directory."""
    command = str((as_dict(event.get("tool_input")) or {}).get("command") or "")
    cwd = event.get("cwd")
    return command, cwd if isinstance(cwd, str) else None


def _active(entry: Mapping[str, object]) -> bool:
    """Return whether the registry entry's route marker still exists."""
    marker = entry.get("marker")
    return bool(marker and pathlib.Path(str(marker)).exists())


def outward(event: Mapping[str, object], entry: Mapping[str, object]) -> str | None:
    """Return the outward action an active route's Bash command takes, if any."""
    if event.get("tool_name") != "Bash" or not _active(entry):
        return None
    command, cwd = _bash(event)
    if not (found := outward_in(command, cwd)):
        return None
    # the action matched, then the command it is in: an excerpt alone once showed no gh
    # at all
    whole = " ".join(command.split())[:EXCERPT]
    excerpt = found[:EXCERPT]
    return excerpt if found == whole else f"{excerpt}` in `{whole}"


def review_post(
    event: Mapping[str, object], entry: Mapping[str, object]
) -> tuple[str, bool] | None:
    """Return the review comment an active route's tool call posts, if any (F104).

    A Bash command's `gh` or `glab` post, or an MCP tool whose name ends in
    `create_note`, with whether it posts a review itself (REVIEW_SHAPES), which the
    excerpt then quotes.
    """
    name = str(event.get("tool_name") or "")
    if not _active(entry):
        return None
    if name.startswith("mcp__") and name.endswith("create_note"):
        return name, False
    if name != "Bash":
        return None
    cmds = _commands(*_bash(event))
    for shaped in (True, False):
        if found := next(
            (" ".join(c.argv) for c in cmds if review_post_cmd(c, shaped=shaped)), None
        ):
            return found[:EXCERPT], shaped
    return None
