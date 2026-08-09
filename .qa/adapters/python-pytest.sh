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

# mutmut 2 took `--paths-to-mutate` on the command line. mutmut 3 removed every
# scoping flag and reads `source_paths` / `only_mutate` from pyproject.toml or
# setup.cfg instead, then reports through `export-cicd-stats`. The two CLIs share
# no common invocation, so detect the major version rather than guessing.
qa_mutmut_major() {
  python3 - <<'PY' 2>/dev/null
import importlib.metadata as md
try:
    print(md.version("mutmut").split(".")[0])
except md.PackageNotFoundError:
    raise SystemExit(1)
PY
}

qa_mutation_error() {   # reason -> ungradeable result, never a pass
  python3 "$QA_ROOT/.qa/adapters/mutmut_normalise.py" --error "$1" > "$QA_MUTATION_JSON"
  echo "[g2] $1" >&2
  return 90
}

qa_mutation() {
  local files=("$@") major
  major="$(qa_mutmut_major)" || { qa_mutation_error "mutmut is not installed"; return 90; }

  if [[ "$major" -lt 3 ]]; then
    mutmut run --paths-to-mutate "$(IFS=,; echo "${files[*]}")" >&2 || true
    mutmut results --all true 2>/dev/null \
      | python3 "$QA_ROOT/.qa/adapters/mutmut_normalise.py" --stats /dev/null --results - \
      > "$QA_MUTATION_JSON"
    return 0
  fi

  # ---- mutmut 3: configuration file, not flags -----------------------------
  # Refuse to run rather than clobber a config the project already owns. A gate
  # that silently rewrites the repo's build config to measure it is not a gate.
  if [[ -f setup.cfg ]] && grep -q '^\[mutmut\]' setup.cfg 2>/dev/null; then
    qa_mutation_error "setup.cfg already has a [mutmut] section; scope G2 there and rerun"; return 90
  fi
  if [[ -f pyproject.toml ]] && grep -q '^\[tool\.mutmut\]' pyproject.toml 2>/dev/null; then
    qa_mutation_error "pyproject.toml already has [tool.mutmut]; scope G2 there and rerun"; return 90
  fi
  local restore=0
  [[ -f setup.cfg ]] && { cp setup.cfg "$QA_ROOT/.qa/.setup.cfg.qa-backup"; restore=1; }

  # source_paths must cover every package the SUITE imports, not just the files
  # being mutated. mutmut copies source_paths into mutants/ and runs pytest from
  # there; tests/conftest.py then puts <mutants>/ and <mutants>/parser on
  # sys.path. Omit parser/ and collection dies with ModuleNotFoundError before a
  # single mutant runs — which reads as "mutation is impossible here" when the
  # real cause is a one-line config gap. only_mutate keeps the actual scope tight.
  #
  # configparser continuation lines: first value on the key's line, the rest
  # indented. Built in python because the delimiter is "\n    " — `paste -sd`
  # cycles SINGLE characters and silently mangles any multi-file list.
  python3 - "${QA_MUTATION_SOURCE_PATHS:-}" "$@" >> setup.cfg <<'PY'
import os, sys

override, files = sys.argv[1], sys.argv[2:]
SKIP = {"tests", "test", "migrations", "ops", "web", "scripts", "mutants",
        "node_modules", "docs"}

if override:
    dirs = sorted({d for d in override.split(",") if d})
else:
    dirs = {os.path.dirname(f) or "." for f in files}
    # Sibling top-level packages the suite imports. Cheap to include, and their
    # absence is a hard collection failure rather than a degraded measurement.
    for entry in sorted(os.listdir(".")):
        if not os.path.isdir(entry) or entry.startswith(".") or entry in SKIP:
            continue
        if any(n.endswith(".py") for n in os.listdir(entry)):
            dirs.add(entry)
    dirs = sorted(dirs)

def block(key, values):
    return key + "=" + "\n    ".join(values)

print("[mutmut]")
print(block("source_paths", dirs))
print(block("only_mutate", files))
PY

  local log="$QA_ROOT/.qa/metrics/mutmut-run.log"
  mkdir -p "$(dirname "$log")"
  mutmut run >"$log" 2>&1 || true
  tr '\r' '\n' < "$log" | grep -vE "Generating mutants|Running stats" | tail -30 >&2

  # Two failure modes this repository layout actually hits. Both must report a
  # reason, not an empty file — "no report" and "nothing survived" are the same
  # bytes on disk otherwise.
  local reason=""
  if grep -q "none match any mutant key" "$log"; then
    reason="mutmut cannot map mutants to modules: tests import these modules unqualified (via tests/conftest.py sys.path injection) while mutmut derives keys from file paths. Switch the suite to fully-qualified imports to enable G2."
  elif grep -qE "failed to collect stats|runner returned [1-9]" "$log"; then
    reason="the suite is not green inside mutmut's mutants/ sandbox, so no baseline exists to mutate against. Usually a 'try: from X import' fallback resolving differently under the sandbox."
  fi

  if [[ -z "$reason" ]]; then
    mutmut export-cicd-stats >/dev/null 2>&1 || mutmut export_cicd_stats >/dev/null 2>&1 || true
    if [[ -s mutants/mutmut-cicd-stats.json ]]; then
      mutmut results 2>/dev/null \
        | python3 "$QA_ROOT/.qa/adapters/mutmut_normalise.py" \
            --stats mutants/mutmut-cicd-stats.json --results - > "$QA_MUTATION_JSON"
    else
      reason="mutmut run produced no stats file; see $log"
    fi
  fi
  [[ -n "$reason" ]] && qa_mutation_error "$reason"

  # Always restore: leaving a [mutmut] section behind changes how the next
  # developer's `mutmut run` behaves, silently.
  if [[ $restore -eq 1 ]]; then
    mv "$QA_ROOT/.qa/.setup.cfg.qa-backup" setup.cfg
  else
    rm -f setup.cfg
  fi
  rm -rf mutants
  [[ -n "$reason" ]] && return 90
  return 0
}

qa_vacuity() { python3 "$QA_ROOT/.qa/gates/py_vacuity.py" "$@"; }

qa_coverage() {
  # Via qa_pytest, not `python3 -m pytest`: the same uv/pipx-installed-pytest
  # problem this file opens by describing applies here too.
  PYTHONPATH="${PYTHONPATH:-}:$PWD" qa_pytest --cov --cov-report=json >/dev/null 2>&1 || true
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
