#!/usr/bin/env bash
# Self-test for G1 (spec §12 Phase 1 acceptance).
#
# Phase 1 cannot be accepted on "the script exists". It is accepted when a test
# that passes on HEAD is rejected, and a collection error is reported
# INCONCLUSIVE rather than PASS. This builds a throwaway repo that exhibits all
# three states and asserts G1 classifies each correctly.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d -t g1-selftest-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

cd "$WORK"
git init -q . && git config user.email t@e.com && git config user.name t
mkdir -p src tests

# --- base revision: add() is buggy, and multiply() does not exist yet --------
cat > src/calc.py <<'PY'
def add(a, b):
    return a - b          # the defect under test
PY
cat > tests/test_base.py <<'PY'
from src.calc import add
def test_placeholder_O0():
    assert add(5, 0) == 5
PY
touch src/__init__.py tests/__init__.py
git add -A && git commit -qm base
BASE=$(git rev-parse HEAD)
git branch -f main "$BASE"

# --- HEAD: three new tests, one per expected G1 state ------------------------
cat > tests/test_g1_cases.py <<'PY'
from src.calc import add

def test_O1_add_returns_sum():
    """Real defect: fails on base with an assertion error. -> PASS"""
    assert add(2, 2) == 4

def test_O2_always_true():
    """Describes existing behaviour, not the defect. -> FAIL"""
    assert add(5, 0) == 5
PY
cat > tests/test_g1_newsymbol.py <<'PY'
from src.calc import multiply          # does not exist on base -> ImportError

def test_O3_multiply():
    """New code: base cannot even import it. -> INCONCLUSIVE"""
    assert multiply(3, 3) == 9
PY
git add -A && git commit -qm "add tests"

export QA_ROOT="$KIT" QA_ADAPTER=python-pytest QA_BASE_REF=main QA_PR=selftest
G1="$KIT/.qa/gates/g1-fails-before.sh"

fails=0
check() { # test-id  test-file  expected-exit  label
  local id="$1" file="$2" want="$3" label="$4"
  "$G1" "$id" "$file" >/dev/null 2>&1
  local got=$?
  if [[ "$got" == "$want" ]]; then
    printf '  ok   %-14s %s\n' "$id" "$label"
  else
    printf '  FAIL %-14s %s (expected exit %s, got %s)\n' "$id" "$label" "$want" "$got"
    fails=$((fails+1))
  fi
}

echo "=== G1 self-test ==="
check test_O1_add_returns_sum tests/test_g1_cases.py     0 "real defect -> PASS"
check test_O2_always_true     tests/test_g1_cases.py     1 "passes on base -> FAIL"
check test_O3_multiply        tests/test_g1_newsymbol.py 3 "new symbol -> INCONCLUSIVE"

if [[ $fails -eq 0 ]]; then echo "G1 self-test: all states correct"; exit 0
else echo "G1 self-test: $fails state(s) misclassified"; exit 1; fi
