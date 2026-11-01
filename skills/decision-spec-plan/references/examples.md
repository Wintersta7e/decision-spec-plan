# What good looks like — worked examples

Real shapes from one project's rounds, with the project's specifics generalised. Use them to judge
your own drafts: an index row or an arbiter ruling that is vaguer than these will produce vaguer
agents.

## A SETTLED row

Weak: *"XP is append-only."*

Strong — states the rule, the reason it reads as arbitrary without, and its source:

| # | Ruling | Source |
|---|---|---|
| **S4** | **"Append-only" is shorthand, and it is wrong for half the ledger.** Two classes: **git-derived** kinds are a pure function of history and are **deleted and recomputed** on a merge or an identity change — production does this (`merge/apply.rs:158-165`); **retained** kinds are reparented, never recomputed. **What never falls is the displayed level, not the row set.** Every new kind is classified into one class before it is priced | `01-data-model.md:442-468` |

The weak row was in the draft index; a framing review caught that it contradicted the owning spec
section and would have made one decision agent design retention rules incompatible with merges.

## A decision row

| # | Decision | Why it is a decision and not a detail | Serves | Harvest |
|---|---|---|---|---|
| **D8** | **"Exists nowhere else" — the deletion invariant and the analyser that decides it** — what counts as elsewhere (a same-disk copy? a mirror?), how many escapes there are, whether any typed confirmation overrides the invariant, and making the shipped enabling half true | This is the rule that makes the tool not a shredder, and it is contradicted inside its own source document (which permits typing a name to delete an unbacked repository). The escapes are counted three ways. **And the analyser this phase would build on is wrong today** — the first three rows of the confirmed-defects table | Ask2 | `hd:C-12..C-15, U-16` · `hs:§10` · `hc:D2..D5` |

Note the three parts of the middle column: the stake, the contradiction in the sources, and the live
defect. That is what stops the agent treating it as a detail.

## A fence ("what each decision may NOT decide")

> **The verdict's XP, framed so D1 and D7 cannot answer it two ways.** "Later earns the same XP as
> any other verdict" (SETTLED) is about **the verdict**: every verdict pays one equal award. **A clean
> archive and a revival are separate transitions** on the settled source list and pay on their own
> evidence. **D7 rules the boundary at which the verdict award is written**; D1 rules its value. A
> ruling that disagrees with this framing says so first.

This fence was added after the framing review found the question split across two rows. Both
rulings then came back consistent.

## A dispatch focus paragraph

> YOUR DECISION: **D10 — The write surface.** … THIS IS THE HIGHEST-RISK DECISION IN THE PHASE: it
> stops a claim the product makes today. Say so in those words if you widen it. Focus: per verb —
> <list>. And THE AUDIT THAT REPLACES THE ARGV-ONLY ONE: MEASURED this session — a user's config made
> the audited command delete a local-only tag; <the flag> stopped it (`<file:line>`). A verb's
> behaviour is argv AND config (and hooks, filters, refspecs from config); the replacement audit must
> prove additivity against that. Say what it scans and that it prints its count.

The measured defect in the dispatch is what made the agent probe further — it found the same command
also **deleting a checked-out branch** under a config refspec, which the lead then reproduced.

## An arbiter ruling

> **A1 — The verifying read: D8's shape wins; D10 owns its intent and admits it.** (`seams A1, C6`)
> `Intent::Fetch` is retired — its one production caller is the pre-flight (`handle.rs:166`, verified)
> and a ref-writing fetch is the thing that deleted a checked-out branch here. It is replaced by an
> objects-only read that writes no ref … **This slice lands in Lane 0**, before any feature.

Shape: which side won, the one verified fact that decided it, what each losing ruling must now say,
and when it lands.

## Two rulings independent re-runs got wrong — the general pattern behind each

**One act, one payout.** A pre-pass approval of N projects must not pay N awards in one click. Both
re-runs capped it at twelve a day, so one click still paid twelve. The ruling that held: *a verdict
given on a card pays that project's once-ever award; a bulk approval pays **one** award for the act,
and the group's projects keep their own once-ever eligibility.* **Pattern: any reward reachable by a
bulk action is volume; price the act, not the items.** (The project already had the precedent —
*forty items closed in one day pay once* — and the right ruling cited it.)

**The product's own artefact must not trap the user.** The Seal writes an annotated tag; under the
deletion invariant an annotated tag object is a preserved byte, so every sealed project would block
Uninstall on the product's own tag. Both re-runs let it block. The ruling that held: *the product's tag
is excluded from the preserved set **iff it re-derives byte-identically** from what the index stored at
write time, and the words stay in the index row after removal.* **Pattern: when a safety rule would
count the product's own writes against the user, exclude exactly the bytes the product can
reproduce — never a blanket exemption.**

## A user question

Asked once, at the arbiter, ≤4 questions, recommended option first, **each option stating its
consequence**:

> *Should the phase admit a narrow `push` so the first two preservation escapes exist? You declined
> push twice last phase, on an argument scoped to that phase.*
> — **Admit narrow push (Recommended)**: only inside a preservation offer … publication is
> irreversible and the copy says so before the click. The README's "git writes are clone and fetch"
> line changes.
> — **Decline push**: the only escape is a bundle the app writes …

The user declined. Because the question named what "decline" costs, the arbiter could rule the
consequences (escapes 1–2 become things the user does, verified by the app's live read) without a
second round-trip.

## A scope-section boundary

> **Boundary 1 — git. WIDENED, and this stops a claim the product makes today.** The intent set is
> `{Clone, ObjectsRead, BundleWrite, TagWrite}` … **The claims that stop**: `README.md:77-79`
> (*"its only writes are clone and fetch"*) — already false for a user whose config prunes (measured),
> and replaced in Lane 0. **The claim that survives**: the read module stays read-only by the
> subcommand allow-list — it changes; it does not write.

A boundary that widens names the published sentence that stops being true, where it is published,
and what replaces it.
