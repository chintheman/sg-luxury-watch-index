#!/usr/bin/env bash
# Self-test for .qa/policy.proposed.yaml — the repo-fitted policy.
#
# Why this is a second file rather than an edit to guard-selftest.sh: that table
# asserts against the SHIPPED policy, whose globs are the kit's placeholders
# (src/, lib/, app/). The two policies disagree by design — under the shipped
# one patch-smith may write src/calc.py and spec-oracle may read
# index/index_engine.py; under this one it is the other way round, which is the
# point. One table cannot be green against both.
#
# So this runs the guard against a throwaway CLAUDE_PROJECT_DIR whose
# policy.yaml IS the proposed file. When a human adopts the proposal, they
# delete guard-selftest.sh's placeholder rows and keep these.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="$KIT/.claude/hooks/qa-guard.py"
PROPOSED="$KIT/.qa/policy.proposed.yaml"

[[ -f "$PROPOSED" ]] || { echo "  SKIP  no .qa/policy.proposed.yaml"; exit 0; }

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/.qa"
cp "$PROPOSED" "$SANDBOX/.qa/policy.yaml"

fails=0; total=0

check() { # label expected json
  local label="$1" want="$2" json="$3" rc got
  CLAUDE_PROJECT_DIR="$SANDBOX" QA_PR=selftest python3 "$GUARD" >/dev/null 2>&1 <<<"$json"
  rc=$?; total=$((total+1))
  [[ $rc -eq 0 ]] && got=ALLOW || got=BLOCK
  if [[ "$got" == "$want" ]]; then printf '  ok    %-54s %s\n' "$label" "$got"
  else printf '  FAIL  %-54s expected %s, got %s\n' "$label" "$want" "$got"; fails=$((fails+1)); fi
}

w() { jq -nc --arg a "$1" --arg p "$2" '{agent_type:$a,tool_name:"Write",tool_input:{file_path:$p}}'; }
r() { jq -nc --arg a "$1" --arg p "$2" '{agent_type:$a,tool_name:"Read",tool_input:{file_path:$p}}'; }
b() { jq -nc --arg a "$1" --arg c "$2" '{agent_type:$a,tool_name:"Bash",tool_input:{command:$c}}'; }
ob() { jq -nc --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }

echo "=== proposed-policy guard self-test ==="

echo "-- the regression that motivated this: ordinary commands must survive --"
check "orchestrator git push -u origin"        ALLOW "$(ob 'git push -u origin claude/qa-lvqlj1')"
check "orchestrator sort -u"                   ALLOW "$(ob 'sort -u names.txt')"
check "orchestrator pip install -U"            ALLOW "$(ob 'pip install -U pytest')"
check "orchestrator ls the gates"              ALLOW "$(ob 'ls .qa/gates/')"
check "orchestrator grep RISK-RULES"           ALLOW "$(ob 'grep mutation_paths .qa/RISK-RULES.yaml')"
check "orchestrator RUN a gate"                ALLOW "$(ob 'bash .qa/gates/g3-vacuity.sh')"

echo "-- but snapshot laundering is still denied for everyone --"
check "unit-smith  vitest -u"                  BLOCK "$(b unit-smith 'npx vitest run -u')"
check "unit-smith  jest -u"                    BLOCK "$(b unit-smith 'npx jest -u')"
check "unit-smith  pytest --snapshot-update"   BLOCK "$(b unit-smith 'pytest --snapshot-update')"
check "orchestrator jest --updateSnapshot"     BLOCK "$(ob 'npx jest --updateSnapshot')"
check "orchestrator playwright --update-snapshots" BLOCK "$(ob 'npx playwright test --update-snapshots')"

