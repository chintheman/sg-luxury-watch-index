---
description: Propose a minimal source fix for a confirmed bug that already has a red test.
argument-hint: <bug-id>
---
Run `patch-smith` for: $ARGUMENTS

**Precondition:** a confirmed, reproducible, red test must already exist. If it
does not, stop and say so — write the failing test first (`/qa-test`). You are
never asked whether a bug exists, only to make a red test green.

1. Read `.qa/bugs/<id>.md` and run the failing test to see it red.
2. Derive the fix from the test and the code. No `git log`, no upstream lookup —
   both are blocked, and retrieving a fix is not the same as understanding one.
3. Make the smallest change that works. If it needs refactoring, stop and write
   a proposal instead.
4. Run the full suite **once** at the end.

Report the failing output before, the passing output after, and root-cause
reasoning — why the code was wrong, not just what you changed.

If you believe the test is wrong, write `.qa/disputes/<id>.md` citing the oracle
proposition it misencodes, and stop.
