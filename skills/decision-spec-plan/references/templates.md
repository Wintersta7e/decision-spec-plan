# Templates

Placeholders: `<P>` phase number, `<planning-dir>` (e.g. `.dev`), `§<S>` the first spec section of
the phase, `R<r>` the first free ruling number. Adapt vocabulary (commands, migrations, schema) to
the project's stack; keep every rule.

---

The four briefs are full text in `briefs/` (decision, spec, reconcile, plan). This file holds the
four documents the **lead** writes: the decision index, the arbiter, the scope section, the plan index
— and, first, the layout and numbering they all use (§0).

---

## §0 — Layout and numbering (read before writing the first file or number)

```
<planning-dir>/                        # gitignored; may name real paths and projects
  DECISION-BRIEF-p<P>.md  SPEC-BRIEF-p<P>.md  RECONCILE-BRIEF-p<P>.md  PLAN-BRIEF-p<P>.md
  decisions/phase<P>/  00-index.md  harvest-{spec,code,design}.md  D<n>-<slug>.md  00-seams.md  00-arbiter.md
  spec/        <N>-<slug>.md   (scope section first, register last; §-numbers continue across phases)
  reconcile/   p<P>-<dimension>.md
  plans/       p<P>-00-index.md  p<P>-<nn>-<slug>.md
  manifests/   <plan-id>.json
  HANDOFF.md   updated at every stage boundary; under 40 KB (bootstrap.md) — HANDOFF-archive.md holds the rest
```

**Numbering — get this exactly right; it is what makes every citation unambiguous across phases:**

| Thing | Rule | Example |
|---|---|---|
| Spec sections `§N` | **continue** from the previous phase | phase 3 ended at §36 → phase 4 starts §37 |
| Plan rulings `R…` | **continue** | phase 3 ended at R145 → phase 4 starts R146 |
| Decisions `D<n>` | **restart at D1 every phase** — the `decisions/phase<P>/` folder scopes them | phase 4 is D1–D12 again, never D13+ |
| Arbiter rulings | **a phase-unique prefix**, restarting at 1, so they never collide with the last phase's | phase 3 `A1–A17`, phase 4 `PA1–PA46`; user rulings `U1…` per phase |
| Criteria | `AC-P<P>-<section>-<n>` | `AC-P4-45-7` |

Before writing the first number, **look at what the previous phase used** and follow it.

---

## §1 — decisions/phase<P>/00-index.md

```markdown
# Phase <P> — the decision round
> **Status**: <drafted | dispatched <date> | arbitrated>. **Route**: decisions → spec → plans.
> **Reading order**: brief → this file → harvests → your sources.
> **Base**: `<main branch>` at `<sha>`
> **Assumes**: `<remote>/<unmerged branch>` at `<sha>` — <what the round takes from it> (one line each;
> `route_state.py` flags any that moved or merged after a `git fetch`, F91)
> **Review**: `<base-sha>..<head-sha>` — <what it reviews: a merge request into `main`> (a review only;
> its Coverage is checked against `git diff --name-only` of this range, F104)
> **Verdict**: <approve | changes requested | unfinished — what is still unread or unprobed> (a review only)

<charter paragraph; what joins the phase from earlier deferrals>

## The asks — what the requester literally asked for
Every change the round makes cites one of these or a user ruling (`scope_check.py --asks`).
| Ask | Verbatim — quoted, never paraphrased | Source (ticket, review comment, the user's message, with date) |
|---|---|---|
| **Ask1** | "<the sentence>" | <where> |
### Do not touch
- <a file in backticks, a version, another ticket's or person's work, an unmerged branch, an asset
  another role owns — each with who said so; the files in backticks fail `scope_check.py --asks`>

**Harvest references** carry a prefix so numbering schemes cannot collide with decision numbers:
`hd:` design, `hs:` spec, `hc:` code.

## SETTLED — do not re-open, do not re-derive
Every row is already ruled; contradicting one needs an explicit argument with file:line. The
source is a ruling — U<n>, A<n>, D<n>, Ask<n>, a decision, spec or handoff `.md`, the user's words —
never only code: `decision_check.py` refuses a row that cites only `file:lines` (F86).
### <topic>
| # | Ruling | Source |
|---|---|---|
| **S1** | **<the rule, bolded where load-bearing>** | <U2 · `spec/02-x.md` §3 · the user, <date>> |
### Measured numbers that bind any ruling
| Figure | Source (with SHA) |

## Today's code — open to change
What the code does now that a ruling might keep or change; a row binds nothing.
| Behaviour | `<file>:<lines>` | Owner D<n> |

## Requirement dimensions — each owned or N/A
| Dimension | Owner: D<n>, S<n>, U<n>, Ask<n>, or `N/A: <reason>` |
|---|---|
| Actors and workflows | |
| Data identity — what makes two records the same on every import, merge or sync path | |
| Ownership and round-trip fidelity | |
| Business rules | |
| State machines — every status, and what survives each operation | |
| Integrations and system events | |
| Validation and exceptions — what is rejected, questioned or repaired | |
| Background jobs | |
| Security and privacy | |

## Confirmed defects the round inherits — verified here, not taken from a harvest
| Defect | Evidence | Owner D<n> |

## The decisions
> **Triage**: U<n> — <which the user kept, which went to the backlog> (needed past six live decisions)

| # | Decision | Why it is a decision and not a detail | Serves | Harvest |
|---|---|---|---|---|
| **D1** | **<title>** — <the questions it answers> | <the constraint or risk that makes it a decision> | <Ask<n> · U<n> · `backlog`> | `hd:… hs:… hc:…` |

Serves names the ask or user ruling the decision exists for; one that serves neither — tidier
infrastructure, a refactor the round noticed — is `backlog` and is not dispatched. Past six live
decisions, ask the user to triage before dispatch: each decision with its cost, keep or backlog
(`decision_check.py`, F89).

### What each decision may NOT decide
- **D1** prices; it does not choose which things pay — D2… name their transitions.
- <every pair of neighbouring decisions whose boundary an agent could cross, and the owner>
- <any question two rows could both answer, framed once here so they cannot answer it two ways>

## What this round is not
Not a spec · not a plan · not a re-litigation · not a fix round.
```

