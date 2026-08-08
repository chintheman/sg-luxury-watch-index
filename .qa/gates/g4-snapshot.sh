#!/usr/bin/env bash
# G4 — no snapshot laundering (spec §5 G4, P8).
#
# The command-level ban lives in the G5 guard (denied for every agent, always).
# This CI-side check catches the other half: snapshot FILES changed in an agent
# PR, however they got there. Snapshots are not blocked — they are labelled for
# a human, because "the snapshot changed and the agent said that's fine" is not
# evidence.
QA_GATE_NAME=g4
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

mapfile -t SNAPS < <(qa_changed_files | grep -Ei '(__snapshots__/|\.snap$|\.ambr$|\.approved\.|/snapshots?/)' || true)

if [[ ${#SNAPS[@]} -eq 0 ]]; then
  qa_emit_result g4 PASS '{"snapshot_files_changed":0}'
  exit "$QA_EXIT_PASS"
fi

qa_log "${#SNAPS[@]} snapshot file(s) changed — needs human sign-off:"
printf '  %s\n' "${SNAPS[@]}" >&2
qa_emit_result g4 NEEDS_HUMAN "$(printf '%s\n' "${SNAPS[@]}" | jq -R . | jq -s \
  '{snapshot_files_changed:length,files:.,label:"needs-human-snapshot-review"}')"
# Deliberately exit 0: this is a labelling gate, not a blocking one. It fails the
# build only via the required-label check in CI, which a human can satisfy.
echo "needs-human-snapshot-review" > "$QA_ROOT/.qa/metrics/g4-label.txt"
exit "$QA_EXIT_PASS"
