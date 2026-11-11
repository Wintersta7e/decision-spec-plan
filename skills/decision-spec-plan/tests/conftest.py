# SPDX-License-Identifier: MIT
"""Put the scripts and the test helpers on sys.path for every test module.

Here rather than in pyproject.toml: an installed copy of the skill has its tests but no
pyproject.toml, and its suite must still find the modules it tests.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (str(HERE), str(HERE.parent / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)