**At rung S** this file is the whole decision round: keep the asks, omit the "may NOT decide" fences; under each decision's row write
its ruling with the decision brief's output items 1–3, 5 and 6; put the user's rulings (U1…) at the
top; apply the §1e review's corrections here and carry any changed ruling into the spec and the plan
before execution — no decision agent reads it. Close it with the review's dispositions:

    ## Dispositions
    | Finding | Disposition | Basis |
    |---|---|---|
    | R1 | applied · applied (upholds S<n>) · declined · re-opened | <D<n>/the change made · U<n> · S<n> · verify/R1.md> |

A declined finding's basis is a user ruling, a SETTLED row, or a claim-only verifier's REFUTED
verdict with its claim quoted and a failing mutant run (`prompts.md` §1f) — never "known limitation" or "default" (F86); re-opening a SETTLED row
moves it out of SETTLED. A fix that enforces a SETTLED row unchanged is `applied (upholds S<n>)`,
never "declined" (F98). At M and L the same table closes the arbiter, for the seam review's
findings; a later review round in its own directory (`decisions/phase<P>/<round>/`) with no
arbiter closes its own index. `decision_check.py` checks all of it, and the hook holds `exec-`
dispatches until it passes, for each round's index too. The briefs' reading lists name files S omits (arbiter,
decision files, plan index): read this document in their place.

**A review's index** — one with a `**Review**` line — also carries what its verdict rests on:

    ## Coverage
    | File | Read |
    |---|---|
    | `src/app.py` | Read in full · Diff read · Not read |

    - `<probe command>` exit=<n> — <what it showed>

Every file the range changes has a row, labelled exactly `Read in full`, `Diff read` or `Not read`;
tests, recordings, documentation and lockfiles need none. Each probe is its command in backticks
and the exit code it ended with, run in a tree of the review's own (`tasks.md`). While any file is
Not read or no probe has run, the verdict says unfinished. `decision_check.py` checks it, and the
hook refuses posting a review comment to GitHub or GitLab while it fails, and a review itself
(`gh pr review`) while no index records its range (F104).

**Before dispatch, check the index against this list** — each item was a real framing error
somewhere:
- every ask is the requester's own sentence, from every source they wrote in (ticket, each review
  comment, the user's messages), and a decision row that serves no ask is a question for the user,
  not a row (F89);
- every SETTLED row quotes its source correctly and is not contradicted by a later ruling or the
  owning spec section (check the spec, not just the concept);
