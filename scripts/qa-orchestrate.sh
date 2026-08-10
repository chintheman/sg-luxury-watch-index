#!/usr/bin/env bash
# Per-PR orchestrator (spec §6.1).
#
# Exists for one reason the CI workflow cannot serve on its own: G6 requires a
# running budget checked BETWEEN agents. A per-invocation --max-budget-usd is a
# useful backstop but it is a post-mortem — it stops one agent overspending, not
# the fleet. This reads the ledger before every dispatch.
#
# Usage: scripts/qa-orchestrate.sh <pr-number> [--dry-run]
set -uo pipefail
QA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export QA_ROOT
. "$QA_ROOT/.qa/gates/lib.sh"

PR="${1:?usage: qa-orchestrate.sh <pr-number> [--dry-run]}"
DRY=0; [[ "${2:-}" == "--dry-run" ]] && DRY=1
export QA_PR="$PR"

BAND="$(jq -r '.band // "medium"' "$QA_ROOT/.qa/risk/$PR.json" 2>/dev/null || echo medium)"
mapfile -t ROUTE < <(python3 -c "
import yaml
d=yaml.safe_load(open('$QA_ROOT/.qa/RISK-RULES.yaml')) or {}
for a in (d.get('routing',{}) or {}).get('$BAND',[]): print(a)")

# Rough per-agent estimates. Replaced with measured values after Phase 3 —
# §13 is explicit that the published figures are placeholders and that real
# costs run 2-4x naive estimates.
est_for() { case "$1" in
  risk-scout) echo 0.10 ;; spec-oracle) echo 2.00 ;; unit-smith) echo 4.00 ;;
  flow-smith) echo 6.00 ;; prober) echo 4.00 ;; authz-prober) echo 3.00 ;;
  release-marshal) echo 1.50 ;; *) echo 1.00 ;; esac; }

# An agent's name is NOT its slash command: the agents are named for the role
# (unit-smith), the commands for the task (/qa-test). Interpolating "/qa-$agent"
# produced "/qa-unit-smith" — a command that does not exist — for every agent on
# every route, so no dispatch could ever have worked. Anything unmapped is a
# hard error: dispatching a non-existent command wastes a turn and returns
# nothing, which the marshal would read as an agent that ran and found nothing.
command_for() { case "$1" in
  risk-scout)      echo qa-risk ;;
  spec-oracle)     echo qa-oracle ;;
  unit-smith)      echo qa-test ;;
  flow-smith)      echo qa-flow ;;
  prober)          echo qa-probe ;;
  patch-smith)     echo qa-fix ;;
  release-marshal) echo qa-verdict ;;
  *) return 1 ;;
esac; }

echo "PR #$PR — band '$BAND' — route: ${ROUTE[*]:-none}"
STOPPED=""

for agent in "${ROUTE[@]}"; do
  if ! cmd="$(command_for "$agent")"; then
    echo "  ERROR: '$agent' is routed by RISK-RULES.yaml but has no /qa-* command."
    echo "  Add one under .claude/commands/, or remove it from the route."
    STOPPED="$agent"
    break
  fi
  est="$(est_for "$agent")"
  if ! "$QA_ROOT/.qa/gates/g6-budget.sh" check "$agent" "$est"; then
    STOPPED="$agent"
    break
  fi
  if [[ $DRY -eq 1 ]]; then
    echo "  [dry-run] would dispatch $agent (est \$$est)"
    "$QA_ROOT/.qa/gates/g6-budget.sh" record "$agent" "$est" >/dev/null
    continue
  fi

  echo "  dispatching $agent (/$cmd) ..."
  out="$(claude -p "/$cmd $PR" \
        --settings "$QA_ROOT/.claude/qa-ci-settings.json" \
        --agent "$agent" --permission-mode dontAsk \
        --output-format json 2>/dev/null)"
  cost="$(jq -r '.total_cost_usd // 0' <<<"$out")"
  "$QA_ROOT/.qa/gates/g6-budget.sh" record "$agent" "$cost"
done

if [[ -n "$STOPPED" ]]; then
  # Never silently truncate. The marshal must report LOW with an explicit
  # reason and list the agents that never ran — a truncated run reporting
  # success is worse than no run at all.
  echo "STOPPED before '$STOPPED'."
  echo "release-marshal must report LOW, name the reason, and list the agents that never ran under untested."
  exit 1
fi
echo "route complete; spent \$$("$QA_ROOT/.qa/gates/g6-budget.sh" total)"
