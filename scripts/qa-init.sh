#!/usr/bin/env bash
# qa-init — read the repository and work out what the QA team needs.
#
# This is the deterministic half of the "lazy button". It answers every recon
# question (spec §15) that can be answered by looking at files, and writes the
# results to .qa/INIT-REPORT.md and .qa/init-report.json.
#
# It deliberately does NOT guess the two questions that need a human (§15 Q17
# and Q20) and does NOT silently overwrite risk rules. A setup script that
# invents a risk model is worse than no setup script: it produces confident
# banding nobody has agreed to, which is exactly the numerology §16 cut.
#
# Usage: scripts/qa-init.sh [--time-suite]
#   --time-suite   actually run the test suite once to measure wall-clock.
#                  Off by default because it can take minutes.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TIME_SUITE=0
[[ "${1:-}" == "--time-suite" ]] && TIME_SUITE=1

J="$ROOT/.qa/init-report.json"
M="$ROOT/.qa/INIT-REPORT.md"
mkdir -p "$ROOT/.qa"

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- prerequisites --------------------------------------------------------
MISSING=()
for t in git python3 jq; do have "$t" || MISSING+=("$t"); done
python3 -c "import yaml" 2>/dev/null || MISSING+=("python3-yaml (pip install pyyaml)")
# macOS ships bash 3.2 (no mapfile) and no GNU timeout. The gates shim around
# both, but flag it so a failure later is recognisable rather than mysterious.
BASH_MAJOR="${BASH_VERSINFO[0]:-0}"
PORTABILITY=""
[[ "$BASH_MAJOR" -lt 4 ]] && PORTABILITY="bash $BASH_MAJOR (pre-4); mapfile shimmed"
have timeout || PORTABILITY="${PORTABILITY:+$PORTABILITY; }no GNU timeout (brew install coreutils)"

# --- stack ----------------------------------------------------------------
ADAPTER="$("$ROOT/.qa/adapters/detect.sh" 2>/dev/null | cut -f1)"
ADAPTER_WHY="$("$ROOT/.qa/adapters/detect.sh" 2>/dev/null | cut -f2)"

TEST_CMD=""; PROP_LIB=""; MUT_TOOL=""; PKG_MGR=""
if [[ -f package.json ]]; then
  PKG_MGR="npm"
  [[ -f pnpm-lock.yaml ]] && PKG_MGR="pnpm"
  [[ -f yarn.lock ]] && PKG_MGR="yarn"
  TEST_CMD="$(jq -r '.scripts.test // ""' package.json 2>/dev/null)"
  dep() { jq -e --arg d "$1" '((.dependencies//{})+(.devDependencies//{}))|has($d)' package.json >/dev/null 2>&1; }
  dep fast-check && PROP_LIB="fast-check"
  dep @stryker-mutator/core && MUT_TOOL="stryker"
elif [[ -f pyproject.toml || -f setup.cfg || -f requirements.txt ]]; then
  PKG_MGR="pip"
  TEST_CMD="pytest"
  grep -rqi 'hypothesis' pyproject.toml requirements.txt setup.cfg 2>/dev/null && PROP_LIB="hypothesis"
  grep -rqi 'mutmut' pyproject.toml requirements.txt setup.cfg 2>/dev/null && MUT_TOOL="mutmut"
fi

# --- test inventory -------------------------------------------------------
count() { find . -path ./node_modules -prune -o -path ./.git -prune -o -type f -name "$1" -print 2>/dev/null | wc -l | tr -d ' '; }
N_TS=$(( $(count '*.test.ts') + $(count '*.test.tsx') + $(count '*.spec.ts') ))
N_JS=$(( $(count '*.test.js') + $(count '*.spec.js') ))
N_PY=$(( $(count 'test_*.py') + $(count '*_test.py') ))
N_TESTS=$(( N_TS + N_JS + N_PY ))
N_SNAP=$(( $(count '*.snap') + $(count '*.ambr') ))

# --- testability signals --------------------------------------------------
OPENAPI=""
for f in openapi.json openapi.yaml swagger.json docs/openapi.yaml api/openapi.yaml; do
  [[ -f "$f" ]] && OPENAPI="$f" && break
done
HAS_MIGRATIONS=$(find . -path ./node_modules -prune -o -type d \( -name migrations -o -name migrate \) -print 2>/dev/null | head -1)
HAS_DOCKER=$([[ -f docker-compose.yml || -f compose.yaml ]] && echo yes || echo no)

# --- risk surfaces, by name. A STARTING POINT for a human, not an answer. --
risk_paths() {
  find . -path ./node_modules -prune -o -path ./.git -prune -o -type d -print 2>/dev/null \
    | grep -Ei "/(billing|payment|payments|checkout|auth|authentication|authorization|login|session|user|users|account|accounts|admin|permission|permissions|migration|migrations|crypto|secret|secrets|token|pii)$" \
    | sed 's|^\./||' | sort -u | head -25
}
RISK_DIRS="$(risk_paths)"

# --- suite wall-clock: decides whether the mutation gate is affordable -----
SUITE_SECONDS="null"
if [[ "$TIME_SUITE" -eq 1 && -n "$TEST_CMD" ]]; then
  say "Timing the suite (this is the number that decides whether G2 is affordable)..."
  S=$(date +%s)
  ( . "$ROOT/.qa/gates/lib.sh" >/dev/null 2>&1; qa_load_adapter >/dev/null 2>&1; qa_test_all ) >/dev/null 2>&1
  SUITE_SECONDS=$(( $(date +%s) - S ))
