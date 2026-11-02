"""The lead's files grow past one read (F76), the skill changes under a running lead (F78), and a
route that ended (its marker gone) waits for --activate."""

import os
import shutil
import unittest

import support
from support import SCRIPTS, ev


class LeadFiles(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the lane checkpoint section 846 wrote: the planning dir reads as Stage 5
        cls.write(
            cls.P / "lanes/p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {cls.MAIN}\n"
        )

    def test_lead_files(self):
        P, T, R = self.P, self.T, self.R
        read = ev("PostToolUse", "s1", '"tool_name":"Read"')
        compact = ev("SessionStart", "s1", '"source":"compact"')
        self.write(P / "HANDOFF.md", "x" * 41000)
        self.write(
            P / "lanes/p1-04-checkpoint.md", "".join(f"{i}\n" for i in range(1, 41))
        )
        self.unthrottle()
        self.hook(
            r"/HANDOFF.md over 40 KB[\s\S]*checkpoint over 35 lines +lanes\/p1-04-checkpoint.md \(40/",
            read,
        )
        self.rm(P / "HANDOFF.md", P / "lanes/p1-04-checkpoint.md")
        self.hook(
            r"/Re-read .*HANDOFF.md and, for Stage 5 \(going by the planning dir\) "
            r"references\/execution.md,/",
            compact,
        )
        # a project whose handoff is SESSION-HANDOFF.md: the size check and the re-read name it
        self.write(P / "SESSION-HANDOFF.md", "x" * 41000)
        self.unthrottle()
        self.hook("/SESSION-HANDOFF.md over 40 KB/", read)
        self.hook(r"/Re-read \S*\/SESSION-HANDOFF.md and,/", compact)
        self.rm(P / "SESSION-HANDOFF.md")
        # `cp -rp` of the plugin: modes and mtimes kept
        shutil.copytree(SCRIPTS.parent, T / "skill", symlinks=True)
        rs = T / "skill/scripts/route_state.py"
        self.touch(T / "skill/references/execution.md")
        self.unthrottle()
        self.hook(
            r"/changed since this session read it: references\/execution.md \(in /",
            read,
            rs=rs,
        )
        self.unthrottle()
        self.hook("silent", read, rs=rs)  # told once
        # the route ended (its marker deleted): a registered session's next route agent waits for
        # --activate
        mk = self.MK(R)
        os.replace(mk, T / "marker.bak")
        self.hook(
            "deny:no active decision-spec-plan route",
            ev(
                "PreToolUse",
                "s1",
                '"tool_name":"Agent","tool_input":{"subagent_type":"dsp-deep","name":"pride-r1"}',
            ),
        )
        self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                '"tool_name":"Bash","tool_input":{"command":"gh pr close 5"}',
            ),
        )
        os.replace(T / "marker.bak", mk)


if __name__ == "__main__":
    unittest.main()
