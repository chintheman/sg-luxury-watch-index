#!/usr/bin/env bash
# G3 — vacuity check (spec §5 G3). Delegates to the adapter's per-language lint.
QA_GATE_NAME=g3
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
qa_load_adapter

mapfile -t FILES < <(if [[ $# -gt 0 ]]; then printf '%s\n' "$@"; else
  qa_changed_files | grep -Ei '(^|/)(tests?|spec)/|\.(test|spec)\.[jt]sx?$|(^|/)test_.*\.py$|_test\.py$'
fi)

if [[ ${#FILES[@]} -eq 0 ]]; then
  # No test files changed is a legitimate pass, but say so out loud: a silent
  # "0 findings" reads identically to "checked everything and found nothing".
  qa_log "no changed test files to check"
  qa_emit_result g3 PASS '{"files_checked":0,"note":"no test files in diff"}'
  exit "$QA_EXIT_PASS"
fi

qa_log "checking ${#FILES[@]} test file(s)"
OUT="$(qa_vacuity "${FILES[@]}" 2>&1)"; RC=$?
echo "$OUT"

if [[ $RC -eq 0 ]]; then
  qa_emit_result g3 PASS "$(jq -nc --argjson n "${#FILES[@]}" '{files_checked:$n}')"
  exit "$QA_EXIT_PASS"
elif [[ $RC -ge 90 ]]; then
  qa_log "vacuity linter is not configured for this stack — this is a misconfiguration, not a pass"
  qa_emit_result g3 MISCONFIGURED "$(jq -nc --arg o "$OUT" '{error:$o}')"
  exit "$QA_EXIT_MISCONFIGURED"
else
  qa_emit_result g3 FAIL "$(jq -nc --argjson n "${#FILES[@]}" --arg o "$(head -c 4000 <<<"$OUT")" \
    '{files_checked:$n,findings:$o}')"
  exit "$QA_EXIT_GATE_FAILED"
fi
