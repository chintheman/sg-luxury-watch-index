---
description: One-shot setup. Reads the repo, works out the stack, wires up the QA team, and tells you honestly what still needs a human.
---

Set up the Agentic QA Team in this repository. Do the whole thing; do not stop
to ask permission between steps. Report at the end.

## 1. Recon — deterministic first

Run `bash scripts/qa-init.sh`, then read `.qa/INIT-REPORT.md` and
`.qa/init-report.json`.

That script already answered every §15 question that can be answered by looking
at files. **Do not re-derive what it found.** Your job starts where it stopped:
the judgement calls.

If it reports missing prerequisites, say so plainly at the end and continue —
most of the setup still works without them.

## 2. Pick or write the stack adapter

If `adapter` is `node-vitest` or `python-pytest`, use it. Write
`QA_ADAPTER=<name>` into `.qa/config.env`.

If it is `custom`, **write a real adapter** at `.qa/adapters/<stack>.sh` from
`custom.sh.template`. Read `.qa/adapters/README.md` for the contract. Fill in
every function you can actually implement, and leave `qa_unimplemented` in place
for the ones you cannot — an adapter that returns success from a function it
never implemented turns its gate into a rubber stamp, which is the exact
vacuous-pass failure the gates exist to catch.

**Verify it works** before moving on: run the suite through `qa_test_all` and
confirm it is green. Getting this wrong is the highest-cost mistake in setup —
if the runner is misresolved, every test run looks like a collection error and
G1 silently reports INCONCLUSIVE forever, measuring nothing while appearing fine.

## 3. Write the `qa-conventions` skill — the highest-value step

Replace the placeholders in `.claude/skills/qa-conventions/SKILL.md` with what
this repo **actually does**. Read real test files to find out; do not guess.

Capture: where tests live, the naming pattern, the exact run commands, the
factory/fixture helpers, how an authenticated client is obtained, how data is
seeded, and any local trap you can see (frozen clocks, per-worker schemas,
order-dependent suites).

Spec §9 calls this the highest quality-per-token skill in the set. A wrong one
is worse than none — agents follow it confidently and produce tests reviewers
reject wholesale.

If there are no existing tests, say so in the skill rather than inventing a
convention, and warn in your report that acceptance will be low until a human
establishes the house style.

## 4. Propose risk rules — propose, do not impose

Write `.qa/RISK-RULES.proposed.yaml` using `candidate_risk_paths` from the recon
plus anything you find that touches money, identity, PII, or irreversible
operations.

**Do not edit `.qa/RISK-RULES.yaml` directly.** It is the referee, it is
guard-protected, and Phase 0 requires a human to sign off on banding before it
governs anything. Present the diff and let them apply it.

Also set `mutation_paths` for this stack: include the languages the mutation
tool understands, and exclude presentation components and generated code.

## 5. Check the gates still hold on this stack

Run `bash .qa/selftest/run.sh`.

If anything fails, fix it and re-run. A gate that passes on the kit's own
fixtures but breaks here is the single most dangerous state this system can be
in — it looks configured and measures nothing.

## 6. Report

Print, in this order:

1. **What works now** — which commands are usable today.
2. **What is blocked** — no mutation tool, no test command, no seams. Be
   specific about the consequence, not just the fact.
3. **What needs a human** — §15 Q17 and Q20 verbatim, plus sign-off on the
   proposed risk rules. Ask Q17 and Q20 as actual questions; they are the two
   the system cannot answer for itself, and Q20 determines what the marshal
   measures.
4. **The one thing to do next** — a single concrete command, usually
   `/qa-risk` or `/qa-oracle <ticket>`.

Be honest about gaps. A setup that reports "all set" while the mutation gate is
unavailable produces confident verdicts backed by nothing, and that costs more
trust than admitting the gap on day one.
