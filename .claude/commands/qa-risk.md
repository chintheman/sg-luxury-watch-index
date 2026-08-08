---
description: Band the current uncommitted changes by risk and print the routing. Free recon before you push.
---
Run `risk-scout` against the working tree.

1. Read `.qa/RISK-RULES.yaml` and `.qa/metrics/history.json`.
2. Get the diff: `git diff HEAD` plus `git status --short` for untracked files.
3. Apply the banding rules top to bottom — first match wins — then escalators.
4. Print: band, matched rule, escalators applied, blind spots (changed code with
   no covering test), the agents that would run, and the estimated cost.
5. Write `.qa/risk/local.json`.

Do not write anything else. This is a read-and-report command; it should cost
cents and finish in under a minute.
