---
description: Produce a Confidence Report for the current branch before you push.
---
Run `release-marshal` against the current branch.

Read every `.qa/` artifact for this change plus gate results in
`.qa/metrics/gates/`. Emit `.qa/reports/local.md` and `.json` in the §3.4 format.

Then print the verdict, the confidence, and **the full `untested` list**.

`untested` is the part worth reading. If you cannot name what was not tested,
the report is not finished — say that rather than emitting a clean-looking
verdict you do not believe.
