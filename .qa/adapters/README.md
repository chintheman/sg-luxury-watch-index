# Stack adapters

The gates in `.qa/gates/` are stack-agnostic. Everything stack-specific — how to
run the suite, how to run mutation testing, how to detect a vacuous test — lives
behind this adapter contract.

An adapter is a shell file that sets a handful of variables and defines a handful
of functions. `.qa/gates/lib.sh` sources exactly one of them, chosen by
`QA_ADAPTER` in `.qa/config.env` (or auto-detected by `detect.sh`).

This indirection is what lets Phase 1 finish before a target stack is chosen, and
what stops "the mutation command" from being copy-pasted into eight scripts.

## Contract

An adapter MUST define:

| Name | Kind | Meaning |
|---|---|---|
| `QA_ADAPTER_NAME` | var | Human-readable identifier, e.g. `node-vitest`. |
| `qa_test_all` | fn | Run the whole suite. Exit 0 iff green. |
| `qa_test_files <file>...` | fn | Run only the named test files. Exit 0 iff green. |
| `qa_test_ids <id>...` | fn | Run only tests whose name matches an oracle ID (`O1`, `I2`, `B1`). |
| `qa_mutation <src-file>...` | fn | Run mutation testing over the given source files. Must write normalised JSON to `$QA_MUTATION_JSON`. |
| `qa_vacuity <test-file>...` | fn | G3. Exit non-zero and print findings if any test is vacuous. |
| `qa_coverage` | fn | Emit coverage as a number 0–1 on stdout. Diagnostic only — never a gate (P3). |
| `qa_route_inventory` | fn | G8. Print one route per line as `METHOD /path`. May print nothing if the stack has no routes. |

An adapter MAY define `qa_bootstrap_worktree <dir>` (§7.3). If absent, worktree
isolation is disabled and writers are serialised — the §11 fallback.

### Normalised mutation JSON

`qa_mutation` must produce this shape, whatever the underlying tool emits:

```json
{
  "score": 0.71,
  "killed": 22,
  "survived": 9,
  "timeout": 1,
  "no_coverage": 3,
  "survivors": [
    { "file": "src/billing/coupon.ts", "line": 42,
      "mutator": "ConditionalExpression",
      "original": "if (total > 0)", "replacement": "if (true)" }
  ]
}
```

`survivors` is the field that matters: §3.3 feeds it back to `unit-smith` *as the
prompt*. A summary score with no survivor detail turns the mutation loop into a
progress bar.

`score` is computed over **killed / (killed + survived + timeout)**. Mutants with
no coverage are reported separately and excluded from the denominator, because a
file nothing exercises should show up as a blind spot in `risk-scout`, not as a
mutation-score failure that `unit-smith` cannot act on.

## Choosing an adapter

```bash
.qa/adapters/detect.sh          # prints the adapter it would pick, and why
echo 'QA_ADAPTER=node-vitest' >> .qa/config.env
```

## Writing a new one

Copy `custom.sh.template`. The template fails loudly on every function rather
than returning success, so an unfinished adapter cannot masquerade as a passing
gate — which is the failure mode this whole design exists to prevent (P5).
