#!/usr/bin/env bash
# Run every gate self-test. This is the Phase 1 acceptance check (spec §12).
#
# Run it on first install against the real stack too: a gate that passes here
# and silently stops measuring on your repo is the failure mode that matters.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(cd "$HERE/../.." && pwd)"
fails=0

run() { # label script...
  local label="$1"; shift
  echo; echo "############ $label ############"
  if "$@"; then echo "-> OK"; else echo "-> FAILED"; fails=$((fails+1)); fi
}

run "G5 separation-of-duties guard" bash "$HERE/guard-selftest.sh"
run "G1 fails-before three-state"   bash "$HERE/g1-selftest.sh"
run "G3 vacuity detection"          bash "$HERE/g3-selftest.sh"
run "G6/G7 gate behaviour"          bash "$HERE/g67-selftest.sh"
run "agents/ mirrors .claude/agents/" bash "$KIT/scripts/qa-sync-agents.sh" --check

echo
if [[ $fails -eq 0 ]]; then
  echo "ALL SELF-TESTS PASSED"
else
  echo "$fails self-test group(s) FAILED"
fi
exit $fails
