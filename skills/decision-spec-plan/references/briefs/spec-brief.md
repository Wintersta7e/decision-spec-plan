# The spec brief — full text

Copy to `<planning-dir>/SPEC-BRIEF-p<P>.md`. Keep every unmarked rule (SKILL.md, 'Adapt, don't
trim'); fill every `‹ADAPT›`.

---

```markdown
# ‹ADAPT: Project› — phase-‹P› spec-writing brief

Every spec author gets this file, identical. You each write **one file**. The decisions are made; the
partition is now by **file**, one author per document, because when agents *apply* settled rulings
the risk flips from disagreement to two people writing one document.

## Your job

Write one normative specification section into `‹spec-dir›`. You are not writing a plan, not writing
code, and not re-deciding anything. **The decision round is closed and arbitrated.** Your file's
number, name and owning rulings are in your dispatch and in the scope section's In table. Section
numbers are the addressing scheme and are **stable across files** — every cross-reference is a
`§N.N`, never a filename.

## The one rule that matters most

**The spec says WHAT. The decision file says WHY.** The decision files carry the evidence, the
rejected alternatives and the file:line on both sides; the seam file carries the conflicts; the
arbiter carries how each was settled. **Do not restate them.** A spec section that re-argues its
ruling is twice the length and creates a second copy of every value in it — the dominant defect
class. Cite the decision once at the head of your section, then state rules.

Where a ruling's *reason* is load-bearing — a guard a future reader would otherwise "simplify" away,
or a rule that reads as arbitrary without its evidence (a measured number, a file:line) — keep one
sentence of it. Cut the story, never the reason.

## The precedence, and it is not optional

**The user's rulings (U) > the arbiter's rulings (A) > a decision file.** ‹ADAPT: one line per
U-ruling.› Each superseded paragraph in a decision file carries a `SUPERSEDED BY` marker. **If you
find yourself implementing a marked paragraph, stop and read the ruling** — it is there because
implementing the original would have produced something unbuildable, inert, unsafe, or against the
user. **Read the arbiter in full before your own decision file, not after.** Its list of defaults
the user may overturn are rulings until overturned.

## Read before writing

1. **The scope section** (‹ADAPT: §S›) — the boundaries, in/out, Lane 0, what is superseded, the
   confirmed defects with owners, the contract rules. **It binds you.** Defect rows assigned to your
   section ride it and need rules and criteria.
2. The decision index — the SETTLED table.
3. **The arbiter — in full.**
4. The seam file — for every item your rulings cite.
5. **Your own decision file(s)**, in full, reading every supersede marker.
6. ‹ADAPT: the spec README — conventions, the one-value-one-owner table, the invariants›
7. ‹ADAPT: the earlier scope sections whose boundaries this phase inherits›
8. The earlier sections you amend or cross-reference.
9. **The actual code for anything you assert about it.** Seam reviews have found rulings describing
   code that does not exist in the shape they claimed.

**Precedence of sources**: ‹ADAPT: ladder›. **The code beats a document that describes it wrongly.**

## Before you state any value, grep for it

    rg -n -F '<the value>' ‹spec-dir›

**One value, one owner.** A reconciliation round once found **105** values stated in two places and
drifting. If a value exists in the spec, **cross-reference the section that owns it**. Where two
sections of this phase touch one value, **the arbiter named the owner — the other cross-references
it.**

## Check the contract before naming any type

‹ADAPT, WHOLE PARAGRAPH: contract location and counts with SHA — or, if the project has no generated
contract, one line saying so and naming what plays that role.› A type the contract declares must not
also be hand-written in a second place. State your additions as a **delta with its shape** — name, fields, which are
nullable, and each command's flags (non-idempotent, privileged…). **Grep first; do not invent a name
that exists. State deltas, never totals.** ‹ADAPT: any single-read or prefix rules the scope
section set.›

## Migrations: state the contents, never the number

‹ADAPT: the placeholder for an unassigned number (e.g. `00NN`); the head migration; which table this
phase rebuilds once and who owns that rebuild; the rebuild procedure's traps — or, if the project has
no migrations, one line saying so and naming what plays that role.› State what your change depends
on that another section creates.

## The invariants — this phase is where some stop being vacuous

‹ADAPT: the scope section's invariant table, one line each.›

## Do not edit any earlier phase's file

They are shipped contracts whose bar passes. Where your section supersedes earlier text, **record it
in a table at the end of your section** — the anchor quoted verbatim, what supersedes it, and that
it is applied as a `[p‹P›]` marker when the implementing code lands. *The bar and the body move
together; a sentence still true of the shipped build must not be edited ahead of the build.*

**Do not edit the spec README or the scope section** — return your row and it is indexed once, by one
hand.

## Copy is the user's

Every visible string whose wording a ruling left to the user is written as **`‹COPY: <the constraint
the text must satisfy>›`** — never a final string.

## The bar and the body move together

**Do not edit earlier phases' acceptance files.** End your section with the acceptance criteria it
requires, stated as prose requirements, numbered **`AC-P‹P›-<your section>-<n>`**. The register
section folds them; you do not edit it. **Each criterion's own line opens with its full id in bold**
(`**AC-P‹P›-<section>-7 — …**`, or a table row whose first cell is the id), numbered from 1 with no
gap, letter suffix or range: `criteria_check.py` derives the register from those lines, and a list
numbered without ids once hid 17 of 253 criteria from a count. Elsewhere you may cite compactly
(`AC-P4-45-9, -11`; `AC-P4-38-1 … -24`). Mandatory shapes:

- **A gate whose passing run scans zero files is a failing gate.** Every scanning check prints its
  count and fails at zero.
- **A test must exercise the shape the product actually has.** A bar written past its defect proves
  the wrong thing — an audit of a command's arguments passed while the user's configuration made the
  same command delete a branch.
- **A count maintained by a human drifts.** Where a checker can derive a count, it derives and prints
  it.
- **A producer with no production caller is not a feature.** Every producer your section introduces
  names its production caller, and one criterion drives it **through the production path**.
- **A criterion guarding a defect names the test that fails against the unfixed tree.**

‹ADAPT: domain-specific verification rules, e.g. "motion is verified on a real mounted element under
each tier, never by matching stylesheet text"; "every git invocation is audited for effect, not
argv".›

## Style

Normative and dense. `##`/`###` headings carrying `§N.N`. Tables over prose for anything
enumerable. State the rule, not the deliberation. No "we should", no "the implementer may wish to" —
say what is true of a correct build. Where a rule has a measured number, give it and its source. **A
number without the tree it was measured on is not a measurement.**

## Public-repo hygiene

‹ADAPT›

## Report a disagreement rather than silently complying

If your decision file or the arbiter contradicts the scope section, the earlier spec, the contract,
or the code — **say so in your reply with file:line on both sides**, and write the reading that keeps
the system correct. Spec authors have corrected the arbiter six times in one round. **Precedence:
U-rulings > A-rulings > decision files; the scope section beats a decision file; the code beats a
document that describes it wrongly.** A disagreement with a **U-ruling** is reported, never acted on.

## Output

Your one file. Then a **short** reply: 1. your README index row (file, sections, one-line contents,
line count); 2. your **contract delta** and migration contents; 3. what you **superseded**, by
anchor, beyond the scope section's list; 4. your criteria ids and count; 5. any **disagreement**,
file:line both sides; 6. what you refused to specify and who owns it. Under 3 KB. **Write the file
first.**
```
