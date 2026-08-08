# .qa/DECISIONS.md — deviations from the build spec

Spec §0.4: "Deviations are expected. Record each one and its reason."
Each entry states what the spec said, what was actually done, and why.

---

## D-001 — This repo is the kit, not an instrumented target repo
**Spec:** §0 "Build the system described here inside a target repository."
**Done:** Built as a stack-agnostic, installable kit. Stack-specific behaviour
lives behind the adapter contract in `.qa/adapters/`.
**Why:** The repository was empty at Phase 0 — no commits, no source, no stack —
and no other repository is in this session's scope. Recon §15 Q1–Q16 have no
answers to find. Building against an imagined stack would have produced gates
that were never executed once, which is worse than gates that are honestly
marked "adapter required".
**Cost:** Phase 2's acceptance bar (mutation lift on three real files, ≥60%
human acceptance) cannot be claimed here and carries over to first installation.

---

## D-002 — G5 is one agent-aware settings hook, not one CI job per agent
**Spec:** §5 G5 and §11 require per-agent enforcement, and explicitly warn:
"The `PreToolUse` payload does not reliably carry a subagent identifier; a
global guard will fail open (everything allowed) or closed (everything blocked)."
The prescribed fallback is one CI job per agent with its own settings file.
**Done:** A single settings-level hook, `.claude/hooks/qa-guard.sh`, which reads
`agent_type` from the payload and enforces the §4 P4 table.
**Why:** The spec's premise is false on CLI 2.1.226. Measured: the `PreToolUse`
payload **does** carry `agent_type` (and `agent_id`) for both subagent dispatch
and `--agent` dispatch, and **omits** `agent_type` for the main session. That is
exactly the signal a global guard needs.
**Fail-closed by construction:** an unrecognised `agent_type` is DENIED, not
allowed. A missing `agent_type` is treated as the orchestrator and gets only the
globally-applicable rules (G4). So the spec's "fails open" hazard is answered by
policy, not by luck.
**Why this is better than the prescribed fallback:** one job per agent multiplies
CI jobs by nine, and the SoD table then lives in nine settings files that drift
apart. One table, one guard, one place to audit.
**Retained from the spec:** per-agent `--tools`/`--allowedTools` scoping is
*also* applied. The hook is the backstop, not the only lock.

---

## D-003 — Per-agent `hooks:` frontmatter is unsupported; enforcement moves to settings
**Spec:** §10's sample `spec-oracle` declares `hooks:` in its own frontmatter,
and §11 lists this as the primary mechanism for oracle blindness and G5.
**Done:** All hooks are declared in `.claude/qa-settings/*.json` and loaded with
`--settings`. Agent frontmatter keeps `tools`/`disallowedTools`/`model`/etc.,
which *are* honoured, and documents the hook that governs it.
**Why:** Measured unsupported on 2.1.226. A hook declared in agent frontmatter
never fires — not under `--agent`, not as a Task-spawned subagent, and
`--debug hooks` shows no hook events. Settings-level hooks do fire, and do
intercept subagent tool calls.
**Escalation:** §11 says to stop and escalate rather than silently substitute a
prompt instruction for a mechanical gate. That is not what happened here: the
mechanical gate is retained, at a different layer. **Flagged for review** because
it means the sample agent definition in spec §10 is not runnable as written.

---

## D-004 — `--allowedTools` is not a restriction outside headless mode
**Spec:** §8's CI example relies on `--allowedTools` to constrain each agent.
**Done:** Kept, but paired with `--tools` and `--disallowedTools`, and backed by
the G5 hook.
**Why:** Measured semantics (`.qa/PROFILE.md` §2): `--allowedTools` is a
*permission* allowlist. In `-p` mode an un-allowlisted tool cannot be approved,
so it is effectively denied — which makes §8's CI usage sound. Interactively it
only pre-approves and restricts nothing, so the same line copied into a local
session would grant far more than intended. `--permission-mode dontAsk` does not
widen the allowlist.
**Note:** An earlier reading of this probe was wrong in the other direction —
the transcript said Bash "executed successfully" when it had been blocked. The
correction came from adding a positive control and measuring side effects rather
than parsing prose. Both the probe and G1 now assert on artefacts, never on text.

