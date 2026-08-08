---
description: Produce an oracle file from a ticket, before the code is written. The highest-value habit in the system.
argument-hint: <issue-id or path to ticket>
---
Run `spec-oracle` for: $ARGUMENTS

**Run this BEFORE writing the implementation.** It is a spec review that catches
ambiguity while it is still cheap to resolve — an ambiguity found now costs a
conversation, the same ambiguity found after merge costs an incident.

Use the `spec-oracle` agent so its blindness rules apply. Do not read the
implementation, the diff, or the changed-file list even if it exists.

Output `.qa/oracles/<id>.md` in the §3.2 format: Propositions with confidence and
source citations, Invariants, Boundaries, and Ambiguities.

Then print the **Ambiguities** section prominently. That list is the point of
running this early — take it to whoever owns the requirement.
