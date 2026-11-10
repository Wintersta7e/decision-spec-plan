"""decision_check.py: a SETTLED row that only describes today's code (F86), a requirement dimension
nobody owns, a review finding declined with no ruling or refuting test; and the hook that holds
the lead's exec- dispatch while the route's ledger fails, and a verifier whose prompt is not the
script-written file."""

import shutil
import unittest

import support
from support import decision_index as index
from support import dispositions as disp
from support import ev, grep, grep_file, jstr

CHECK = "decision_check.py"

SEAMS = (
    "# Seams\n## A. BLOCKERS\n**R1** — `src/a.ts:9` merges two people with one name; contradicts "
    "S1.\n**R2** — the cache is never cleared.\n## E. SAFETY\n- R3 — a crash loses the draft.\n"
)
WRATH = (
    "# Wrath — x\n## Findings\n"
    "| ID | Severity | Age | Where | Finding | Recommendation | Evidence |\n"
    "|---|---|---|---|---|---|---|\n"
    "| WRA-1 | high | new | `src/t.ts:9` | a crafted tag crashes the parser | bound the read | "
    "probes/wrath/tag.sh → crash |\n"
    "| WRA-2 | low | new | `a:1` | other | x | y |\n"
)


class DecisionCheck(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.DC = cls.T / "dc/decisions/phase1"
        (cls.DC / "verify").mkdir(parents=True)
        # what sections 835 and 846 left in phase 1: D files, and the phase unbound by the ledger
        cls.write(cls.P / "decisions/phase1/D1-a.md", "ruling\n")
        cls.write(cls.P / "decisions/phase1/D2-b.md", "ruling\n")
        cls.edit_marker(lambda m: m["ledger"].update({"1": False}))

    def dcheck(self, want, rx, *args):
        r = self.py(CHECK, self.DC, *args, merge=True)
        self.ok(
            f"decision_check {want} /{rx}/",
            r.code == want and grep(r.out, rx, E=True),
            f"got {r.code}: {r.out[:600]}",
        )

    def dispatch(self, name, prompt):
        return ev(
            "PreToolUse",
            "s1",
            f'"tool_name":"Agent","transcript_path":"{self.LEAD}",'
            f'"tool_input":{{"name":"{name}","prompt":{jstr(prompt)}}}',
        )

    def hook_held(self, event):
        """The hook's merged output on event."""
        return self.hook_out(event).out

    def ledger(self, fn):
        self.edit_marker(lambda m: fn(m["ledger"]))

    def test_decision_check(self):
        DC, P, T = self.DC, self.P, self.T
        idx = DC / "00-index.md"
        self.dcheck(2, "no index")
        self.write(
            idx, index("| S1 | **Names merge only on email** | U2, the user 10-20 |")
        )
        self.dcheck(0, "0 failure")
        self.write(
            idx, index("| S1 | **Rows keep 14 columns** | `src/import.ts:40-52` |")
        )
        self.dcheck(1, "S1 cites only code.*Today's code")
        self.write(
            idx,
            index("| S1 | **Rows keep 14 columns** | `docs/spec/02-import.md` §3 |"),
        )
        self.dcheck(0, "0 failure")
        self.write(idx, index("| **Names merge** | U2 |"))
        self.dcheck(1, "without an S<n> id")
        self.write(idx, index("| S1 | **x** | U2 |", "TBD"))
        self.dcheck(1, "dimension 'security' has no owner")
        self.write(idx, index("| S1 | **x** | U2 |", "N/A:"))
        self.dcheck(1, "dimension 'security' has no owner")
        self.write(idx, index("| S1 | **x** | U2 |", "N/A: offline-only"))
        self.dcheck(0, "0 failure")
        text = index("| S1 | **x** | U2 |")
        self.write(
            idx,
            "".join(ln for ln in text.splitlines(True) if "Background jobs" not in ln),
        )
        self.dcheck(1, "dimension 'background jobs' has no row")
        # a decision serves an ask or a user ruling, or waits in the backlog; past six, the user
        # triages first (F89)
        why = text.replace("| # | Decision | Serves |", "| # | Decision | Why |")
        self.write(idx, why)
        self.dcheck(1, "decisions table has no Serves column")
        self.write(idx, text.replace("| D1 | x | Ask1 |", "| D1 | x | tidier infra |"))
        self.dcheck(1, "D1 serves no ask")
        seven = "\n".join(f"| D{i} | x | Ask1 |" for i in range(2, 8))
        self.write(idx, index("| S1 | **x** | U2 |", "", seven))
        self.dcheck(1, "7 decisions to rule.*Triage")
        self.write(
            idx,
            index(
                "| S1 | **x** | U2 |",
                "",
                seven + "\n> **Triage**: U3 — the user kept all seven",
            ),
        )
        self.dcheck(0, "0 failure")
        lines = seven.split("\n")
        backlog = "\n".join(
            [ln.replace("Ask1", "backlog", 1) for ln in lines[:2]] + lines[2:]
        )
        self.write(idx, index("| S1 | **x** | U2 |", "", backlog))
        self.dcheck(0, "0 failure")
        # dispositions, once the review exists: at S in the index, at M and L in the arbiter
        self.write(DC / "00-seams.md", SEAMS)
        self.write(idx, index("| S1 | **x** | U2 |"))
        self.dcheck(1, "has no Dispositions table", "--rung", "S")
        self.write(
            idx,
            index(
                "| S1 | **x** | U2 |",
                "",
                disp("| R1 | declined | known limitation |\n| R2 | applied | D1 |"),
            ),
        )
        self.dcheck(1, "R3 has no disposition", "--rung", "S")
        self.dcheck(
            1, "R1 is declined on 'known limitation'.*--verifier R1", "--rung", "S"
        )
        self.write(
            idx,
            index(
                "| S1 | **x** | U2 |",
                "",
                disp(
                    "| R1 | re-opened | user asked |\n| R2 | applied | D1 |\n"
                    "| R3 | declined | U4 |"
                ),
            ),
        )
        self.dcheck(
            1, "R1 is re-opened against S1, which is still in SETTLED", "--rung", "S"
        )
        # a decline rests on a SETTLED row only if the row is there
        self.write(
            idx,
            index(
                "| S2 | **y** | U2 |",
                "",
                disp(
                    "| R1 | declined | S9 |\n| R2 | declined | the S3 bucket is out of scope |\n"
                    "| R3 | declined | S2 |"
                ),
            ),
        )
        self.dcheck(1, "R1 is declined on S9, which is not in SETTLED", "--rung", "S")
        self.dcheck(1, "R2 is declined on 'the S3 bucket", "--rung", "S")
        self.write(
            idx,
            index(
                "| S2 | **y** | U2 |",
                "",
                disp(
                    "| R1 | declined | default |\n| R2 | applied | D1 |\n| R3 | declined | S2 |"
                ),
            ),
        )
        self.dcheck(1, "R1 is declined on 'default'", "--rung", "S")
        out = self.py(CHECK, DC, "--verifier", "R1", "--sha", "abc123").out
        p = DC / "verify/R1.prompt.md"
        self.ok(
            "decision_check --verifier writes the claim and commit, nothing else",
            out == str(p)
            and grep_file(p, "merges two people with one name", F=True)
            and grep_file(p, "abc123", F=True)
            and not grep_file(p, "cache|known limitation|Ruling", E=True),
            out,
        )
        self.ok(
            "the verifier prompt asks for the claim quoted and a mutant run",
            grep_file(p, "Mutant run:", F=True) and grep_file(p, "Claim:", F=True),
            p.read_text() if p.exists() else "",
        )
        # a finding's repro block keeps its shell comments, and a wrapped `#42` is no heading
        DF = T / "dc-fence/decisions/phase1"
        self.write(
            DF / "00-seams.md",
            "# Seams\n**R1** — importing twice duplicates rows. Repro:\n```sh\n"
            "# import the same file twice\napp import a.csv && app import a.csv\n```\n"
            "After the second run every row is there twice, see\n#42 for the report.\n"
            "## B. OTHER\n**R2** — the cache is never cleared.\n",
        )
        self.py(CHECK, DF, "--verifier", "R1", "--sha", "abc123")
        fp = DF / "verify/R1.prompt.md"
        self.ok(
            "decision_check: a finding runs past a fenced # comment to the next heading",
            fp.exists()
            and grep_file(fp, "After the second run every row is there twice", F=True)
            and grep_file(fp, "#42 for the report", F=True)
            and not grep_file(fp, "OTHER", F=True),
            fp.read_text() if fp.exists() else "",
        )
        # a REFUTED from a test that cannot see the defect refutes nothing: it must fail on a
        # mutant that makes the claim true, and quote the claim it checks
        v = DC / "verify/R1.md"
        self.write(v, "Verdict: REFUTED\n")
        self.dcheck(
            1, "R1's REFUTED in verify/R1.md quotes no line of the claim", "--rung", "S"
        )
        self.write(
            v,
            'Verdict: REFUTED\nClaim: "merges two people with one name"\n'
            "Run: npm test -- a → exit=0\nMutant: key by name alone\n"
            "Mutant run: npm test -- a → exit=0\n",
        )
        self.dcheck(
            1,
            "R1's REFUTED in verify/R1.md shows no mutant run that fails",
            "--rung",
            "S",
        )
        self.write(
            v,
            'Verdict: REFUTED\nClaim: "merges two dogs"\nMutant run: npm test -- a → exit=1\n',
        )
        self.dcheck(
            1, "R1's REFUTED in verify/R1.md quotes no line of the claim", "--rung", "S"
        )
        self.write(
            v,
            'Verdict: REFUTED\nClaim: "merges two people with one   name"\n'
            "Run: npm test -- a → exit=0\nMutant: key by name alone\n"
            "Mutant run: npm test -- a → exit=1\n",
        )
        self.dcheck(0, "0 failure", "--rung", "S")
        self.write(v, "Verdict: UPHELD\n")
        self.dcheck(1, "R1 is declined, but verify/R1.md upheld it", "--rung", "S")
        # the verifier prompt glosses each verdict; one copied onto the line is still that verdict
        self.write(v, "Verdict: UPHELD (the test demonstrates the claim)\n")
        self.dcheck(1, "R1 is declined, but verify/R1.md upheld it", "--rung", "S")
        # a round with no arbiter (a review round run S-shaped under an M route) keeps them in
        # its index
        self.dcheck(1, "R1 is declined, but verify/R1.md upheld it", "--rung", "M")
        self.write(DC / "00-arbiter.md", "# Arbiter\n")
        self.dcheck(1, "00-arbiter.md has no Dispositions table", "--rung", "M")
        self.write(
            DC / "00-arbiter.md",
            disp("| R1 | applied | A3 |\n| R2 | applied | A1 |\n| R3 | applied | A2 |"),
        )
        self.dcheck(0, "0 failure", "--rung", "M")
        # a fix that holds a SETTLED row says so and the row stays: findings that upheld a row
        # were relabelled "declined" to pass (live)
        upholds = disp(
            "| R1 | applied (upholds S1) | D1 |\n| R2 | applied | D1 |\n| R3 | declined | U4 |"
        )
        self.write(idx, index("| S1 | **x** | U2 |", "", upholds))
        self.dcheck(0, "0 failure", "--rung", "S")
        self.write(
            idx,
            index(
                "| S1 | **x** | U2 |",
                "",
                disp(
                    "| R1 | applied (upholds S7) | D1 |\n| R2 | applied | D1 |\n"
                    "| R3 | declined | U4 |"
                ),
            ),
        )
        self.dcheck(1, "R1 upholds S7, which is not in SETTLED", "--rung", "S")
        self.write(
            idx,
            index(
                "| S1 | **x** | U2 |",
                "",
                disp(
                    "| R1 | declined (upholds S1) | D1 |\n| R2 | applied | D1 |\n"
                    "| R3 | declined | U4 |"
                ),
            ),
        )
        self.dcheck(
            1, r"R1: disposition 'declined \(upholds S1\)' is not", "--rung", "S"
        )

        # the hook holds the lead's exec- dispatch while the route's ledger fails, and a verifier
        # whose prompt is not the script-written file
        pidx = P / "decisions/phase1/00-index.md"
        code_row = "| S1 | **Rows keep 14 columns** | `src/import.ts:40` |"
        self.write(pidx, index(code_row))
        out = self.hook_held(self.dispatch("exec-p1-09-a", "go"))
        self.ok(
            "a phase begun before the ledger check is not held by it",
            not grep(out, "decision ledger"),
            out,
        )
        self.ledger(lambda led: led.update({"1": True}))
        self.hook(
            r"deny:decision ledger fails(.|\n)*S1 cites only code",
            self.dispatch("exec-p1-09-a", "go"),
        )
        self.write(pidx, index("| S1 | **x** | U2 |"))
        out = self.hook_held(self.dispatch("exec-p1-09-a", "go"))
        self.ok(
            "a passing ledger releases the exec- dispatch to the budget gate",
            not grep(out, "decision ledger"),
            out,
        )
        # a check added after a phase was bound never holds that phase: its index was written
        # without it
        self.write(
            pidx,
            index("| S1 | **x** | U2 |").replace(
                "| # | Decision | Serves |", "| # | Decision | Why |"
            ),
        )
        self.hook(
            r"deny:decision ledger fails(.|\n)*no Serves column",
            self.dispatch("exec-p1-09-a", "go"),
        )
        self.ledger(lambda led: led.pop("1#checks", None))
        out = self.hook_held(self.dispatch("exec-p1-09-a", "go"))
        self.ok(
            "a phase bound before the Serves check is not held by it",
            not grep(out, "decision ledger"),
            out,
        )
        self.ledger(lambda led: led.update({"1#checks": 2}))
        self.write(pidx, index("| S1 | **x** | U2 |"))
        # a review round in its own directory is checked by its own index (live: two rounds never
        # read)
        rnd = P / "decisions/phase1/wave2-review"
        rnd.mkdir(parents=True)
        self.write(rnd / "00-index.md", index(code_row))
        self.hook(
            r"deny:decision ledger fails.*wave2-review(.|\n)*S1 cites only code",
            self.dispatch("exec-p1-09-a", "go"),
        )
        shutil.copy(DC / "00-seams.md", rnd)
        self.write(rnd / "00-index.md", index("| S1 | **x** | U2 |", "", upholds))
        out = self.hook_held(self.dispatch("exec-p1-09-a", "go"))
        self.ok(
            "a review round with its dispositions in its index releases the dispatch",
            not grep(out, "decision ledger"),
            out,
        )
        # a phase begun before the ledger check still has its later rounds checked
        self.ledger(lambda led: led.update({"1": False}))
        self.write(rnd / "00-index.md", index(code_row))
        self.hook(
            "deny:decision ledger fails.*wave2-review",
            self.dispatch("exec-p1-09-a", "go"),
        )
        self.rm(rnd)
        self.ledger(lambda led: led.update({"1": True}))
        shutil.copy(DC / "00-seams.md", P / "decisions/phase1")
        self.py(CHECK, P / "decisions/phase1", "--verifier", "R2", "--sha", "abc123")
        self.hook(
            "deny:verifier's prompt is the file",
            self.dispatch(
                "verify-R2", "Check R2. The lead thinks it is a known limitation."
            ),
        )
        r2 = (P / "decisions/phase1/verify/R2.prompt.md").read_text().rstrip("\n")
        self.hook("silent", self.dispatch("verify-R2", r2))
        # a disputed seven-sins finding goes to the same verifier, its claim taken from the sin's
        # report
        rd = P / "reviews/p1-push1"
        self.write(rd / "wrath.md", WRATH)
        out = self.py(
            CHECK,
            rd,
            "--verifier",
            "WRA-1",
            "--sha",
            "abc123",
            "--from",
            rd / "wrath.md",
        ).out
        p = rd / "verify/WRA-1.prompt.md"
        self.ok(
            "decision_check --verifier --from takes a sin's finding, not its severity or fix",
            out == str(p)
            and grep_file(p, "a crafted tag crashes the parser", F=True)
            and grep_file(p, "probes/wrath/tag.sh", F=True)
            and not grep_file(p, "high|bound the read|other", E=True),
            out,
        )
        wra = p.read_text().rstrip("\n") if p.exists() else ""
        self.hook("silent", self.dispatch("verify-WRA-1", wra))
        self.hook(
            "deny:verifier's prompt is the file",
            self.dispatch("verify-WRA-1", wra + " Wrath is usually right."),
        )
        # ...and so does one from a sliced run's slice and from a review round's own folder
        r2dir = P / "decisions/phase1/r2"
        r2dir.mkdir(parents=True)
        self.write(
            rd / "s2/wrath.md",
            WRATH.replace("a crafted tag crashes the parser", "the loop is quadratic"),
        )
        self.py(
            CHECK,
            rd / "s2",
            "--verifier",
            "WRA-1",
            "--sha",
            "abc123",
            "--from",
            rd / "s2/wrath.md",
        )
        s2 = (rd / "s2/verify/WRA-1.prompt.md").read_text().rstrip("\n")
        self.hook("silent", self.dispatch("verify-WRA-1", s2))
        self.write(
            r2dir / "00-seams.md",
            "# Review round 2 findings\n\n- **R1** — the export drops the last row when the "
            "file ends without a newline.\n",
        )
        self.py(CHECK, r2dir, "--verifier", "R1", "--sha", "abc123")
        r1 = (r2dir / "verify/R1.prompt.md").read_text().rstrip("\n")
        self.hook("silent", self.dispatch("verify-R1", r1))
        self.rm(rd, r2dir)
        self.rm(pidx, P / "decisions/phase1/00-seams.md", P / "decisions/phase1/verify")

        # a finding opens with its id — in a numbered list or a heading too — and a wrapped line
        # that begins with another finding's id stays in its finding
        self.write(
            DC / "00-seams.md",
            "# Seams\n1. **R1** — the export drops the id column.\n"
            "2. **R2** — two people sharing a name merge on import,\n"
            "R1's keying makes this reachable from every import path.\n"
            "### **R3** — the cache is never cleared.\n",
        )
        self.rm(DC / "verify/R1.md")
        self.write(idx, index("| S1 | **x** | U2 |", "", disp("| R1 | applied | D1 |")))
        self.dcheck(1, "R2 has no disposition", "--rung", "S")
        self.dcheck(1, "R3 has no disposition", "--rung", "S")
        ok = (
            self.py(CHECK, DC, "--verifier", "R2", "--sha", "abc123").code == 0
            and grep_file(
                DC / "verify/R2.prompt.md", "reachable from every import path", F=True
            )
            and self.py(CHECK, DC, "--verifier", "R3", "--sha", "abc123").code == 0
            and grep_file(
                DC / "verify/R3.prompt.md", "the cache is never cleared", F=True
            )
        )
        self.ok(
            "decision_check --verifier: a wrapped finding whole, a heading finding", ok
        )
        # an escaped pipe stays inside its table cell
        self.write(
            T / "wrath.md",
            "| ID | Severity | Age | Where | Finding | Recommendation | Evidence |\n"
            "|---|---|---|---|---|---|---|\n"
            "| WRA-3 | high | new | `a:1` | reads unbounded | cap | `cat big.tag \\| ./reader` "
            "ran out of memory |\n",
        )
        w3 = DC / "verify/WRA-3.prompt.md"
        ok = self.py(
            CHECK,
            DC,
            "--verifier",
            "WRA-3",
            "--sha",
            "abc123",
            "--from",
            T / "wrath.md",
        ).code == 0 and grep_file(
            w3, "cat big.tag | ./reader` ran out of memory", F=True
        )
        self.ok(
            "decision_check --from: an escaped pipe stays in the evidence",
            ok,
            w3.read_text() if w3.exists() else "",
        )


if __name__ == "__main__":
    unittest.main()
