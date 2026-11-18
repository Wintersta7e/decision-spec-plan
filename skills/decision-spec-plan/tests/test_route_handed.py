# SPDX-License-Identifier: MIT
"""Commands the lead hands the user, read at its Stop (F107).

A block that ends every WSL session among other lines, a program's prompt followed by
the lines meant for it, and a `cd` or `git -C` to a missing directory send the turn
back once.
"""

import json
import unittest

import support
from support import ev

# the shape that ended every session: a remount, then the distro stop, then diskpart
CRASH = """Run this in PowerShell:

```powershell
wsl -d dev -u root -- sh -c "umount -l /mnt/c"
wsl --terminate dev
diskpart
  select vdisk file="C:\\disk.vhdx"
  compact vdisk
```
"""


class Handed(support.Route):
    """The lead of s1's route ends its turn with commands for the user."""

    def stop(self, message: str, *, again: bool = False) -> str:
        """The hook's output on the lead's Stop after message."""
        extra = f'"last_assistant_message":{json.dumps(message)}'
        if again:
            extra += ',"stop_hook_active":true'
        return self.hook_out(ev("Stop", "s1", extra)).out

    def test_handed_commands(self) -> None:
        """Each failing shape sends the turn back once; sound blocks pass."""
        out = self.stop(CRASH)
        self.ok(
            "the session-ending block and diskpart's prompt send the turn back",
            '"decision": "block"' in out
            and "F107" in out
            and "wsl --terminate" in out
            and "`diskpart` opens its own prompt" in out,
            out,
        )
        self.ok("only once", self.stop(CRASH, again=True) == "")
        alone = "First the steps above, then on its own:\n\n```\nwsl --shutdown\n```\n"
        self.ok("a stop alone in its block passes", self.stop(alone) == "")
        here = str(self.R)
        cmds = f"```bash\ncd {here} && git status\ngit -C ~/ log -1\n```\n"
        self.ok("directories that exist pass", self.stop(cmds) == "")
        gone = f"```bash\ncd {here}/product-maven\n```\nand `cd /nowhere` in prose\n"
        out = self.stop(gone)
        self.ok(
            "a missing directory in a block is named; prose is not read",
            "product-maven`: no such directory" in out and "/nowhere" not in out,
            out,
        )
        self.ok(
            "a comment and a script file are no prompt",
            self.stop("```\n# diskpart\ndiskpart /s compact.txt\nexit\n```") == "",
        )
        self.ok("no message, no hold", self.stop("") == "")


if __name__ == "__main__":
    _ = unittest.main()