---

## D-005 — Fork PRs are skipped with a visible comment
**Spec:** §7.4 requires an explicit decision, not silent failure.
**Done:** `qa-pr.yml` guards every job on
`head.repo.full_name == github.repository`, and a separate job posts
"QA not run (fork PR)" so the absence is visible in the PR.
**Why:** Fork PRs get a read-only token and no secrets, so the workflow cannot
run. `pull_request_target` would work but runs untrusted code with a writable
token — a poor trade for a QA system whose agents execute repository code.

---

## D-006 — Mutation scoring excludes no-coverage mutants from the denominator
**Spec:** §5 G2 sets a threshold on mutation score without defining the
denominator.
**Done:** `score = killed / (killed + survived + timeout)`. Mutants with no
coverage are reported separately.
**Why:** A file no test touches would otherwise drag the score toward zero with
mutants `unit-smith` cannot act on, and the agent would burn its turn budget on
an unreachable target. No-coverage mutants are a *blind spot* finding for
`risk-scout` and for the marshal's `untested` list, not a mutation failure.
**Risk, stated:** this makes the score flattering for barely-tested files. It is
mitigated by reporting `no_coverage` in the Confidence Report, so a high score
over three covered mutants cannot be mistaken for a well-tested file.

---

## D-007 — G3 stops at four detectable patterns
**Spec:** §5 G3 already scopes this and moves self-computation detection to the
human review checklist.
**Done:** Followed exactly: zero assertions, mock-only assertions, skip/only/todo,
literal tautology. Implemented as per-language lint (ESLint rules for JS/TS, an
AST checker for Python — pytest has no stock lint for assertion counting).
**Why recorded:** so nobody "improves" G3 later by adding heuristic self-
computation detection. False rejections cost more trust than the misses cost
quality.

---

## D-008 — `SHIP_WITH_WATCH` is disabled until §15 Q17 is answered
**Spec:** §3.4 — only offer it if feature flags or staged rollout actually exist.
**Done:** `ship_with_watch_available: false` in `.qa/RISK-RULES.yaml`; G7 rejects
a report using the verdict while the flag is false.
**Why:** Nobody has confirmed rollout machinery exists. Made mechanical rather
than left to the marshal's judgement, because a verdict the organisation cannot
act on is worse than a HOLD.

---

