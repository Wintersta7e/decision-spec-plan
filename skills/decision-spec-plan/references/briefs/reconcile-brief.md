# The reconciliation brief — full text

Copy to `<planning-dir>/RECONCILE-BRIEF-p<P>.md`. Keep every unmarked rule (SKILL.md, 'Adapt, don't
trim'); fill every `‹ADAPT›`. Dispatch one agent per kept dimension, all in one message — or the one
agent with the dimension `all` where SKILL.md Stage 3 says so. **Keep every row of §3** unless the
phase's spec declares or changes nothing on that row's axis: grep the phase's spec files for the
axis's nouns in the project's own words, print how many files it read and how many hits, read every
hit, and put the pattern and both counts in the dropped row's one line. `values`, `edges` and `bar`
are never dropped — every multi-author spec has all three. Add a row, in the same shape, for an axis
on which a previous round or the returns log shows facts falling that no row reads.

---

```markdown
# ‹ADAPT: Project› — the phase-‹P› spec reconciliation brief

**Every reconciliation agent gets this file, identical.** Your dimension is the only thing that
differs, and it arrives in your dispatch.

## 1. What exists, and what you are doing

The phase-‹P› specification was written by **‹N› authors, one file each, who could not see each
other**. That partition is correct for *writing* and is exactly the partition that once produced
**105 cross-section contradictions**. **You are the pass that finds them before a plan author does.**
You write no spec text and change no file outside your own findings file. **The plan round is
blocked on your output**: a finding you do not report is one a plan author meets at implementation
time, where it costs a lane instead of a paragraph.

## 2. Read in this order

1. ‹ADAPT: the spec README — the index and the precedence ladder›
2. **The scope section** — it binds every reader. Its confirmed-defects list is known and is **not**
   a finding.
3. The arbiter — its rulings win over any decision file.
4. The decision index — the SETTLED table.
5. **The returns log** (`decisions/phase‹P›/spec-returns.md`) — every author's delta and
   disagreement. One already reported is known: report it only if you found something it misses. A
   conflict between two authors' reported readings that neither names **is** a finding.
6. **Every phase-‹P› section file, all of them**, along your dimension.

The `criteria_check.py` output is known, not a finding.

## 3. Your dimension

‹ADAPT: the dispatch names one row, or `all` — then read along every row and name each finding's
row in its `**Dimension**` line (§7). Fill each kept row with the project's own nouns; a dropped row
keeps its line and says why, with the scan and its counts.

| Dimension | Reads every section for |
|---|---|
| **wire** | Every type, command, event and field: declared once, placed on a surface, produced by someone, consumed by someone; names and shapes agree across sections |
| **store** | Every persisted thing — table, column, index, trigger, migration, file format, stored setting: one owner, dependencies in order, one rebuild per table, CHECKs matching the enums they mirror |
| **values** | Every number, threshold, name, spelling, default and rule stated in more than one place |
| **edges** | Producers and consumers, and ordering: X consumed and never produced; declared and never placed, stored or read; X must land before Y and Y before X |
| **bar** | Every acceptance criterion and gate: can it fail? does it scan something and print a count? does it exercise the real shape? does a test file own it? |
›

## 4. The standard every finding meets

**Cite file:line on BOTH sides.** A finding that names one side is a suspicion. **Verify every
code-level claim against the tree** — if a section says a column exists, a function returns a shape,
a test asserts a value, open it. **Compare shapes, not strings** — grepping a declaration matches
prose about it. Before "declared nowhere", **name the languages and directories you searched**.
**A list that is self-consistent is not thereby right** — every list once agreed with every other list
and none agreed with the product. **Never rewrite the spec.** Not a word, not a marker. You report;
one hand applies.

## 5. What is a finding and what is noise

**A finding**: two sections state one value, threshold, name, count, spelling or rule differently ·
A says B owns a thing and B does not own it, or declines it in its own words · something consumed
and never produced · something declared and never placed, stored or read · a section contradicting
the scope section, the arbiter or SETTLED · a false claim about the tree · an ordering that cannot
hold · a rule whose test, as specified, would pass against the defect it names.

**Noise, do not report**: wording you would have chosen differently · a value stated once in its
owner and referenced elsewhere by pointer (**that is the correct shape**) · anything in the scope
section's known-defects list · scope you would have ruled differently · what goes wrong once a
design the sections agree on is built (the seven-sins spec review beside you owns that). **A ruling
you disagree with is not a finding; a ruling that contradicts another ruling is.**

## 6. The shape of a finding — a worked example

**A wire type with no placement.** Section A says its items reach the UI *"through the field section
B declares"*. Section B says *"item values are not ours"* and its wire table declares four types and
no such field. **A's three types are declared and land on no surface.** Both sides cited; neither
author was wrong about their own half. That is the shape: two authors, each correct about their own
file, and the fact falls between them.

## 7. Your output

**Write one file: `‹planning-dir›/reconcile/p‹P›-<your-dimension>.md`.** Numbered, **ordered worst
first**:

    ### F<n> — <one line: the disagreement, not the topic>
    **Dimension**: wire | store | values | edges | bar
    **Severity**: blocker | defect | drift
    **Sides**: `<file>:<line>` says X · `<file>:<line>` says Y
    **Verified**: what you opened in the tree, and what it actually holds
    **Why it matters**: the failure a plan author hits, in one or two sentences
    **Not ruling it**: the options you can see, and which you would take

*blocker* — a plan cannot be written without a ruling. *defect* — a plan can be written but will be
wrong. *drift* — two copies of one value that will separate later.

**You do not rule.** You recommend. One hand arbitrates all dimensions together, because a ruling
made inside one dimension is the defect this pass exists to find.

**Return a manifest, not the findings.** At most 20 lines: the path, the count by severity, the three
worst in one line each, and anything you could not verify. An agent that emits ~30 large items in one
output has twice returned nothing.

## 8. Push back

If this brief is wrong about your dimension, or if you believe the spec is right and the brief's
example is wrong — say so. **Overlap with another row is expected and is no reason to stay silent**:
file every fact your row names even if another row may file it too — independent convergence is
evidence a finding is real (in two rounds, 12% and 23% of findings were a second row's copy of one
fact), and one hand rules each fact once. A fact only another row names goes in one line under
*Seen outside my dimension*.
**If you find nothing, say so plainly and say what you searched.** A clean dimension is a result; a
clean dimension reported without naming what was read is not.

## 9. House rules

‹ADAPT: hygiene; grep the spec as a directory; dedicated tools (symbol search, structural search,
text search); do not run the gate or build — you are reading.›
```