- every claim about the code in the index was opened by you;
- no question can be answered by two rows — if one can, frame it once under "may NOT decide";
- any prior user ruling on the subject is found and recorded (search the old decision and plan
  indexes for the user's own rulings — one index re-opened a question the user had closed);
- each row's *why* names the stake, the contradiction in the sources, and any live defect
  (`examples.md`);
- **a SETTLED row is a ruling, never a description of what the code does today** — if the code
  does something harmful, that is a confirmed-defects row with an owner, not a settled row;
- every requirement dimension has an owner or a one-line `N/A: <reason>` — a dimension the asks
  never touch is N/A, cheaply; one they touch and no row owns is a missing decision;
- `scripts/decision_check.py decisions/phase<P>` exits 0;
- **every figure that drives a decision is labelled *measured*, *documented* or *assumed*** — and
  where a read-only probe is cheap (an unauthenticated API call, a throwaway repo, running the
  regex, timing the command), it is *measured*. A run that only read the documentation scored
  below one that probed the same API live.

---

## §2 — decisions/phase<P>/00-arbiter.md

```markdown
# Phase <P> — the user's rulings U1–U<k> and the arbiter's rulings A1–A<m>
> **These WIN over any `D*.md` they name.** Precedence: U > A > D.
> Made <date> on <SHA>, after <the reviews that ran>. The seam file carries the evidence; a ruling
> cites it as `seams A1`. **Code claims re-verified here**: <list each, with file:line>.
> <If the cross-model review did not complete: say so, say what replaced it, and when it re-runs.>

## The user's rulings — <date>
### U1 — <the ruling in one line>
<what it removes, what it keeps, what becomes moot — each moot item named so nobody builds it>

## Arbiter rulings
### <group: safety / surfaces / the ledger / carried / sequencing / schema>
**A1 — <ruling in one line>.** (`seams A1, C6`) <the rule; which side won and why in ≤2 sentences;
what each losing ruling must now say>

### Sequencing
**A<n> — Lane 0 runs before any new feature.** <shipped defects and false published claims, each
with its owner section>
(What belongs in Lane 0 — check each class, both independent re-runs missed the third:
 1. a shipped defect that can destroy or overwrite user data;
 2. a published claim (README, security policy, consent copy, a settings label) that is false of the
    tree **at the next tag**;
 3. **any defect whose damage a new rule of this phase makes permanent** — e.g. a writer that
    over-pays a ledger, once a raise-only floor makes every over-payment irreversible; a writer that
    corrupts a record, once a new "never deleted" guarantee freezes it. Fix it before the rule lands.)

**A<n> — Defaults the arbiter set where a ruling asked the user, and the user may overturn.**
<list — so none reads as settled by the user>

### What the round confirmed without change
<one line per accepted ruling>

## Dispositions
| Finding | Disposition | Basis |
|---|---|---|
| R1 | applied · declined · re-opened | <A<n> · U<n> · S<n> · verify/R1.md — as at S, §1> |
```


---

## §3 — the scope section, `spec/<S>-phase<P>-scope.md`

```markdown
## <S>. Phase <P> — scope
<charter; "derived from a decision round, not written freehand"; precedence U > A > D; which
recorded obligations are consumed here>

### <S>.1 In
| § | File | Owns | Decisions and rulings |

### <S>.2 Out, and where each goes instead
| Out | Where (phase / never / declined by the user / past release) | Why |

### <S>.3 What phase <P> inherits and must not re-derive
<the five rules most often re-decided by accident>

### <S>.4 The boundaries — inherited, widened, new
**Boundary N — <name>. WIDENED, and this stops a claim the product makes today.** <the exact
claim that stops, where it is published, what replaces it, the audit that proves the new one>

### <S>.5 The invariants, at the moment they stop being vacuous
| Invariant | Why phase <P> is where it breaks |

### <S>.6 Lane 0 — runs before any new feature
| Item | Owner § |

### <S>.7 What this supersedes — anchored, applied later
| Anchor (verbatim) | Superseded by | Applied with |
(Applied as `[p<P>]` markers in the change that lands the code — the bar and the body move together.)

### <S>.8 Defects this round confirmed, with owners
| Defect | Verified at (file:line) | Owner § |

### <S>.9 The contract, as it stands, and the rules for changing it
<current counts with SHA; deltas never totals; regenerate once after merges; new prefixes; one
rebuild per table per phase; contents-not-numbers>
```


---

## §4 — plans/p<P>-00-index.md

```markdown
# Phase <P> — plan index
## The plan set — | Plan | Section | Wave | Depends on | Migration(s) |
## Wave order — waves in dependency order; which may run in parallel; the register lane last
## Migration numbers — assigned once, by one hand, in dependency order
(each rebuild names the trap it carries: sequence high-water marks, fixtures a new CHECK rejects)
## The reconciled contract delta — stated once, here (base counts with SHA; each section's delta;
new names with owners). No plan restates a total.
## Rulings R<r>… — each: the finding, the ruling, which plan carries it
## Reading map — per plan, what it reads beyond its own section
| Plan | Own § (in full) | Other sections — heading or line range, and the value it needs there | Arbiter / U rulings | Reconcile findings | Code — harvest rows |
(Built from the section's own references — `grep -no '§[0-9]\+' spec/<n>-*.md` — and the returns
log's cross-references. A floor, not a fence: the author reads further where its section needs it
and names each such read in its reply, and those gaps correct the next phase's map.)
```

