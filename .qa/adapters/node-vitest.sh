#!/usr/bin/env bash
# Adapter: Node/TypeScript with vitest + Stryker.
QA_ADAPTER_NAME="node-vitest"

QA_PKG_RUN="${QA_PKG_RUN:-npx}"

qa_test_all()   { $QA_PKG_RUN vitest run --reporter=basic; }
qa_test_files() { $QA_PKG_RUN vitest run --reporter=basic "$@"; }

# Oracle IDs are encoded in test names (§3.3), so selection is by name pattern.
# Anchored with a word boundary so O1 does not also select O10.
qa_test_ids() {
  local pat; pat="$(printf '%s|' "$@")"; pat="${pat%|}"
  $QA_PKG_RUN vitest run --reporter=basic -t "\\b(${pat})\\b"
}

# Stryker emits a rich JSON report; we normalise it to the adapter contract so
# the gate and unit-smith never learn Stryker's schema.
qa_mutation() {
  local files=("$@") tmp; tmp="$(mktemp -d)"
  $QA_PKG_RUN stryker run \
    --mutate "$(IFS=,; echo "${files[*]}")" \
    --reporters json \
    --jsonReporter.fileName "$tmp/mutation.json" \
    --coverageAnalysis perTest >&2 || true   # non-zero on threshold breach; the gate decides, not Stryker

  [[ -s "$tmp/mutation.json" ]] || { echo "stryker produced no report" >&2; return 91; }

  jq '
    [ .files | to_entries[] as $f | $f.value.mutants[] | {file:$f.key} + . ] as $m
    | { killed:      ($m | map(select(.status=="Killed"))      | length),
        survived:    ($m | map(select(.status=="Survived"))    | length),
        timeout:     ($m | map(select(.status=="Timeout"))     | length),
        no_coverage: ($m | map(select(.status=="NoCoverage"))  | length) }
    | . + { score: ( (.killed + .survived + .timeout) as $d
                     | if $d == 0 then null else (.killed / $d) end ) }
    | . + { survivors: ( $m | map(select(.status=="Survived"))
              | map({file, line: (.location.start.line),
                     mutator: .mutatorName,
                     original: (.description // ""),
                     replacement: (.replacement // "")}) ) }
  ' "$tmp/mutation.json" > "$QA_MUTATION_JSON"
  rm -rf "$tmp"
}

# G3 as a lint rule, per the spec's instruction not to build a bespoke AST tool.
# These rules come from eslint-plugin-vitest / eslint-plugin-jest.
qa_vacuity() {
  $QA_PKG_RUN eslint --no-eslintrc \
    --config .qa/gates/eslint-vacuity.cjs \
    --format stylish "$@"
}

qa_coverage() {
  $QA_PKG_RUN vitest run --coverage --coverage.reporter=json-summary >/dev/null 2>&1 || true
  jq -r '(.total.lines.pct // 0) / 100' coverage/coverage-summary.json 2>/dev/null || echo 0
}

qa_route_inventory() {
  # Best-effort: prefer a generated OpenAPI document over source scraping,
  # because scraping decorators is how a route inventory silently goes stale.
  if [[ -f openapi.json ]]; then
    jq -r '.paths | to_entries[] | .key as $p | .value | keys[] | (ascii_upcase + " " + $p)' openapi.json
  else
    echo "no openapi.json; implement qa_route_inventory for this repo" >&2; return 92
  fi
}

qa_bootstrap_worktree() {
  local wt="$1"
  # node_modules is symlinked rather than reinstalled: a fresh install per
  # worktree is the single biggest cost in the mutation loop (§7.3).
  [[ -d node_modules ]] && ln -sfn "$PWD/node_modules" "$wt/node_modules"
  [[ -f .env.test ]] && cp .env.test "$wt/.env.test"
  # Unique DB per worktree; parallel agents sharing one database is a flake factory.
  echo "QA_DB_SCHEMA=qa_$(basename "$wt")" >> "$wt/.env.test"
  ( cd "$wt" && qa_test_all >/dev/null 2>&1 ) || {
    echo "bootstrap verification failed: suite is not green in $wt" >&2; return 93; }
}
