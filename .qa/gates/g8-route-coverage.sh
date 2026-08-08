#!/usr/bin/env bash
# G8 — route coverage (spec §5 G8, §3.9).
# A new route without an authz-matrix row fails the build. Spec §3.9: "That
# check alone is worth the agent."
QA_GATE_NAME=g8
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
qa_load_adapter
MATRIX="$QA_ROOT/.qa/authz-matrix.yaml"

if [[ ! -f "$MATRIX" ]]; then
  qa_log "no authz-matrix.yaml yet — G8 is inactive until Phase 5 creates it"
  qa_emit_result g8 NOT_APPLICABLE '{"note":"authz-matrix.yaml does not exist yet"}'
  exit "$QA_EXIT_PASS"
fi

mapfile -t ROUTES < <(qa_route_inventory 2>/dev/null) || true
if [[ ${#ROUTES[@]} -eq 0 ]]; then
  qa_log "route inventory is empty — the adapter's qa_route_inventory is not implemented"
  qa_emit_result g8 MISCONFIGURED '{"note":"qa_route_inventory returned nothing"}'
  exit "$QA_EXIT_MISCONFIGURED"
fi

MISSING=()
for r in "${ROUTES[@]}"; do
  grep -qF -- "$r" "$MATRIX" || MISSING+=("$r")
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  qa_log "FAIL — ${#MISSING[@]} route(s) have no authz-matrix row:"
  printf '  %s\n' "${MISSING[@]}" >&2
  qa_emit_result g8 FAIL "$(printf '%s\n' "${MISSING[@]}" | jq -R . | jq -s '{missing_routes:.}')"
  exit "$QA_EXIT_GATE_FAILED"
fi
qa_log "PASS — all ${#ROUTES[@]} routes have matrix rows"
qa_emit_result g8 PASS "$(jq -nc --argjson n "${#ROUTES[@]}" '{routes:$n}')"
