#!/usr/bin/env bash
# G6 — budget, as a RUNNING total checked between agents (spec §5 G6).
#
# The spec is specific about why this is not a post-hoc assertion: a per-
# invocation `jq -e '.total_cost_usd < N'` is a post-mortem, not a budget. The
# orchestrator calls this BEFORE dispatching each agent.
#
#   g6-budget.sh check <next-agent> [est-usd]   -> exit 0 to proceed, 1 to stop
#   g6-budget.sh record <agent> <usd>           -> add a completed agent's spend
#   g6-budget.sh total                          -> print spend so far
QA_GATE_NAME=g6
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
qa_need jq

PR="${QA_PR:-local}"

# Budget scales with the risk band. A flat cap would abort every critical PR
# mid-route (see .qa/DECISIONS.md D-009), which converts the most important
# reviews into the least complete ones.
BAND="${QA_BAND:-$(jq -r '.band // "medium"' "$QA_ROOT/.qa/risk/${PR}.json" 2>/dev/null || echo medium)}"
CAP="$(python3 -c "
import yaml
d = yaml.safe_load(open('$QA_ROOT/.qa/RISK-RULES.yaml')) or {}
g = d.get('gates', {}) or {}
by = g.get('pr_budget_usd_by_band', {}) or {}
print(by.get('$BAND', g.get('pr_budget_usd', 8.0)))
" 2>/dev/null || echo 8.00)"
CAP="${QA_PR_BUDGET_USD:-$CAP}"
LEDGER="$QA_ROOT/.qa/metrics/cost/${PR}.json"
mkdir -p "$(dirname "$LEDGER")"
[[ -f "$LEDGER" ]] || echo '{"pr":"'"$PR"'","total_usd":0,"agents":[]}' > "$LEDGER"

total() { jq -r '.total_usd' "$LEDGER"; }

case "${1:-}" in
  total) total ;;

  record)
    agent="${2:?agent}"; usd="${3:?usd}"
    tmp="$(mktemp)"
    jq --arg a "$agent" --argjson u "$usd" --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
       '.agents += [{agent:$a,usd:$u,at:$t}] | .total_usd = ((.total_usd // 0) + $u)' \
       "$LEDGER" > "$tmp" && mv "$tmp" "$LEDGER"
    qa_log "recorded $agent \$$usd; running total \$$(total) of \$$CAP"
    ;;

  check)
    agent="${2:?agent}"; est="${3:-0}"
    spent="$(total)"
    if jq -n --argjson s "$spent" --argjson e "$est" --argjson c "$CAP" -e '($s + $e) > $c' >/dev/null; then
      qa_log "STOP — dispatching '$agent' (est \$$est) would exceed the \$$CAP cap (spent \$$spent)"
      # Never silently truncate: a truncated run reporting success is worse
      # than no run at all. Leave an explicit marker for the marshal.
      jq -n --arg a "$agent" --argjson s "$spent" --argjson c "$CAP" \
        '{reason:"budget_exhausted",stopped_before:$a,spent_usd:$s,cap_usd:$c,
          instruction:"release-marshal must report LOW confidence with reason budget_exhausted and list every agent that did not run under untested"}' \
        > "$QA_ROOT/.qa/metrics/cost/${PR}.stop.json"
      qa_emit_result g6 BUDGET_EXHAUSTED "$(jq -nc --arg a "$agent" --argjson s "$spent" '{stopped_before:$a,spent_usd:$s}')"
      exit "$QA_EXIT_GATE_FAILED"
    fi
    qa_log "ok to dispatch '$agent' (spent \$$spent, est \$$est, cap \$$CAP)"
    ;;

  *) echo "usage: g6-budget.sh {check <agent> [est]|record <agent> <usd>|total}" >&2; exit 2 ;;
esac