## D-009 — The PR budget is scaled by risk band
**Spec:** §5 G6 sets a single per-PR cap, `<<$8>>`.
**Done:** `pr_budget_usd_by_band` in `.qa/RISK-RULES.yaml` — low $1, medium $8
(the spec's figure, kept as the default), high $25, critical $50. G6 reads the
band from `.qa/risk/<pr>.json`.
**Why:** The spec's own numbers contradict each other. §13 estimates a critical
PR at $25–50, but §5 G6 caps every PR at $8. Applied literally, the orchestrator
stops after `unit-smith` on every critical PR and the marshal reports LOW with
`budget_exhausted` — turning the *most* important reviews into the *least*
complete ones. Confirmed by running the orchestrator in dry-run mode against a
critical route: it halted before `flow-smith` at $6.10 of $8.
**Note:** the band caps are derived from §13's own placeholder estimates, so they
inherit its uncertainty. §12 Phase 3 requires re-baselining from measurements;
these numbers are the first thing that should change when real data exists.

---

## D-010 — An unconfigured QA workflow skips visibly instead of failing red
**Spec:** §7.4 requires an explicit decision for the fork-PR case, but says
nothing about the workflow simply not being configured.
**Done:** A `preflight` job checks whether `ANTHROPIC_API_KEY` is set. If not,
the agent jobs are skipped and a one-time PR comment says "QA not run (not
configured)" with the setup steps.
**Why:** Found by running the workflow against this PR — the secret was unset
and the job failed red. A QA system that turns a PR red because *it* is not
configured trains people to ignore its red, and §3.6 is explicit that the moment
red CI becomes ignorable, every other part of this system stops producing
anything. The absence of a report must be **visible** (§7.4's principle) without
being **blocking**.
**Note:** secrets are not readable in a job-level `if`, so the check runs in a
step and is published as a job output.

---

## D-011 — Two real workflow bugs found by running it
Both were mine, and both were the kind that fail quietly.

**Inter-job artifact passing.** The `confidence` job checks out fresh, so
`.qa/risk/<pr>.json` written by the `risk` job was never present. G6 reads the
band from that file, so every budget check silently fell back to `medium` — on a
critical PR that is a gate measuring the wrong thing while reporting success,
which is exactly what P5 exists to prevent. Fixed by uploading/downloading the
artifact **and** passing the band as `QA_BAND`, so the gate does not depend on a
file crossing a job boundary.

**Wrong default branch.** `QA_DEFAULT_BRANCH` used
`github.event.repository.default_branch`, which is whatever branch happens to be
the repository default — here still the feature branch, because the repository
was created empty and the first push set it. Now uses the PR's own base ref,
which is the only correct answer.

---

## D-012 — KNOWN ISSUE: the guard's self-protection is too broad
**Status:** open. Needs a human to apply, because the guard locks everyone —
including the orchestrator — out of the file that would fix it.

**Symptom.** Two rules protect the referee from being rewritten mid-run:

- `defaults.bash_deny` includes `\.qa/(policy\.yaml|gates/|RISK-RULES\.yaml)`,
  matched against the **whole Bash command string**.
- `defaults.write_deny_always` includes `.qa/policy.yaml`, `.qa/gates/**` and
  `.qa/RISK-RULES.yaml`, checked **before** the orchestrator is waved through.

So any Bash command that merely *mentions* one of those paths is refused, even
when it edits something else entirely — editing `README.md` with a heredoc that
happens to contain the string `.qa/RISK-RULES.yaml` is blocked. And a human
maintaining the kit in their own session cannot edit the gates or the risk rules
at all. Both were hit repeatedly while building `/qa-init`.

**A third false positive, and the most instructive one.** The snapshot rule
`(^|\s)(-u|--update-snapshot|...)(\s|$)` blocks **`git push -u origin <branch>`**,
where `-u` means "set upstream" and has nothing to do with snapshots. A bare
`-u` is far too generic to match on its own; it needs to be anchored to a test
runner, e.g. `(jest|vitest|pytest|playwright)\b[^|;]*\s-u(\s|$)`. Until then the
long form `git push --set-upstream` works.

This one matters more than the inconvenience suggests: a gate that fires on
unrelated commands trains people to route around it, and a gate people route
around is worse than no gate. Precision is not a nicety here — it is what keeps
the rule credible.

**Why it is wrong.** The threat being defended against is *an agent* rewriting
its own referee mid-run. A human session doing deliberate maintenance is not
that threat, and matching on a command's text rather than its target confuses
"mentions" with "modifies".

**The fix, for whoever applies it.** Split the rules by caller:

```yaml
defaults:
  bash_deny:              # everyone — snapshot laundering only (P8/G4)
    - <the --update-snapshot patterns>
  agent_bash_deny:        # agents only — editing the referee
    - '\.qa/(policy\.yaml|gates/|RISK-RULES\.yaml)'
  write_deny_always:      # everyone — the guard itself, so it cannot self-modify
    - ".qa/policy.yaml"
    - ".claude/hooks/**"
  agent_write_deny:       # agents only
    - ".qa/gates/**"
    - ".qa/RISK-RULES.yaml"
    - ".claude/qa-settings/**"
    - ".github/workflows/**"
```

and in `qa-guard.py`, evaluate the `agent_*` lists only when `agent_type` is
present. Keep the `write_deny_always` check on `.qa/policy.yaml` and
`.claude/hooks/**` ahead of the orchestrator return — the guard must never be
able to edit the guard.

**Deliberately not worked around.** Editing the policy from inside a session to
loosen the policy is precisely the move this design exists to prevent, so the
constraint was respected and the issue written up instead. Meanwhile `/qa-init`
writes `.qa/RISK-RULES.proposed.yaml` rather than the protected file, which is
better practice anyway: Phase 0 requires human sign-off on banding.
