# SPDX-License-Identifier: MIT
"""read_script and run_script answer None for a path the user cannot look into.

pathlib's `is_dir()` raises PermissionError where `os.path.isdir()` answers False, so a
command whose cwd sits under an unreadable directory must still read as "no script",
never as a crash of the guard that asked.
"""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

import pytest
from typing_extensions import override

import shell_cmd


class UnreadableCwd(unittest.TestCase):
    """A cwd under a directory without search permission reads as no script."""

    root: ClassVar[Path]
    locked: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        """Make a directory the test user cannot search."""
        cls.root = Path(tempfile.mkdtemp(prefix="dsp-test-"))
        cls.locked = cls.root / "locked"
        (cls.locked / "sub").mkdir(parents=True)
        script = cls.locked / "sub" / "ship.sh"
        _ = script.write_text("git push\n")
        script.chmod(0o755)
        cls.locked.chmod(0)

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        """Restore permissions so the directory can be removed."""
        cls.locked.chmod(stat.S_IRWXU)
        shutil.rmtree(cls.root)

    def test_cwd_under_unreadable_dir(self) -> None:
        """Both readers return None instead of raising."""
        if os.geteuid() == 0:
            self.skipTest("root searches any directory")
        cwd = self.locked / "sub"
        with pytest.raises(PermissionError):  # the precondition: pathlib raises here
            _ = cwd.is_dir()
        word = shell_cmd.words("./ship.sh")[0]
        assert shell_cmd.read_script(word, cwd) is None
        assert shell_cmd.run_script(word, cwd) is None

    def test_readable_cwd_still_reads(self) -> None:
        """The same script under a readable cwd is still read."""
        self.locked.chmod(stat.S_IRWXU)
        try:
            word = shell_cmd.words("./ship.sh")[0]
            assert shell_cmd.read_script(word, self.locked / "sub") == "git push\n"
        finally:
            self.locked.chmod(0)
