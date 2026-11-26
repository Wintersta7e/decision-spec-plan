# SPDX-License-Identifier: MIT
"""`route_state.py --fingerprint <repo>`: one digest of a repository's git state.

The lead prints it before a hunt's first dispatch and after its last return: a
different digest means the repository changed while the hunters ran, a slip no hold
saw, and the route stops for the user (prompts.md §8, F109).
"""

import hashlib
import pathlib
import sys

from .common import git

USAGE = "usage: route_state.py --fingerprint <repo>"
# A for-each-ref line's tab and the remote-tracking namespace (a refname has no tab).
REMOTE = "\trefs/remotes/"
# the reflog subjects of a fetch, which moves a remote-tracking ref with no slip
FETCHED = (">fetch", ">pull")


def _files(root: pathlib.Path) -> list[tuple[str, bytes]]:
    """Return each file under root with its bytes, by path relative to root, sorted."""
    if not root.is_dir():
        return []
    files = sorted(p for p in root.rglob("*") if p.is_file())
    return [(p.relative_to(root).as_posix(), p.read_bytes()) for p in files]


def _remote_updates(repo: pathlib.Path, refs: str) -> str:
    """Return each remote-tracking ref in refs moved by other than a fetch,, counted.

    A push of an existing commit leaves its only local trace there (`update by push`);
    a `>` before each reflog subject keeps an empty one (a bare `update-ref`) a line.
    """
    counts: list[str] = []
    for line in sorted(r for r in refs.splitlines() if REMOTE in r):
        ref = line.split("\t", 1)[1]
        _, log = git(repo, "log", "-g", "--format=>%gs", ref, "--")
        if n := sum(not s.startswith(FETCHED) for s in log.splitlines()):
            counts.append(f"{ref} {n}")
    return "\n".join(counts)


def fingerprint(repo: pathlib.Path) -> str:
    """Return the sha256 over repo's git state that a hunter's slip would change.

    HEAD, every ref (`for-each-ref`) but the remote-tracking ones (a fetch moves
    them, no hunter's slip) and how often each of those moved by other than a fetch
    (a push leaves its trace there), the stash count, `status --porcelain=v1
    --ignored -z`, the repository's own config: the config file in the git common
    dir, `config --local` and `--worktree --includes --list --show-origin` with the
    bytes of every file they name (included ones too), and `config.worktree` even
    while git does not read it; each file's name and bytes under `info/`; and the
    hooks dir git runs (`--git-path hooks`, which honours `core.hooksPath`): its
    resolved path and each hook's name and bytes. Global and system config stay
    out: they lie outside the repository. Each part is hashed with its name and
    length, so no two states share a stream.
    """
    digest = hashlib.sha256()

    def part(name: str, data: bytes) -> None:
        digest.update(f"{name} {len(data)}\n".encode())
        digest.update(data)

    def file_part(name: str, path: pathlib.Path) -> None:
        part(name, path.read_bytes() if path.is_file() else b"")

    origins: set[str] = set()
    for name, args in (
        ("HEAD", ("rev-parse", "HEAD")),
        ("refs", ("for-each-ref",)),
        ("status", ("status", "--porcelain=v1", "--ignored", "-z")),
        (
            "local config",
            ("config", "--local", "--includes", "--list", "--show-origin", "-z"),
        ),
        (
            "worktree config",
            ("config", "--worktree", "--includes", "--list", "--show-origin", "-z"),
        ),
    ):
        code, out = git(repo, *args)
        if name == "refs":
            part("remote updates", _remote_updates(repo, out).encode())
            out = "\n".join(r for r in out.splitlines() if REMOTE not in r)
        part(name, f"{code}\n{out}".encode())
        if name.endswith("config") and code == 0:
            # -z: origin NUL key-and-value NUL, pair after pair
            origins |= {o for o in out.split("\0")[::2] if o.startswith("file:")}
    for origin in sorted(origins):
        file_part(f"config origin {origin}", repo / origin.removeprefix("file:"))
    _, stashes = git(repo, "stash", "list")
    part("stash count", str(len(stashes.splitlines())).encode())
    _, common = git(repo, "rev-parse", "--git-common-dir")
    file_part("config", repo / common / "config")
    _, worktree_config = git(repo, "rev-parse", "--git-path", "config.worktree")
    file_part("config.worktree", repo / worktree_config)
    _, info = git(repo, "rev-parse", "--git-path", "info")
    for rel, data in _files(repo / info):
        part(f"info {rel}", data)
    _, hooks = git(repo, "rev-parse", "--git-path", "hooks")
    part("hooks dir", str((repo / hooks).resolve()).encode())
    for rel, data in _files(repo / hooks):
        part(f"hook {rel}", data)
    return digest.hexdigest()


def fingerprint_cli(argv: list[str]) -> int:
    """Print the fingerprint of the repository argv names; 2 when it names none."""
    rest = [a for a in argv if a != "--fingerprint"]
    repo = pathlib.Path(rest[0]) if len(rest) == 1 else None
    if repo is None or git(repo, "rev-parse", "--git-dir")[0] != 0:
        print(USAGE + " (a git repository)", file=sys.stderr)
        return 2
    print(fingerprint(repo))
    return 0
