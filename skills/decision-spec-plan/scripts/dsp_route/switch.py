# SPDX-License-Identifier: MIT
"""The monitor switch: one environment variable turns event recording on.

README, INSTALL.md and `route_state.py --help` spell the variable as `NAME` does, and
hooks.json's guarded commands open with `GUARD`. Only `os` is imported, so a hook that
asks pays for nothing else.
"""

import os

NAME = "DSP_MONITOR"
# the shell predicate a guarded hooks.json command runs before any Python
GUARD = f'[ "${NAME}" = 1 ]'


def on(env: dict[str, str] | None = None) -> bool:
    """Return whether the monitor is on: exactly "1" in env (default os.environ)."""
    return (os.environ if env is None else env).get(NAME) == "1"
