"""apply_markers.py: line endings, a BOM and code fences survive a supersede marker; a malformed
marker list is refused by name, with exit 2 and nothing written, never a traceback."""

import hashlib
import unittest

import support
from support import grep


def crlf(path):
    """'<LF count> <CRLF count>' of a file's bytes."""
    b = path.read_bytes()
    lf, crlf_ = b.count(b"\n"), b.count(b"\r\n")
    return f"{lf} {crlf_}"


class MarkersCrlfMalformed(support.Sandbox):
    """A CRLF file keeps its line endings; a malformed list is refused by name."""

    no_hooks = False

    def test_crlf_and_malformed(self):
        M = self.T / "markers"
        d = M / "d"
        self.write_bytes(
            d / "D2-x.md", b"# D2\r\n\r\nThe cache is per user.\r\nOther line.\r\n"
        )
        self.write(
            M / "ok.json",
            '[{"file":"D2-x.md","anchor":"per user","ruling":"A1","clause":"one global cache"}]\n',
        )
        r = self.py("apply_markers.py", d, M / "ok.json", merge=True)
        self.ok(
            "apply_markers: a CRLF file keeps CRLF",
            r.code == 0
            and crlf(d / "D2-x.md") == "6 6"
            and support.grep_file(d / "D2-x.md", "SUPERSEDED BY A1"),
            f"exit {r.code}, lf crlf: {crlf(d / 'D2-x.md')}: {r.out}",
        )
        before = hashlib.md5((d / "D2-x.md").read_bytes()).hexdigest()
        self.write(
            M / "noclause.json",
            '[{"file":"D2-x.md","anchor":"Other line","ruling":"A2"}]\n',
        )
        self.write(M / "object.json", '{"file":"D2-x.md"}\n')
        for j in ("noclause", "object"):
            r = self.py("apply_markers.py", d, M / f"{j}.json", merge=True)
            self.ok(
                f"apply_markers: a malformed list ({j}) is refused",
                r.code == 2
                and not grep(r.out, "Traceback")
                and grep(r.out, f"cannot read {M}/{j}.json")
                and hashlib.md5((d / "D2-x.md").read_bytes()).hexdigest() == before,
                f"exit {r.code}: {r.out}",
            )


class MarkersRerunFenceEndings(support.Sandbox):
    """A clause that repeats its anchor re-runs as present; an anchor in a code block is marked
    above the fence; mixed line endings stay mixed; a BOM stays first."""

    no_hooks = False

    def test_rerun_fence_mixed_bom(self):
        M = self.T / "markers"
        d = M / "d"
        self.write(
            d / "D3-r.md", "# D3\n\nThe client retries three times on a timeout.\n"
        )
        self.write(
            M / "r.json",
            '[{"file":"D3-r.md","anchor":"retries three times","ruling":"A7",'
            '"clause":"it retries three times only when idempotent"}]\n',
        )
        self.py("apply_markers.py", d, M / "r.json")
        r = self.py("apply_markers.py", d, M / "r.json", merge=True)
        text = (d / "D3-r.md").read_text()
        self.ok(
            "apply_markers: a clause repeating its anchor re-runs as present",
            r.code == 0
            and grep(text.removesuffix("\n"), "SUPERSEDED BY A7", count=True) == 1,
            f"exit {r.code}: {r.out}",
        )
        self.write(
            d / "D4-s.md",
            "# D4\n\n```sql\nCREATE TABLE a (id INTEGER);\n\nCREATE TABLE item (\n"
            "  qty INTEGER CHECK (qty <= 3)\n);\n```\n",
        )
        self.write(
            M / "s.json",
            '[{"file":"D4-s.md","anchor":"CHECK (qty <= 3)","ruling":"A4",'
            '"clause":"qty is capped at 5"}]\n',
        )
        r = self.py("apply_markers.py", d, M / "s.json", merge=True)
        lines = (d / "D4-s.md").read_text().split("\n")
        after = [
            lines[k]
            for i, line in enumerate(lines)
            if "SUPERSEDED BY A4" in line
            for k in (i, i + 1)
            if k < len(lines)
        ]
        self.ok(
            "apply_markers: an anchor in a code block is marked above the fence",
            r.code == 0 and "```sql" in after,
            f"exit {r.code}: {r.out} {(d / 'D4-s.md').read_text()}",
        )
        self.write_bytes(
            d / "D5-m.md", b"# D5\n\nAlpha paragraph.\r\n\nBeta anchor here.\n"
        )
        self.write(
            M / "m.json",
            '[{"file":"D5-m.md","anchor":"Beta anchor","ruling":"A1","clause":"gone"}]\n',
        )
        r = self.py("apply_markers.py", d, M / "m.json", merge=True)
        self.ok(
            "apply_markers: mixed line endings stay mixed",
            r.code == 0 and crlf(d / "D5-m.md") == "7 1",
            f"exit {r.code}, lf crlf: {crlf(d / 'D5-m.md')}: {r.out}",
        )
        self.write_bytes(d / "D6-b.md", b"\xef\xbb\xbf# D6\n\nGamma anchor here.\n")
        self.write(
            M / "b.json",
            '[{"file":"D6-b.md","anchor":"Gamma anchor","ruling":"A2","clause":"gone"}]\n',
        )
        r = self.py("apply_markers.py", d, M / "b.json", merge=True)
        data = (d / "D6-b.md").read_bytes()
        second = data.split(b"\n")[1] if data.count(b"\n") >= 1 else b""
        self.ok(
            "apply_markers: a BOM stays first, the header under the title",
            r.code == 0
            and data[:7].hex() == "efbbbf23204436"
            and second == b"> **Read 00-arbiter.md first.**",
            f"exit {r.code}: {r.out} {data[:80]!r}",
        )


if __name__ == "__main__":
    unittest.main()
