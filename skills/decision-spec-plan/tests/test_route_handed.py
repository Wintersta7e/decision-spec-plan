# SPDX-License-Identifier: MIT
"""Commands the lead hands the user, read at its Stop (F107).

A block that ends every WSL session among other lines, a program's prompt followed by
the lines meant for it, a `cd` or `git -C` to a missing directory, a relative one from
off the repository root, a Windows program in a WSL shell's block and a push to a
remote whose push URL is disabled send the turn back once; an inline `! cmd` span is a
block of one line.
"""

import json
import unittest

from typing_extensions import override

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

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Give R a subdirectory and remotes: two push URLs disabled, one not."""
        super().setUpClass()
        (cls.R / "src").mkdir()
        for name, push in (("origin", "no-push"), ("off", "DISABLED"), ("up", "")):
            url = f"https://example.invalid/{name}.git"
            _ = cls.git("-C", cls.R, "remote", "add", name, url)
            if push:
                _ = cls.git("-C", cls.R, "remote", "set-url", "--push", name, push)

    def stop(self, message: str, *, again: bool = False, cwd: str = "") -> str:
        """The hook's output on the lead's Stop after message, from cwd if given."""
        extra = f'"last_assistant_message":{json.dumps(message)}'
        if again:
            extra += ',"stop_hook_active":true'
        if cwd:
            # read after ev's own cwd: the last of a repeated key is the one json keeps
            extra += f',"cwd":{json.dumps(cwd)}'
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

    def test_inline_spans(self) -> None:
        """An inline `! cmd` span is read as a block of its one line."""
        out = self.stop("Then run `! cd /no/such && ls` here, and `cd /nowhere` too.")
        self.ok(
            "a missing directory in a `!` span is named; a plain span is prose",
            "`cd /no/such`: no such directory" in out and "/nowhere" not in out,
            out,
        )
        self.ok(
            "a span whose directory exists passes",
            self.stop(f"Run `! cd {self.R} && git status`.") == "",
        )

    def test_relative_directories(self) -> None:
        """A relative `cd` or `git -C` is flagged while the cwd is off the root."""
        root, sub = str(self.R), str(self.R / "src")
        block = "```bash\ncd src && make\ngit -C docs log -1\n```\n"
        out = self.stop(block, cwd=sub)
        self.ok(
            "each relative path is named with the cwd it was written from",
            "`cd src`: a relative path" in out
            and "`git -C docs`: a relative path" in out
            and sub in out,
            out,
        )
        self.ok("from the root it passes", self.stop(block, cwd=root) == "")
        self.ok(
            "an absolute, home or computed path is no relative one",
            self.stop(f"```bash\ncd {root}\ncd ~\ncd $D\ncd -\n```\n", cwd=sub) == "",
        )

    def test_windows_program_in_wsl(self) -> None:
        """A drive-letter program in a block a WSL shell runs is flagged."""
        wsl = "```bash\n! ls /srv/data\nC:\\Tools\\app.exe --scan\n```\n"
        out = self.stop(wsl)
        self.ok(
            "the Windows program is named",
            "`C:\\\\Tools\\\\app.exe`" in out and "WSL" in out,
            out,
        )
        posix = '```\ncat /etc/hostname\n"D:\\Apps\\run.exe" x\n```\n'
        self.ok("a POSIX path marks the block too", "run.exe" in self.stop(posix))
        self.ok(
            "a `!` span is a WSL line itself", "app.exe" in self.stop("`! C:\\app.exe`")
        )
        ps = "```powershell\nC:\\Tools\\app.exe --scan\ncd C:\\Work\n```\n"
        self.ok("a PowerShell block of its own passes", self.stop(ps) == "")

    def test_disabled_push_remotes(self) -> None:
        """A push to a remote whose push URL is `no-push` or `DISABLE…` is flagged."""
        root = str(self.R)
        for block, remote in (
            ("git push origin main", "origin"),
            ("git push -u --force off main", "off"),
            ("git push", "origin"),
        ):
            out = self.stop(f"```bash\n{block}\n```\n", cwd=root)
            self.ok(
                f"{block}: the remote is named",
                f"`{block}`: remote `{remote}`'s push URL is disabled" in out,
                out,
            )
        self.ok(
            "a remote that pushes passes",
            self.stop("```bash\ngit push up main\n```\n", cwd=root) == "",
        )
        self.ok(
            "an inline span is read too",
            "remote `origin`" in self.stop("`! git push origin main`", cwd=root),
        )


if __name__ == "__main__":
    _ = unittest.main()
