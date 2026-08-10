#!/usr/bin/env bash
# G3 must reject each vacuous pattern and leave a sound test alone.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX="$KIT/.qa/fixtures/python/test_vacuity_cases.py"
OUT="$(python3 "$KIT/.qa/gates/py_vacuity.py" "$FIX" 2>&1)"; rc=$?
fails=0
for want in NO_ASSERTION MOCK_ONLY TAUTOLOGY SKIPPED; do
  if grep -q "\[$want\]" <<<"$OUT"; then printf '  ok    detects %s\n' "$want"
  else printf '  FAIL  missed %s\n' "$want"; fails=$((fails+1)); fi
done
if grep -q 'test_genuinely_fine' <<<"$OUT"; then
  printf '  FAIL  false positive on a sound test\n'; fails=$((fails+1))
else printf '  ok    no false positive on the sound test\n'; fi
[[ $rc -ne 0 ]] || { printf '  FAIL  exit code was 0 despite findings\n'; fails=$((fails+1)); }

# An unreadable input must be reported, and must not stop the scan. Only
# SyntaxError was caught, so a missing path raised FileNotFoundError and killed
# the process — every file after it went unchecked while the exit code still
# looked like an ordinary vacuity failure.
MISSING="$KIT/.qa/fixtures/python/__no_such_file__.py"
OUT2="$(python3 "$KIT/.qa/gates/py_vacuity.py" "$MISSING" "$FIX" 2>&1)"
if grep -q '\[UNREADABLE\]' <<<"$OUT2"; then printf '  ok    reports an unreadable input\n'
else printf '  FAIL  missed UNREADABLE on a missing file\n'; fails=$((fails+1)); fi
if grep -q '\[NO_ASSERTION\]' <<<"$OUT2"; then printf '  ok    keeps scanning past an unreadable input\n'
else printf '  FAIL  stopped scanning after the unreadable input\n'; fails=$((fails+1)); fi

exit $fails
