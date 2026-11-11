# SPDX-License-Identifier: MIT
"""The lead's files, the skill under a running lead, and a route that ended.

The lead's files grow past one read (F76), the skill changes under a running lead (F78),
and a route that ended (its marker gone) waits for --activate.
"""

import shutil
import unittest

from typing_extensions import override

import support
from support import SCRIPTS, ev


class LeadFiles(support.Route):
    """The route of support.Route, its planning dir at Stage 5."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the lane checkpoint that puts the planning dir at Stage 5."""
        super().setUpClass()
        # the lane checkpoint section 846 wrote: the planning dir reads as Stage 5
        _ = cls.write(
            cls.P / "lanes/p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {cls.MAIN}\n"
        )

    def test_lead_files(self) -> None:
        """Oversized lead files, a changed skill file and an ended route."""
        p, t, r = self.P, self.T, self.R
        read = ev("PostToolUse", "s1", '"tool_name":"Read"')
        compact = ev("SessionStart", "s1", '"source":"compact"')
        _ = self.write(p / "HANDOFF.md", "x" * 41000)
        _ = self.write(
            p / "lanes/p1-04-checkpoint.md", "".join(f"{i}\n" for i in range(1, 41))
        )
        self.unthrottle()
        _ = self.hook(
            r"/HANDOFF.md over 40 KB[\s\S]*checkpoint over 35 lines "
            r"+lanes\/p1-04-checkpoint.md \(40/",
            read,
        )
        self.rm(p / "HANDOFF.md", p / "lanes/p1-04-checkpoint.md")
        _ = self.hook(
            r"/Re-read .*HANDOFF.md and, for Stage 5 \(going by the planning dir\) "
            r"references\/execution.md,/",
            compact,
        )
        # a project whose handoff is SESSION-HANDOFF.md: the size check and the re-read
        # name it
        _ = self.write(p / "SESSION-HANDOFF.md", "x" * 41000)
        self.unthrottle()
        _ = self.hook("/SESSION-HANDOFF.md over 40 KB/", read)
        _ = self.hook(r"/Re-read \S*\/SESSION-HANDOFF.md and,/", compact)
        self.rm(p / "SESSION-HANDOFF.md")
        # `cp -rp` of the plugin: modes and mtimes kept
        _ = shutil.copytree(SCRIPTS.parent, t / "skill", symlinks=True)
        rs = t / "skill/scripts/route_state.py"
        _ = self.write(t / "skill/references/execution.md", "a changed rule\n", "a")
        self.unthrottle()
        _ = self.hook(
            r"/changed since this session read it: references\/execution.md \(in /",
            read,
            rs=rs,
        )
        self.unthrottle()
        _ = self.hook("silent", read, rs=rs)  # told once
        # an upgrade rewrites every file (`git archive | tar -x`): a new mtime on the
        # same text is no change to re-read
        self.touch(t / "skill/SKILL.md")
        self.touch(t / "skill/references/execution.md")
        self.unthrottle()
        _ = self.hook("silent", read, rs=rs)
        # the route ended (its marker deleted): a registered session's next route agent
        # waits for --activate
        mk = self.MK(r)
        _ = mk.replace(t / "marker.bak")
        _ = self.hook(
            "deny:no active decision-spec-plan route",
            ev(
                "PreToolUse",
                "s1",
                '"tool_name":"Agent",'
                '"tool_input":{"subagent_type":"dsp-deep","name":"pride-r1"}',
            ),
        )
        _ = self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                '"tool_name":"Bash","tool_input":{"command":"gh pr close 5"}',
            ),
        )
        _ = (t / "marker.bak").replace(mk)


if __name__ == "__main__":
    _ = unittest.main()
