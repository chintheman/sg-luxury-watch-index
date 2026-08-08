#!/usr/bin/env bash
# G2 — mutation gate: scoped, capped, run once (spec §5 G2).
#
# Three properties the spec insists on, each defeating a specific failure:
#   scoped  — only files matching mutation_paths. Presentation components make
#             overwhelmingly equivalent mutants; chasing them burns the whole
#             turn budget on junk DOM assertions.
#   capped  — a hard wall-clock limit. Mutation cost is mutants x suite time;
#             150 mutants on a 3-minute suite is hours.
#   once    — the blocking evaluation is a CI step after the agent, not a check
#             on every Stop attempt.
#
# Coverage may be reported here. Coverage is never a gate (P3).
QA_GATE_NAME=g2
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
qa_load_adapter
qa_need jq

# `timeout` needs a real process to kill, but qa_mutation is a shell function
# that exists only in this shell. Re-enter this script in child mode so the
# wall-clock cap wraps something killable.
export QA_MUTATION_JSON="${QA_MUTATION_JSON:-$QA_ROOT/.qa/metrics/mutation.json}"
if [[ "${QA_G2_CHILD:-}" == "1" ]]; then
  qa_mutation "$@"
  exit $?
fi

THRESHOLD="${QA_MUTATION_THRESHOLD:-0.60}"
CAP="${QA_MUTATION_TIMEOUT_SECONDS:-900}"
export QA_MUTATION_JSON="${QA_MUTATION_JSON:-$QA_ROOT/.qa/metrics/mutation.json}"
mkdir -p "$(dirname "$QA_MUTATION_JSON")"

mapfile -t ALL < <(if [[ $# -gt 0 ]]; then printf '%s\n' "$@"; else qa_changed_files; fi)
mapfile -t SCOPED < <(printf '%s\n' "${ALL[@]}" | qa_filter_mutation_paths)
EXEMPT=$(( ${#ALL[@]} - ${#SCOPED[@]} ))

if [[ ${#SCOPED[@]} -eq 0 ]]; then
  # Not a pass by default: say loudly that the gate did not apply, so the
  # marshal can put it in `untested` rather than imply it was measured.
  qa_log "no changed files are in mutation_paths; gate does not apply"
  qa_emit_result g2 NOT_APPLICABLE "$(jq -nc --argjson e "$EXEMPT" \
    '{scoped_files:0,exempt_files:$e,note:"no changed file is in mutation_paths"}')"
  exit "$QA_EXIT_PASS"
fi

qa_log "mutating ${#SCOPED[@]} file(s); ${EXEMPT} exempt by policy; cap ${CAP}s; threshold $THRESHOLD"

START=$(date +%s)
QA_G2_CHILD=1 timeout --signal=TERM "$CAP" "$0" "${SCOPED[@]}"
RC=$?
ELAPSED=$(( $(date +%s) - START ))

if [[ $RC -eq 124 ]]; then
  qa_log "mutation exceeded the ${CAP}s wall-clock cap"
  qa_emit_result g2 TIMEOUT "$(jq -nc --argjson s "${#SCOPED[@]}" --argjson e "$ELAPSED" --argjson c "$CAP" \
    '{scoped_files:$s,elapsed_seconds:$e,cap_seconds:$c,
      note:"cap hit — narrow mutation_paths or enable per-test coverage filtering"}')"
  exit "$QA_EXIT_INCONCLUSIVE"
fi

if [[ ! -s "$QA_MUTATION_JSON" ]]; then
  qa_log "mutation tool produced no report — treating as misconfiguration, not a pass"
  qa_emit_result g2 MISCONFIGURED '{"note":"no mutation report produced"}'
  exit "$QA_EXIT_MISCONFIGURED"
fi

SCORE=$(jq -r '.score // "null"' "$QA_MUTATION_JSON")
if [[ "$SCORE" == "null" ]]; then
  qa_log "no gradeable mutants (every mutant was uncovered or the tool found none)"
  qa_emit_result g2 INCONCLUSIVE "$(cat "$QA_MUTATION_JSON")"
  exit "$QA_EXIT_INCONCLUSIVE"
fi

PASSED=$(jq -n --argjson s "$SCORE" --argjson t "$THRESHOLD" '$s >= $t')
EXTRA=$(jq --argjson t "$THRESHOLD" --argjson e "$EXEMPT" --argjson el "$ELAPSED" \
  '{score,killed,survived,timeout,no_coverage,threshold:$t,exempt_files:$e,elapsed_seconds:$el,
    survivors:(.survivors[0:40])}' "$QA_MUTATION_JSON")

if [[ "$PASSED" == "true" ]]; then
  qa_log "PASS — score $SCORE >= $THRESHOLD (${ELAPSED}s)"
  qa_emit_result g2 PASS "$EXTRA"
  exit "$QA_EXIT_PASS"
fi

qa_log "FAIL — score $SCORE < $THRESHOLD. Surviving mutants follow; feed them back to unit-smith."
jq -r '.survivors[] | "  \(.file):\(.line)  \(.mutator)  \(.original) -> \(.replacement)"' \
  "$QA_MUTATION_JSON" 2>/dev/null | head -40 >&2
qa_emit_result g2 FAIL "$EXTRA"
exit "$QA_EXIT_GATE_FAILED"
