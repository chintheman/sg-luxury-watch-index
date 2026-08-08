---
name: qa-repro
description: Minimising a failure to the shortest reliable repro, and telling a race from order-dependence from a real bug. Load when triaging a fuzzer finding or a flaky test.
---

# Reproduction and minimisation

## Minimise first

A 40-step failure is not a bug report; it is a transcript. Reduce it before you
write anything up.

1. **Bisect the steps.** Delete the second half; still fails? Keep going.
2. **Shrink the data.** Property-based tools shrink automatically — use their
   output. By hand: shorten strings, zero the numbers, empty the collections.
3. **Drop the setup.** Most fixture setup is irrelevant to the failure.
4. **Confirm determinism.** Run the minimised case 10 times. If it fails 10/10,
   you have a repro. If 3/10, you have something more interesting.

The target is three steps or fewer. Under that bar a developer can hold the whole
thing in their head, which is what makes a bug get fixed rather than triaged.

## Classifying an intermittent failure

| Signal | Likely cause |
|---|---|
| Fails only in parallel, passes alone | shared state or a shared DB |
| Fails only after a specific other test | order-dependence — usually unreset global state |
| Fails at a consistent rate regardless of order | **a real race in the code** |
| Fails only on slow/loaded machines | timing assumption — a sleep pretending to be a wait |
| Fails only against a live third party | external dependency; needs a fake at the process edge |

**The third row is the valuable one.** A test that fails 2% of the time
independent of ordering is usually reporting a genuine production race that
everyone has been trained to retry away. Promote it to a bug with a repro, and
say plainly that it was misfiled as flake.

## Writing it up

Fill `.qa/bugs/<id>.md` completely. Keep **severity** (technical damage) and
**priority** (business urgency) independent — they answer different questions,
and collapsing them is how a data-corruption bug ends up behind a UI nit.

`expected` must cite an oracle proposition ID where one exists. A bug report
whose "expected" is only the reporter's opinion is an argument, not a defect.
