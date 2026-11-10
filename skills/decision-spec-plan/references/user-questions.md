# Asking the user

Every ask follows this: a decision call, a scope question, a budget, a push.

- **Few, and only the open ones.** At most four per `AskUserQuestion`, the four that most change
  what gets built. Leave out any a SETTLED row, a U-ruling or the asks already answer. A call you
  are sure of is not a question: it goes in the arbiter as a default the user may overturn, and a
  fifth question becomes one too. **Why:** published, one to three questions keep 86–94% of the
  value of asking (arXiv 2610.24411).
- **The recommended option first. Each option states its consequence and its source** (file:line,
  a measured figure, a ruling id), so the fallout needs no second round-trip (`examples.md`, A user
  question). **The question carries the strongest case against your recommendation** in one
  sentence: the losing side's best argument, not a strawman. **Each option names the ask it
  serves** — `Ask<n>` with the requester's sentence quoted — or says it serves none, which makes it
  added scope (below); a default you state for the arbiter does the same. **Why:** three of four
  over-scope plan rows in one window were born in an ask option or a stated default (F89).
- **A call that adds scope offers `backlog`.** That option keeps the change out of this round,
  recorded and not dispatched. **Why:** asked for a bug hunt, one user was offered a ~5M review
  panel ("Scratch 7 sins run"); a round of 14 mostly-infrastructure decisions was approved and
  disowned a minute later (F89).
- **A budget ask is the sentence `--budget` prints.** It has the recorded figure, the reason
  against and a smaller option, and covers the route's work left — one ask a route, at the
  go-ahead, never a wave or a group (F74, F93). It opens with the asks the figure does not
  deliver — deferred by a U-ruling, or no plan row serves them (`scope_check.py --asks`) — or says
  it delivers every ask; a "done" report opens the same way (`execution.md`, Report; F89).
- **A publish, a push or an API write is asked by name.** The option names the command and its
  target (`npm publish` of which packages, the remote and branch); a "go" to something else never
  covers it, and a standing "later" rules it out until the user lifts it. **Why:** one lead
  published five immutable packages on a bare "go" against the user's "CI and publishing later";
  the re-plan cost 3.9M (F81).
- **The hook tallies the answers.** If 9 of the last 10 took your recommendation, it says so:
  ask fewer and sharper questions, and rule the rest yourself. **Why:** across three projects
  users took the recommendation in 34 of 37 asks and 27 of 29, once 3 s after the ask; published,
  reviewers habituate to recommendations (arXiv 2606.22721; F89).
- **A goal the user changes while a lane runs never goes into that lane.** Stop the lane at its
  next task boundary, re-plan the tasks the change touches, and dispatch a fresh group on the new
  plan. **Why:** published, a goal clarified in mid-run does worse than one never asked (arXiv 2605.07937).
- **"Find a good stopping point", "pause", "I need to go": hand off now.** Dispatch nothing new.
  Write the handoff's in-flight block and its resume line, then tell the user what is still
  running: an agent minutes from its checkpoint finishes, any other is stopped at its next task
  boundary. **Why:** one lead waited for a group to finish after "find a good stopping point";
  the group was lost when the session ended (0.3M and a re-plan).