echo "-- and mutating the referee from a shell is still denied --"
check "orchestrator redirect into policy"      BLOCK "$(ob 'echo x > .qa/policy.yaml')"
check "orchestrator sed -i a gate"             BLOCK "$(ob 'sed -i s/a/b/ .qa/gates/g2-mutation.sh')"
check "orchestrator rm RISK-RULES"             BLOCK "$(ob 'rm .qa/RISK-RULES.yaml')"
check "orchestrator overwrite a hook"          BLOCK "$(ob 'echo x > .claude/hooks/qa-guard.sh')"
check "unit-smith Write -> .qa/gates/g2.sh"    BLOCK "$(w unit-smith .qa/gates/g2.sh)"
check "unit-smith Write -> .claude/hooks/x.sh" BLOCK "$(w unit-smith .claude/hooks/x.sh)"

echo "-- P2: oracle blindness, against paths that EXIST in this repo --"
check "oracle Read index/index_engine.py"      BLOCK "$(r spec-oracle index/index_engine.py)"
check "oracle Read index/signals.py"           BLOCK "$(r spec-oracle index/signals.py)"
check "oracle Read parser/filter.py"           BLOCK "$(r spec-oracle parser/filter.py)"
check "oracle Read scraper/scraper.py"         BLOCK "$(r spec-oracle scraper/scraper.py)"
check "oracle Read pipeline.py"                BLOCK "$(r spec-oracle pipeline.py)"
check "oracle Read sold_tracer.py"             BLOCK "$(r spec-oracle sold_tracer.py)"
check "oracle Read tests/test_index_v3.py"     BLOCK "$(r spec-oracle tests/test_index_v3.py)"
check "oracle Read METHODOLOGY.md"             ALLOW "$(r spec-oracle METHODOLOGY.md)"
check "oracle Grep index/**"                   BLOCK "$(jq -nc '{agent_type:"spec-oracle",tool_name:"Grep",tool_input:{pattern:"index/**"}}')"
check "oracle Fetch PR files URL"              BLOCK "$(jq -nc '{agent_type:"spec-oracle",tool_name:"WebFetch",tool_input:{url:"https://github.com/o/r/pull/12/files"}}')"

echo "-- P4: patch-smith can now write THIS repo's source, never its tests --"
check "patch-smith -> index/index_engine.py"   ALLOW "$(w patch-smith index/index_engine.py)"
check "patch-smith -> parser/filter.py"        ALLOW "$(w patch-smith parser/filter.py)"
check "patch-smith -> pipeline.py"             ALLOW "$(w patch-smith pipeline.py)"
check "patch-smith -> tests/test_dedupe.py"    BLOCK "$(w patch-smith tests/test_dedupe.py)"
check "patch-smith -> migrations/001_x.py"     BLOCK "$(w patch-smith migrations/001_reply_and_edits.py)"
check "patch-smith Bash git log"               BLOCK "$(b patch-smith 'git log -20')"

echo "-- P4: everyone else stays in their lane --"
check "unit-smith  -> tests/test_x.py"         ALLOW "$(w unit-smith tests/test_x.py)"
check "unit-smith  -> index/index_engine.py"   BLOCK "$(w unit-smith index/index_engine.py)"
check "unit-smith  -> .qa/fixtures/python/a.py" ALLOW "$(w unit-smith .qa/fixtures/python/a.py)"
check "risk-scout  -> .qa/risk/1.json"         ALLOW "$(w risk-scout .qa/risk/1.json)"
check "risk-scout  -> .qa/oracles/1.md"        BLOCK "$(w risk-scout .qa/oracles/1.md)"
check "marshal     -> .qa/reports/1.md"        ALLOW "$(w release-marshal .qa/reports/1.md)"
check "marshal     -> index/index_engine.py"   BLOCK "$(w release-marshal index/index_engine.py)"
check "unknown agent write"                    BLOCK "$(w rogue-agent index/index_engine.py)"
check "unknown agent bash"                     BLOCK "$(b rogue-agent 'ls')"
check "escape via absolute path"               BLOCK "$(w unit-smith /etc/passwd)"

echo
if [[ $fails -eq 0 ]]; then echo "proposed-policy self-test: all $total cases correct"; exit 0
else echo "proposed-policy self-test: $fails of $total case(s) wrong"; exit 1; fi
