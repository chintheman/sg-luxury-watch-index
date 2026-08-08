---
name: qa-mutation
description: Running and reading mutation testing in this repo — commands, mutant states, and which survivors are genuinely equivalent. Load before starting the mutation loop.
---

# Mutation testing

Mutation score is the gate because coverage is trivially reward-hackable: call
the code, assert nothing, get 100%. A mutant that survives is a specific,
concrete statement that some behaviour is unasserted.

## Commands

| Task | Command |
|---|---|
| Fast in-loop subset | `<<coverage-filtered, changed file only>>` |
| Full scoped run | `.qa/gates/g2-mutation.sh` (CI runs this once) |

Use the fast subset while iterating. The blocking evaluation happens once in CI —
re-running everything each turn is a latency and cost sink, and the numbers will
not differ enough to change what you do next.

## Reading mutant states

| State | Meaning | Your move |
|---|---|---|
| **Killed** | A test failed when the mutant was introduced. | Nothing. |
| **Survived** | Behaviour changed and every test still passed. | **Write a test that kills it.** This is the whole loop. |
| **NoCoverage** | No test executes this line. | A blind spot. Report it — it belongs in `untested`, not in the score. |
| **Timeout** | The mutant caused a hang. Counts as killed. | Nothing. |
| **CompileError** | Mutant was not valid code. | Ignore; the tool excludes it. |

Score = `killed / (killed + survived + timeout)`. NoCoverage mutants are
excluded from the denominator on purpose (see `.qa/DECISIONS.md` D-006) — they
are a coverage finding you cannot fix by asserting harder.

## Genuinely equivalent mutants

Some survivors cannot be killed because the mutant is semantically identical.
Recognise them and stop rather than contorting a test:

- Reordering operations with no observable difference.
- Changing a value used only in a log line or error string.
- `<=` → `<` on a bound that other constraints make unreachable.
- Presentation-only changes — `className`, conditional rendering, formatting.
  This is why `.tsx`/`.jsx` are excluded from `mutation_paths` entirely.

If you believe a survivor is equivalent, **say so explicitly in your report with
the reasoning**. Do not silently leave it, and do not write a junk DOM assertion
to make the number move. An honest "3 survivors, 2 equivalent, here's why" is a
better result than 0 survivors bought with meaningless tests.

## When the score will not move

Usually the code has no seam: the behaviour is unreachable without I/O you
cannot control. That is a **testability finding**, not a test-writing failure.
Report it. Missing seams are the structural gap that keeps showing up in
`untested` month after month.
