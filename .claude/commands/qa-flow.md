---
description: Plan and generate an end-to-end browser test for a user journey.
argument-hint: "<journey description>"
---
Run `flow-smith` for the journey: $ARGUMENTS

Use Playwright MCP with `--isolated --headless --save-trace`. Always isolated —
leaked session state manufactures phantom flakes that cost days to diagnose.

1. **plan** — explore the running app, write the journey to `.qa/plans/`.
2. **generate** — turn the plan into a spec, verifying **every selector and
   assertion against the live app as you write it**. An unverified assertion is
   a guess.
3. Run it three times. If it is not stable, fix it now, not later.

Cap: 5 e2e tests per PR, high-risk journeys only. If you want a sixth, the
behaviour probably belongs a layer down.
