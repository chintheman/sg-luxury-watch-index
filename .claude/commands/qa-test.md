---
description: Run the full mutation loop on one file — write tests, mutate, kill survivors, repeat.
argument-hint: <path to source file>
---
Run `unit-smith` on: $ARGUMENTS

1. Read the oracle file for this change if one exists; if not, say so — tests
   written without an oracle risk encoding current behaviour as correct, and the
   report must record that.
2. Load the `qa-conventions` and `qa-mutation` skills.
3. Write tests named after their oracle proposition IDs.
4. Run the mutation loop: test → mutate → read survivors → kill → repeat.
5. Stop when survivors are killed or turns run out.

Report honestly at the end: mutation score before and after, surviving mutants
with a note on which are genuinely equivalent, and propositions left uncovered.
**Do not pad with weak tests to look finished** — a padded result corrupts the
verdict, which is the only thing this system produces.