fi

# --- history --------------------------------------------------------------
python3 "$ROOT/scripts/qa-history.py" >/dev/null 2>&1
HIST_FILES=$(jq -r '.files | length' "$ROOT/.qa/metrics/history.json" 2>/dev/null || echo 0)
HIST_TRUNC=$(jq -r '.history_truncated' "$ROOT/.qa/metrics/history.json" 2>/dev/null || echo false)

# --- machine-readable -----------------------------------------------------
jq -n \
  --arg adapter "$ADAPTER" --arg why "$ADAPTER_WHY" --arg pkg "$PKG_MGR" \
  --arg test_cmd "$TEST_CMD" --arg prop "$PROP_LIB" --arg mut "$MUT_TOOL" \
  --arg openapi "$OPENAPI" --arg migrations "$HAS_MIGRATIONS" --arg docker "$HAS_DOCKER" \
  --arg port "$PORTABILITY" \
  --argjson tests "$N_TESTS" --argjson snaps "$N_SNAP" \
  --argjson suite "$SUITE_SECONDS" --argjson hist "$HIST_FILES" \
  --arg trunc "$HIST_TRUNC" \
  --argjson missing "$(printf '%s\n' "${MISSING[@]:-}" | grep -v '^$' | jq -R . | jq -s .)" \
  --argjson risk "$(printf '%s\n' "$RISK_DIRS" | grep -v '^$' | jq -R . | jq -s .)" \
  '{adapter:$adapter, adapter_reason:$why, package_manager:$pkg, test_command:$test_cmd,
    property_lib:$prop, mutation_tool:$mut, openapi:$openapi, migrations_dir:$migrations,
    docker_compose:$docker, portability_notes:$port, test_files:$tests, snapshot_files:$snaps,
    suite_seconds:$suite, history_files:$hist, history_truncated:$trunc,
    missing_prerequisites:$missing, candidate_risk_paths:$risk}' > "$J"

# --- human-readable -------------------------------------------------------
{
  echo "# QA init report"
  echo
  echo "Generated by \`scripts/qa-init.sh\`. Deterministic findings only — every"
  echo "judgement call is left to you or to the agent that reads this."
  echo
  echo "## Stack"
  echo
  echo "| | |"
  echo "|---|---|"
  echo "| Adapter | \`${ADAPTER:-unknown}\` — ${ADAPTER_WHY:-} |"
  echo "| Package manager | ${PKG_MGR:-none detected} |"
  echo "| Test command | ${TEST_CMD:-**none found**} |"
  echo "| Test files | $N_TESTS (ts/tsx $N_TS, js $N_JS, py $N_PY) |"
  echo "| Property-testing lib | ${PROP_LIB:-**none** — invariants will be example-based} |"
  echo "| Mutation tool | ${MUT_TOOL:-**none installed**} |"
  echo "| Snapshot files | $N_SNAP $([[ "$N_SNAP" -gt 0 ]] && echo '(each one is a G4 liability)') |"
  echo "| OpenAPI schema | ${OPENAPI:-none — prober loses Schemathesis fuzzing} |"
  echo "| Migrations | ${HAS_MIGRATIONS:-none found} |"
  echo "| docker-compose | $HAS_DOCKER |"
  echo "| Suite wall-clock | $([[ "$SUITE_SECONDS" == "null" ]] && echo '**not measured** — re-run with --time-suite' || echo "${SUITE_SECONDS}s") |"
  echo "| Git history | $HIST_FILES file(s)$([[ "$HIST_TRUNC" == "true" ]] && echo ' — **TRUNCATED**, fetch full depth') |"
  [[ -n "$PORTABILITY" ]] && echo "| Portability | $PORTABILITY |"
  echo
  if [[ "${#MISSING[@]}" -gt 0 && -n "${MISSING[0]:-}" ]]; then
    echo "## Missing prerequisites"
    echo
    printf -- '- %s\n' "${MISSING[@]}"
    echo
  fi
  echo "## Candidate high-risk paths"
  echo
  if [[ -n "$RISK_DIRS" ]]; then
    echo "Found by directory name. **A starting point, not an answer** — a human"
    echo "signs these off before they band anything (spec §12 Phase 0)."
    echo
    printf -- '- `%s`\n' $RISK_DIRS
  else
    echo "None matched by name. Identify them from §15 Q15 instead: what touches"
    echo "money, auth, PII, or destructive operations?"
  fi
  echo
  echo "## Blockers"
  echo
  [[ -z "$TEST_CMD" ]] && echo "- **No test command found.** The gates have nothing to run. This is the first thing to fix."
  [[ -z "$MUT_TOOL" ]] && echo "- **No mutation tool.** G2 is the design's central gate; §15 Q4 says to stop and escalate if the stack has none. Install Stryker (JS/TS) or mutmut (Python), or accept that the mutation gate is unavailable and say so in every report."
  [[ "$N_TESTS" -eq 0 ]] && echo "- **No tests at all.** unit-smith has no conventions to follow; expect low acceptance until a few hand-written tests establish the house style."
  echo
  echo "## Still needs a human — not guessed"
  echo
  echo "- **§15 Q17** — feature flags, staged rollout, or fast rollback? Decides whether \`SHIP_WITH_WATCH\` is real."
  echo "- **§15 Q20** — what does \"confident to ship\" concretely mean here? Decides what the marshal measures."
} > "$M"

say ""
say "Wrote $M"
say "      $J"
say ""
sed -n '/## Stack/,/^$/p' "$M" | head -20
