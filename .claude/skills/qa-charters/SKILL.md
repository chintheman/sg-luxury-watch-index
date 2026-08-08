---
name: qa-charters
description: Writing charters, running a time-boxed exploratory session, and the session sheet format. Load before an exploratory testing session.
---

# Charters and session-based exploratory testing

## Charter template

> Explore `<target>` with `<tools/data>` to discover `<risk>`.

A good charter names a **risk**, not an area. "Explore checkout" is a to-do.
"Explore coupon stacking at checkout with expired and 100% coupons to discover
incorrect totals" is a charter — it tells you when to stop and what counts as a
find.

## Where charters come from, in priority order

1. `risk-scout`'s `failure_modes` — already phrased as "if this is wrong, users see X".
2. Oracle **Ambiguities** — the spec did not determine behaviour, so nobody wrote
   a test. Highest yield in the list.
3. High-risk areas with low mutation score — code that matters and is weakly asserted.
4. The standing hopper in `.qa/charters/backlog.md`.

## Running the session

Time-boxed by turns. One charter per session. When you find something, note it
and **keep going** — finishing the charter is the point; a session that stops at
the first bug leaves the rest of the risk unexplored.

Record what you tried even when it found nothing. "Tried X, Y, Z, all correct" is
genuine evidence for the marshal, and it stops the next session repeating you.

## Session sheet

Spec §3.8 trims SBTM to the fields that carry information. Full task-breakdown
percentages and charter-vs-opportunity ratios were deliberately cut (§16) — they
are accounting, not findings.

```markdown
CHARTER: <the charter>
AREAS:   <files, routes, screens touched>
NOTES:   <narrative — what you tried, which oracles you used, what looked odd>
BUGS:    <ids and one-line titles>
ISSUES:  <blockers: missing test data, broken staging, no way to observe X>
UNFINISHED: <what you did not get to — requeue it to the backlog>
CONFIDENCE: <prose — how you feel about this area now, and why>
```

**CONFIDENCE is not optional and not a number.** It is the SBTM "Feelings" line,
it is the one qualitative signal in the whole system, and the marshal reads it.
"Low — found a bug in 18 turns on the money path" carries information no metric
does.

**ISSUES matters more than it looks.** An environment you could not test in is a
finding about testability that will recur every session until someone fixes it.
