---
name: qa
description: QA this repository end to end and give a ship/hold verdict with evidence. Use whenever the user says "QA this", "QA the repo", "QA the build", "review this before I ship", "is this safe to ship", "check my changes", "run QA", or asks for a quality/test review of the current project. Sets itself up on first run — the user never has to install or configure anything.
---

# QA — the one command

The user wants one thing: **is this safe to ship, and what's wrong with it?**

Do the whole job. **Never ask a setup question.** Never tell them to run
something first. Never make them choose a mode. If something is missing, either
fix it silently or work around it and mention it once at the end.

If the user gave an argument (a path, a ticket, "the billing change"), scope to
that. Otherwise scope it yourself, using step 2.

---

## 1. Self-install, silently

The repository is already cloned — you are running inside it. That is not a
step, and it is never the user's problem.

Check for `.qa/config.env`.

**If it exists**, QA is installed. Skip to step 2.

**If it does not**, install it now without narrating:

- If `.qa/adapters/` is missing entirely, clone
  `https://github.com/chintheman/Agentic-QA-Team` to a temp directory outside
  the repo, copy in `.claude/`, `.qa/`, `scripts/` and `agents/`, and delete the
  temp directory.
- Run `bash scripts/qa-init.sh` and read `.qa/INIT-REPORT.md`.
- Write `.qa/config.env` with the detected adapter. If the adapter is `custom`,
  write one from `.qa/adapters/custom.sh.template` — implement only what you can
  actually implement, and leave `qa_unimplemented` for the rest. An adapter that
  returns success from a stub turns its gate into a rubber stamp.
- Fill `.claude/skills/qa-conventions/SKILL.md` from **real test files**.
- Write `.qa/RISK-RULES.proposed.yaml`. Do **not** overwrite
  `.qa/RISK-RULES.yaml` — banding needs human sign-off.

Mention the install in one line at the end, not as a preamble.

---

## 2. Work out what to review, in this order

1. **Uncommitted changes** — `git status --porcelain`. If any, that is the target.
2. **This branch vs the default branch** — if ahead, review those commits.
3. **The last commit on the default branch** — if the tree is clean and level.
4. **Nothing changed** — say so, then audit the highest-risk module instead
   (from `.qa/RISK-RULES.yaml`, or the largest source file if unbanded) so the
   run still produces something.

State the scope in one line so they know what you looked at.

---

## 3. Band it, then match the effort

Apply `.qa/RISK-RULES.yaml` (or the `.proposed` file if that is all there is).
First matching rule wins.

| Band | Do |
|---|---|
| **low** | Run the suite. Report. Stop. |
| **medium** | Suite + vacuity + mutation on changed files. |
| **high** | The above + an oracle pass on intended behaviour, and name uncovered propositions. |
| **critical** | The above + probe the money/identity/irreversible paths for what has no test at all. |

Do not run agents that have nothing to do. If there is no browser harness, no
`flow-smith`. If there is no multi-user auth surface, no `authz-prober`.

---

## 4. Run the gates that can actually run

In cheapest-first order, skipping any whose tooling is absent:

1. **Suite** — `qa_test_all`. If it fails, that dominates everything: report it
   first and do not bury it under mutation numbers.
2. **Vacuity (G3)** — zero-assertion, mock-only, skipped, tautological tests.
3. **Mutation (G2)** — only on changed files in `mutation_paths`.
4. **fails-before/passes-after (G1)** — only when a test targets a defect.

**Missing tooling is a finding, not a blocker.** No mutation tool means the
central gate is unavailable — say so plainly and continue. Never report success
for a gate that did not run.

Count skipped tests. A suite where 28% skip proves at most 72% of itself, and
the user needs that number to read the green correctly.

---

## 5. One report, in plain language

Lead with the answer. No preamble, no method description.

```
VERDICT: SHIP / SHIP_WITH_WATCH / HOLD     confidence: HIGH / MEDIUM / LOW

Scope: 3 changed files in index/ (band: critical)

What I checked
  Suite         115 passed, 44 skipped (28% of the suite never ran)
  Vacuity       clean
  Mutation      0.71 on 3 files — above the 0.60 gate
  Untested      2 of 7 behaviours have no test

What's wrong
  1. <the most important thing, in one sentence, with file:line>
  2. ...

What I could NOT check
  - <every gap, named. Never leave this empty on a high-risk change.>

Next
  <one concrete action>
```

Rules for the report:

- **`What I could NOT check` is mandatory** on high and critical. If you cannot
  name what you did not test, you were not thinking. Absent tooling, skipped
  tests, unspecified behaviour, exempt files — all belong here.
- **`SHIP_WITH_WATCH` only if `ship_with_watch_available` is true**, and never
  when the change touches `rollback_unsafe_paths` — a migration or a published
  figure cannot be undone by redeploying old code, so "watch it" would name a
  response that does not exist.
- Confidence caps: no specification → MEDIUM at best. Mutation gate unavailable
  → MEDIUM at best. Suite red → LOW.
- Write for someone deciding at 5pm on a Friday. "Billing error rate above 2%
  within 30 minutes" is actionable; "keep an eye on checkout" is not.

---

## What not to do

- Do not ask which mode, depth, or agent they want. Choose.
- Do not stop to request setup, credentials or a config file. Work around it.
- Do not report a clean verdict when a gate could not run. That is the failure
  this system exists to prevent, and it costs more trust than any missing test.
- Do not pad. Three real findings beat twelve manufactured ones.
