#!/usr/bin/env bash
# Adapter: Python with pytest + mutmut.
QA_ADAPTER_NAME="python-pytest"

# Resolve a working pytest rather than assuming `python3 -m pytest`. A pytest
# installed by uv/pipx lives in its own venv and is importable only by that
# venv's interpreter, so the module form fails while the console script works.
# Getting this wrong makes every test run look like a collection error, which
# G1 then reports as INCONCLUSIVE — a gate silently measuring nothing.
qa_pytest() {
  if [[ -z "${QA_PYTEST_CMD:-}" ]]; then
    if python3 -c "import pytest" >/dev/null 2>&1; then
      QA_PYTEST_CMD="python3 -m pytest"
    elif command -v pytest >/dev/null 2>&1; then
      QA_PYTEST_CMD="pytest"
    else
      echo "no pytest available (tried 'python3 -m pytest' and 'pytest')" >&2
      return 90
    fi
  fi
  # rootdir on sys.path so `from src... import` works without an installed package.
  $QA_PYTEST_CMD -p no:cacheprovider --rootdir . "$@"
}

qa_test_all()   { PYTHONPATH="${PYTHONPATH:-}:$PWD" qa_pytest -q; }
qa_test_files() { PYTHONPATH="${PYTHONPATH:-}:$PWD" qa_pytest -q "$@"; }

# Verbose on purpose: G1 must be able to find the specific test ID in the
# output to distinguish a named assertion failure from generic noise.
qa_test_ids()   {
  local pat; pat="$(printf '%s or ' "$@")"
  PYTHONPATH="${PYTHONPATH:-}:$PWD" qa_pytest -v -k "${pat% or }"
}

qa_mutation() {
  local files=("$@")
  # mutmut writes to its own cache; we ask for JUnit-ish results and normalise.
  mutmut run --paths-to-mutate "$(IFS=,; echo "${files[*]}")" >&2 || true
  mutmut results --all true 2>/dev/null | python3 "$QA_ROOT/.qa/gates/mutmut_normalise.py" > "$QA_MUTATION_JSON"
}

qa_vacuity() { python3 "$QA_ROOT/.qa/gates/py_vacuity.py" "$@"; }

qa_coverage() {
  python3 -m pytest -q --cov --cov-report=json >/dev/null 2>&1 || true
  python3 -c "import json;print(json.load(open('coverage.json'))['totals']['percent_covered']/100)" 2>/dev/null || echo 0
}

qa_route_inventory() {
  if [[ -f openapi.json ]]; then
    jq -r '.paths | to_entries[] | .key as $p | .value | keys[] | (ascii_upcase + " " + $p)' openapi.json
  else
    echo "no openapi.json; implement qa_route_inventory for this repo" >&2; return 92
  fi
}

qa_bootstrap_worktree() {
  local wt="$1"
  [[ -n "${VIRTUAL_ENV:-}" ]] && ln -sfn "$VIRTUAL_ENV" "$wt/.venv"
  [[ -f .env.test ]] && cp .env.test "$wt/.env.test"
  echo "QA_DB_SCHEMA=qa_$(basename "$wt")" >> "$wt/.env.test"
  ( cd "$wt" && qa_test_all >/dev/null 2>&1 ) || {
    echo "bootstrap verification failed: suite is not green in $wt" >&2; return 93; }
}
