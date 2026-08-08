# .qa/STRATEGY.md — human-owned

Revisited quarterly. There is deliberately **no standing strategist agent** (§16):
a monthly document nobody reads is not worth an agent. This is a short human
document, written with Claude's help, that the monthly review actually uses.

## What we are optimising

**Calibrated shipping confidence** — not coverage percentage, not test count, not
bug count. The deliverable is a per-PR Confidence Report: a risk-scored verdict,
the evidence behind it, and an explicit statement of what was *not* tested.

A report saying "MEDIUM, these three paths are untested, here's why" is a
success. A green checkmark with no reasoning is a failure even when the code is
fine.

### What "confident to ship" means here (§15 Q20, answered)

> "No bugs, no inaccuracies, no faulty logic, no faulty math, no contradictions."

Five criteria, tracked per PR in `.qa/RISK-RULES.yaml` → `confidence_criteria`:
faulty math · faulty logic · contradictions · inaccuracies · bugs generally.

This is a **correctness** definition. It says nothing about performance, UX or
scale — so the marshal does not lead with those, and neither should the monthly
review. If that changes, change it here first.

## Where we will not chase quality

- **Presentation components** — exempt from the mutation gate. Mutants there are
  overwhelmingly equivalent. Reported, not gated.
- **Generated code** — not mutated, not hand-tested.
- **Anything with no observable outcome** — the system cannot test what the app's
  own interfaces cannot see. Those areas need instrumentation before they need
  tests.

## Current state — first install

| Item | Status |
|---|---|
| Phase 0 | complete (probe verified, §11 resolved) |
| Phase 1 | complete (gates built and self-tested) |
| Phases 2–5 | built; acceptance pending a real codebase |
| Mutation threshold | 0.60 — ratchet monthly, never down |
| `SHIP_WITH_WATCH` | **enabled**, gated on rollback-safe paths (§15 Q17: fast rollback, no flags) |

## Open

1. **Q17** — do feature flags or staged rollout exist? (The only one left.) Until answered,
   `SHIP_WITH_WATCH` stays off and the marshal has only SHIP/HOLD.
3. **Ticket quality** — §17 is blunt that the system's ceiling is set by it. If
   tickets are one-liners the oracle will be weak, and that is a process problem
   no prompt can fix.

## Monthly review — 30 minutes, reads auto-harvested data

- Is the mutation threshold ratchetable?
- Which modules keep appearing in `untested`? Those are structural gaps, usually
  missing seams rather than missing tests.
- Which banding rules produced disagreement? Add or amend a rule. **Do not tune a
  weight vector** — that was cut deliberately (§16).
- Which agents burn budget without producing accepted output? Below 50%
  acceptance an agent is net negative: fix its prompt or retire it.
