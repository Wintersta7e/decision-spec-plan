# SPDX-License-Identifier: MIT
"""The route report's text, pinned byte for byte over seven route shapes.

The CLI's report, its `--all` form and the hook's injected `.last` of each shape match a
golden file, cold (no merged-result cache) and warm (the cache the cold run wrote), so a
change to how the report is built cannot change what it prints or what a session reads.
"""

import difflib
from pathlib import Path

import report_shapes
import support
from report_shapes import GOLDEN, GOLDEN_DIR, mask
from support import RS

OUTPUTS = ("cli", "all", "hook")
# seven shapes' three outputs, and the missing planning dir's
GOLDEN_FILES = 22
NO_DIR_EXIT = 2


class GoldenText(report_shapes.Shapes):
    """Each shape's three outputs, cold then warm, equal their golden files."""

    def compare(self, name: str, got: str, run: str, seen: set[str]) -> None:
        """One output's masked text equals tests/golden/report-<name>.txt."""
        path = GOLDEN_DIR / f"report-{name}.txt"
        rel = path.relative_to(support.PLUGIN)
        seen.add(path.name)
        want = path.read_text(encoding="utf-8") if path.exists() else None
        text = mask(got) + "\n"
        if want is None:
            detail = f"missing golden file {rel}\n{text}"
        else:
            diff = difflib.unified_diff(
                want.splitlines(), text.splitlines(), str(rel), "actual", lineterm=""
            )
            detail = "\n".join(diff)
        self.ok(f"golden {rel} ({run})", want == text, detail)

    def output(self, key: str, what: str) -> str:
        """Return one output of a shape: the CLI's text, or the hook's `.last`."""
        shape = GOLDEN[key]
        if key == "7-odd":
            self.freshen()
        if what == "hook":
            self.unthrottle()
            _ = self.hook_out(
                support.ev("PostToolUse", shape["session"], '"tool_name":"Read"')
            )
            last = report_shapes.last_file(shape)
            return last.read_text(encoding="utf-8") if last.exists() else ""
        extra = ["--all"] if what == "all" else []
        return self.py(RS, *shape["argv"], *extra).out

    def test_golden_text(self) -> None:
        """Every output of every shape, cold then warm, and the missing planning dir."""
        seen: set[str] = set()
        comparisons = 0
        for key, shape in GOLDEN.items():
            for what in OUTPUTS:
                name = f"{key}-{what}"
                report_shapes.merged_file(shape).unlink(missing_ok=True)
                self.compare(name, self.output(key, what), "cold", seen)
                if key == "2-merged" and what == "cli":
                    self.ok(
                        "the cold CLI run of shape 2 wrote the cache",
                        report_shapes.merged_file(shape).exists(),
                    )
                self.compare(name, self.output(key, what), "warm", seen)
                comparisons += 2
        for run in ("cold", "warm"):
            r = self.py(RS, "missing-plan", "--phase", "1", cwd=self.T)
            self.ok(
                f"a missing planning dir exits {NO_DIR_EXIT} ({run})",
                r.code == NO_DIR_EXIT,
                r.out,
            )
            self.compare("missing-cli", r.out, run, seen)
            comparisons += 1
        files = len(seen)
        self.ok(
            f"golden files: {files}, comparisons: {comparisons}",
            files == len(GOLDEN) * len(OUTPUTS) + 1 == GOLDEN_FILES
            and comparisons == 2 * files,
            sorted(seen),
        )
        stale = sorted(
            p.name for p in Path(GOLDEN_DIR).glob("report-*.txt") if p.name not in seen
        )
        self.ok("no golden file is left unread", not stale, stale)
