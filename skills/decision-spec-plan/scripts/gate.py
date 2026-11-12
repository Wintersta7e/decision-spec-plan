#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a gate and write its log: the evidence push_guard.py and route_state.py read.

    gate.py <planning-dir> <name> [--repo DIR] [--harness LABEL] [--wt LANE]
        -- <command> [args...]

Runs <command> in --repo (default: the current directory) and writes
<planning-dir>/lanes/<name>-gate.log (`<name>-<label>-gate.log` with --harness):

    sha=<HEAD> dirty=<tracked files changed>[ wt=<lane>]
    harness=<label>       (with --harness: a suite CI runs that the local gate does not)
    cmd=<command>
    <the command's output, stdout and stderr merged>
    exit=<status>

The output also streams to the terminal, and gate.py exits with the command's status.
One argument after `--` runs as `bash -c <argument>` (a compound gate:
`cargo test && npm test`); several run as they are.

Why a runner: leads and agents hand-wrote that log, piped the gate through `tail` (the
log then lost its `exit=` line) and edited a red log green (failure-modes F97, F31). The
runner writes every line itself, before the command runs and after it ends, so a log
either holds the whole run or says it is still running.
"""

import argparse
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
from typing import IO


class _Args(argparse.Namespace):
    """The arguments before `--`."""

    planning_dir: str = ""
    name: str = ""
    repo: str = "."
    harness: str | None = None
    wt: str | None = None


def git(repo: pathlib.Path, *args: str) -> str:
    """Run git in repo and return its stdout; raise when it fails."""
    return subprocess.run(
        [shutil.which("git") or "git", "-C", str(repo), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def main() -> int:
    """Run the gate command and write its log; the command's exit status."""
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit(__doc__)
    split = argv.index("--")
    ap = argparse.ArgumentParser(prog="gate.py", usage=__doc__)
    _ = ap.add_argument("planning_dir")
    _ = ap.add_argument("name")
    _ = ap.add_argument("--repo", default=".")
    _ = ap.add_argument("--harness")
    _ = ap.add_argument("--wt")
    a = ap.parse_args(argv[:split], namespace=_Args())
    command = argv[split + 1 :]
    if not command:
        sys.exit("gate.py: no command after --")
    repo = pathlib.Path(a.repo).resolve()
    sha = git(repo, "rev-parse", "HEAD").strip()
    dirty = len(git(repo, "status", "--porcelain", "--untracked-files=no").splitlines())
    lanes = pathlib.Path(a.planning_dir, "lanes")
    lanes.mkdir(parents=True, exist_ok=True)
    log = lanes / (
        f"{a.name}-{a.harness}-gate.log" if a.harness else f"{a.name}-gate.log"
    )
    run = (
        [shutil.which("bash") or "bash", "-c", command[0]]
        if len(command) == 1
        else command
    )
    shown = command[0] if len(command) == 1 else shlex.join(command)
    with log.open("w", newline="\n") as out:
        _ = out.write(
            f"sha={sha} dirty={dirty}" + (f" wt={a.wt}" if a.wt else "") + "\n"
        )
        if a.harness:
            _ = out.write(f"harness={a.harness}\n")
        _ = out.write(f"cmd={shown}\n")
        out.flush()
        with subprocess.Popen(
            run, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ) as proc:
            # stdout=PIPE: never None. typeshed says IO[Any]; with no text= it is bytes,
            # and iterating a binary stream yields a line per readline()
            stream: IO[bytes] | tuple[()] = proc.stdout or ()
            last = b"\n"
            for chunk in stream:
                _ = sys.stdout.buffer.write(chunk)
                _ = sys.stdout.buffer.flush()
                _ = out.write(chunk.decode(errors="replace"))
                last = chunk
        status = proc.returncode
        _ = out.write(("" if last.endswith(b"\n") else "\n") + f"exit={status}\n")
    print(
        f"gate.py: {log} — sha={sha[:12]} dirty={dirty} exit={status}", file=sys.stderr
    )
    if dirty:
        print(
            "gate.py: the tree had uncommitted tracked changes, so this log gates no "
            "commit (push_guard.py wants dirty=0): commit first, then rerun",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
