#!/usr/bin/env bash
# G1 — fails-before / passes-after, three-state (spec §5 G1).
#
# A test written for a defect must fail on the base revision and pass with the
# fix. The subtlety the spec insists on: for NEW code the base revision has no
# such symbol, so the test file fails to *import* and the runner exits non-zero.
# A naive "exit code != 0 means it failed correctly" check therefore passes any
# test at all, including one with no assertions. That is a vacuous gate.
#
#   named assertion failure for this test  -> PASS
#   import/collection/compile error        -> INCONCLUSIVE (report N/A, lean on G2/G3)
#   test passes on base                    -> FAIL (it encodes the bug, not the requirement)
#
# Usage: g1-fails-before.sh <test-id> [<test-file>...]

QA_GATE_NAME=g1
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
qa_load_adapter
qa_need git

TEST_ID="${1:?usage: g1-fails-before.sh <test-id> [test-file...]}"; shift
TEST_FILES=("$@")

BASE_REF="${QA_BASE_REF:-origin/${QA_DEFAULT_BRANCH:-main}}"
BASE_SHA="$(git merge-base HEAD "$BASE_REF" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null || true)"
[[ -n "$BASE_SHA" ]] || qa_die "cannot resolve a base revision to test against"

WORK="$(mktemp -d -t g1-XXXXXX)"
cleanup() { git worktree remove --force "$WORK" >/dev/null 2>&1 || rm -rf "$WORK"; }
trap cleanup EXIT

qa_log "base revision: $BASE_SHA"
git worktree add --detach -q "$WORK" "$BASE_SHA" || qa_die "could not create base worktree"

# The test files themselves must come from HEAD — the whole point is to run the
# NEW test against the OLD source. Without this the base worktree simply has no
# such test and the gate measures nothing.
for f in "${TEST_FILES[@]}"; do
  [[ -f "$f" ]] || continue
  mkdir -p "$WORK/$(dirname "$f")"
  cp "$f" "$WORK/$f"
done

if declare -f qa_bootstrap_worktree >/dev/null; then
  qa_bootstrap_worktree "$WORK" || qa_log "bootstrap reported problems; continuing (results may be INCONCLUSIVE)"
fi

OUT="$WORK/.g1-output.txt"
( cd "$WORK" && qa_test_ids "$TEST_ID" ) > "$OUT" 2>&1
RC=$?

# Collection/import/compile failures. Deliberately generous: a false
# INCONCLUSIVE costs a weaker report, a false PASS corrupts the verdict.
COLLECTION_RX='(ModuleNotFoundError|ImportError|Cannot find module|Failed to resolve import|error TS[0-9]+|SyntaxError|collection error|ERROR collecting|No test files found|Cannot find name)'
# A genuine, named assertion failure for the test under test.
ASSERT_RX='(AssertionError|assert[[:space:]]|Expected|expect\(|FAILED|✕|✗|× )'

STATUS="INCONCLUSIVE"; REASON=""
if [[ $RC -eq 0 ]]; then
  STATUS="FAIL"
  REASON="test '$TEST_ID' PASSES on the base revision — it describes existing behaviour, not the defect. Reject and regenerate."
elif grep -Eq "$COLLECTION_RX" "$OUT"; then
  STATUS="INCONCLUSIVE"
  REASON="base revision could not build/collect the test (new symbol). Gate does not apply; report N/A and rely on G2/G3."
elif grep -Eq "$ASSERT_RX" "$OUT" && grep -q "$TEST_ID" "$OUT"; then
  STATUS="PASS"
  REASON="named assertion failure for '$TEST_ID' on the base revision."
else
  STATUS="INCONCLUSIVE"
  REASON="runner exited $RC without a recognisable assertion failure for '$TEST_ID'."
fi

qa_log "$STATUS — $REASON"
qa_emit_result g1 "$STATUS" "$(jq -nc --arg id "$TEST_ID" --arg r "$REASON" --arg b "$BASE_SHA" \
  --arg o "$(tail -40 "$OUT" | head -c 4000)" '{test_id:$id,reason:$r,base:$b,output_tail:$o}')"

case "$STATUS" in
  PASS)         exit "$QA_EXIT_PASS" ;;
  FAIL)         exit "$QA_EXIT_GATE_FAILED" ;;
  *)            exit "$QA_EXIT_INCONCLUSIVE" ;;
esac
