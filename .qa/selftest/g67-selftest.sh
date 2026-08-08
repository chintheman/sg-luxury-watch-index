#!/usr/bin/env bash
# G6 must stop BEFORE dispatch; G7 must reject an incomplete oracle or report.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export QA_ROOT="$KIT" QA_PR="selftest-$$"
fails=0
L="$KIT/.qa/metrics/cost/${QA_PR}.json"
trap 'rm -f "$L" "$KIT/.qa/metrics/cost/${QA_PR}.stop.json" "$KIT/.qa/oracles/${QA_PR}.md" "$KIT/.qa/reports/${QA_PR}.json" "$KIT"/.qa/metrics/gates/*"${QA_PR}"*.json' EXIT

"$KIT/.qa/gates/g6-budget.sh" record a 7.32 >/dev/null 2>&1
if "$KIT/.qa/gates/g6-budget.sh" check flow-smith 2.00 >/dev/null 2>&1; then
  printf '  FAIL  G6 allowed a dispatch that would breach the cap\n'; fails=$((fails+1))
else printf '  ok    G6 stops before the breaching dispatch\n'; fi

printf '# o\n## Propositions\n- [O1] x\n  - source: docs/a.md\n' > "$KIT/.qa/oracles/${QA_PR}.md"
if "$KIT/.qa/gates/g7-completeness.sh" oracle high "$KIT/.qa/oracles/${QA_PR}.md" >/dev/null 2>&1; then
  printf '  FAIL  G7 accepted 1 proposition on a high PR\n'; fails=$((fails+1))
else printf '  ok    G7 rejects an under-populated oracle\n'; fi

jq -n '{verdict:"SHIP",untested:[],evidence:{oracle_propositions:3,propositions_covered_by_tests:3}}' > "$KIT/.qa/reports/${QA_PR}.json"
if "$KIT/.qa/gates/g7-completeness.sh" marshal critical "$KIT/.qa/reports/${QA_PR}.json" >/dev/null 2>&1; then
  printf '  FAIL  G7 accepted an empty untested on a critical PR\n'; fails=$((fails+1))
else printf '  ok    G7 rejects an empty untested list\n'; fi
# SHIP_WITH_WATCH must be refused when a rollback cannot undo the change.
mkdir -p "$KIT/.qa/risk"
jq -n '{changed_files:["db/migrations/0042.sql"]}' > "$KIT/.qa/risk/${QA_PR}.json"
jq -n '{verdict:"SHIP_WITH_WATCH",untested:["x"],evidence:{oracle_propositions:1,propositions_covered_by_tests:1}}' > "$KIT/.qa/reports/${QA_PR}.json"
if "$KIT/.qa/gates/g7-completeness.sh" marshal high "$KIT/.qa/reports/${QA_PR}.json" >/dev/null 2>&1; then
  printf '  FAIL  G7 allowed SHIP_WITH_WATCH on an irreversible migration\n'; fails=$((fails+1))
else printf '  ok    G7 refuses SHIP_WITH_WATCH when rollback cannot undo it\n'; fi

jq -n '{changed_files:["src/api/cart.ts"]}' > "$KIT/.qa/risk/${QA_PR}.json"
if "$KIT/.qa/gates/g7-completeness.sh" marshal high "$KIT/.qa/reports/${QA_PR}.json" >/dev/null 2>&1; then
  printf '  ok    G7 allows SHIP_WITH_WATCH on a rollback-safe change\n'
else printf '  FAIL  G7 wrongly refused a rollback-safe SHIP_WITH_WATCH\n'; fails=$((fails+1)); fi
rm -f "$KIT/.qa/risk/${QA_PR}.json"

exit $fails
