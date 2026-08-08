---
description: Run one time-boxed exploratory testing session against local dev.
argument-hint: "<charter>"
---
Run `prober` with the charter: $ARGUMENTS

Load the `qa-charters` and `qa-repro` skills.

If the charter names an API surface with an OpenAPI schema, drive **Schemathesis**
rather than inventing payloads — the fuzzer generates better inputs than you can,
and your value is triage and minimisation.

Write a session sheet to `.qa/sessions/<date>-<n>.md` with every field filled in,
including `CONFIDENCE` in prose and `ISSUES` for anything that blocked you.

Minimise every finding to three steps or fewer before writing it up.
