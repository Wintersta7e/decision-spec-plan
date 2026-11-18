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

The machine is the user's: the command runs at `nice -n 19` (and `ionice -c3` where it
exists), with Cargo, CMake and pytest-xdist's `auto` held to half the cores unless the
environment sets them, and in one of DSP_GATE_SLOTS gate slots shared by every route on
this machine (default: a core in eight). It waits for a free slot for up to
DSP_GATE_WAIT_MIN minutes (default 30), then runs anyway: a hung gate never holds the
others (failure-modes F100).

Why a runner: leads and agents hand-wrote that log, piped the gate through `tail` (the
log then lost its `exit=` line) and edited a red log green (failure-modes F97, F31). The
runner writes every line itself, before the command runs and after it ends, so a log
either holds the whole run or says it is still running.
"""

import argparse
import contextlib
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Generator
from typing import IO

try:
    import fcntl
except ImportError:  # not POSIX: no slots
    fcntl = None

SLOTS = pathlib.Path.home() / ".claude/dsp-routes/gate-slots"
POLL_S = 5
# the build tools' own parallelism settings, each held to half the cores when unset
JOBS = (
    "CARGO_BUILD_JOBS",
    "CMAKE_BUILD_PARALLEL_LEVEL",
    "PYTEST_XDIST_AUTO_NUM_WORKERS",
)


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


def _env_int(name: str, default: int, least: int = 1) -> int:
    """Return the environment's integer `name` if at least `least`, else default."""
    raw = os.environ.get(name, "")
    return int(raw) if raw.isdigit() and int(raw) >= least else default


@contextlib.contextmanager
def slot() -> Generator[int | None]:
    """Hold one of the machine's gate slots while the gate runs; its index, or None.

    None when there are no slots here or the wait ran out.
    """
    if fcntl is None:
        yield None
        return
    n = _env_int("DSP_GATE_SLOTS", max(1, (os.cpu_count() or 1) // 8))
    deadline = time.monotonic() + 60 * _env_int("DSP_GATE_WAIT_MIN", 30, least=0)
    SLOTS.mkdir(parents=True, exist_ok=True)
    told = False
    while True:
        for i in range(n):
            f = (SLOTS / f"{i}.lock").open("a")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                continue
            try:
                yield i
            finally:
                f.close()  # closing the file releases the lock
            return
        if time.monotonic() >= deadline:
            print("gate.py: no gate slot came free; running anyway", file=sys.stderr)
            yield None
            return
        if not told:
            print(
                f"gate.py: all {n} gate slots on this machine are busy; waiting",
                file=sys.stderr,
            )
            told = True
        time.sleep(POLL_S)


def low_priority(run: list[str]) -> tuple[list[str], dict[str, str]]:
    """Return the command at low priority and its environment with half the cores."""
    half = str(max(1, (os.cpu_count() or 2) // 2))
    env = {**dict.fromkeys(JOBS, half), **os.environ}
    nice = [shutil.which("nice") or "nice", "-n", "19"]
    io = [ionice, "-c3"] if (ionice := shutil.which("ionice")) else []
    return [*io, *nice, *run], env


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
    run, env = low_priority(
        [shutil.which("bash") or "bash", "-c", command[0]]
        if len(command) == 1
        else command
    )
    shown = command[0] if len(command) == 1 else shlex.join(command)
    with log.open("w", newline="\n") as out:
        wt = f" wt={a.wt}" if a.wt else ""
        _ = out.write(f"sha={sha} dirty={dirty}{wt}\n")
        if a.harness:
            _ = out.write(f"harness={a.harness}\n")
        _ = out.write(f"cmd={shown}\n")
        out.flush()
        with (
            slot(),
            subprocess.Popen(
                run, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            ) as proc,
        ):
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
