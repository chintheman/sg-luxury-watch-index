#!/usr/bin/env bash
# Self-test for the G5 guard (spec §5 G5, §4 P4).
#
# The guard is the only thing standing between the design and "agent writes
# test, test fails, same agent loosens the assertion". It gets a table test.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="$KIT/.claude/hooks/qa-guard.py"
fails=0; total=0

check() { # label expected(ALLOW|BLOCK) json
  local label="$1" want="$2" json="$3"
  CLAUDE_PROJECT_DIR="$KIT" QA_PR=selftest python3 "$GUARD" >/dev/null 2>&1 <<<"$json"
  local rc=$? got; total=$((total+1))
  [[ $rc -eq 0 ]] && got=ALLOW || got=BLOCK
  if [[ "$got" == "$want" ]]; then printf '  ok    %-52s %s\n' "$label" "$got"
  else printf '  FAIL  %-52s expected %s, got %s\n' "$label" "$want" "$got"; fails=$((fails+1)); fi
}

w() { # agent path -> Write payload
  jq -nc --arg a "$1" --arg p "$2" '{agent_type:$a,tool_name:"Write",tool_input:{file_path:$p}}'
}
r() { jq -nc --arg a "$1" --arg p "$2" '{agent_type:$a,tool_name:"Read",tool_input:{file_path:$p}}'; }
b() { jq -nc --arg a "$1" --arg c "$2" '{agent_type:$a,tool_name:"Bash",tool_input:{command:$c}}'; }

echo "=== G5 guard self-test ==="
echo "-- P4: test authors may not write source --"
check "unit-smith  -> tests/test_x.py"        ALLOW "$(w unit-smith tests/test_x.py)"
check "unit-smith  -> src/calc.py"            BLOCK "$(w unit-smith src/calc.py)"
check "flow-smith  -> e2e/checkout.spec.ts"   ALLOW "$(w flow-smith e2e/checkout.spec.ts)"

echo "-- P4: the fixer may not touch tests (the load-bearing row) --"
check "patch-smith -> src/calc.py"            ALLOW "$(w patch-smith src/calc.py)"
check "patch-smith -> tests/test_x.py"        BLOCK "$(w patch-smith tests/test_x.py)"
check "patch-smith -> src/a.test.ts"          BLOCK "$(w patch-smith src/a.test.ts)"
check "patch-smith -> .qa/reports/1.md"       BLOCK "$(w patch-smith .qa/reports/1.md)"

echo "-- P4: analysts write only their own directory --"
check "risk-scout  -> .qa/risk/1.json"        ALLOW "$(w risk-scout .qa/risk/1.json)"
check "risk-scout  -> .qa/oracles/1.md"       BLOCK "$(w risk-scout .qa/oracles/1.md)"
check "marshal     -> .qa/reports/1.md"       ALLOW "$(w release-marshal .qa/reports/1.md)"
check "marshal     -> src/calc.py"            BLOCK "$(w release-marshal src/calc.py)"

echo "-- P2: oracle blindness across every content-returning tool (§7.2) --"
check "oracle Read  docs/pricing.md"          ALLOW "$(r spec-oracle docs/pricing.md)"
check "oracle Read  src/billing/coupon.ts"    BLOCK "$(r spec-oracle src/billing/coupon.ts)"
check "oracle Read  tests/test_coupon.py"     BLOCK "$(r spec-oracle tests/test_coupon.py)"
check "oracle Grep  src/**"                   BLOCK "$(jq -nc '{agent_type:"spec-oracle",tool_name:"Grep",tool_input:{pattern:"src/**"}}')"
check "oracle Fetch PR files URL"             BLOCK "$(jq -nc '{agent_type:"spec-oracle",tool_name:"WebFetch",tool_input:{url:"https://github.com/o/r/pull/12/files"}}')"
check "oracle Fetch docs site"                ALLOW "$(jq -nc '{agent_type:"spec-oracle",tool_name:"WebFetch",tool_input:{url:"https://docs.example.com/pricing"}}')"
check "oracle Bash  git diff"                 BLOCK "$(b spec-oracle 'git diff HEAD~1')"

echo "-- P7: solving agents get no history and no upstream lookup --"
check "patch-smith Bash git log"              BLOCK "$(b patch-smith 'git log -20')"
check "patch-smith Bash curl"                 BLOCK "$(b patch-smith 'curl https://x.dev')"
check "patch-smith Bash pytest"               ALLOW "$(b patch-smith 'pytest -q')"

echo "-- G4/P8: snapshot laundering denied for everyone --"
check "unit-smith  vitest -u"                 BLOCK "$(b unit-smith 'npx vitest run -u')"
check "unit-smith  pytest --snapshot-update"  BLOCK "$(b unit-smith 'pytest --snapshot-update')"
check "orchestrator jest --updateSnapshot"    BLOCK "$(jq -nc '{tool_name:"Bash",tool_input:{command:"npx jest --updateSnapshot"}}')"

echo "-- Referee immutability and fail-closed defaults --"
check "unit-smith  -> .qa/gates/g2.sh"        BLOCK "$(w unit-smith .qa/gates/g2.sh)"
check "unit-smith  -> .claude/hooks/x.sh"     BLOCK "$(w unit-smith .claude/hooks/x.sh)"
check "unknown agent write"                   BLOCK "$(w rogue-agent src/x.py)"
check "unknown agent bash"                    BLOCK "$(b rogue-agent 'ls')"
check "orchestrator write src (no agent_type)" ALLOW "$(jq -nc '{tool_name:"Write",tool_input:{file_path:"src/x.py"}}')"
check "escape via absolute path"              BLOCK "$(w unit-smith /etc/passwd)"

echo "-- A guard that cannot read its policy must fail closed --"
EMPTY="$(mktemp -d)"; mkdir -p "$EMPTY/.qa"
CLAUDE_PROJECT_DIR="$EMPTY" python3 "$GUARD" >/dev/null 2>&1 <<<"$(w unit-smith tests/a.py)"
rc=$?; total=$((total+1)); if [[ $rc -ne 0 ]]; then printf '  ok    %-52s BLOCK\n' "missing policy.yaml"; else
  printf '  FAIL  %-52s expected BLOCK\n' "missing policy.yaml"; fails=$((fails+1)); fi
rm -rf "$EMPTY"

echo
if [[ $fails -eq 0 ]]; then echo "G5 guard self-test: all $total cases correct"; exit 0
else echo "G5 guard self-test: $fails of $total case(s) wrong"; exit 1; fi
