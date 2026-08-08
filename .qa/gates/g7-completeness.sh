#!/usr/bin/env bash
# G7 — oracle and marshal completeness (spec §5 G7).
#
# Without this gate the system's optimisation pressure points the wrong way:
# 2 vague propositions yield 2/2 covered and a clean HIGH, while 12 sharp ones
# yield 8/12 and a MEDIUM. That inverts the mission, so completeness is graded.
#
#   g7-completeness.sh oracle  <band> <.qa/oracles/<pr>.md>
#   g7-completeness.sh marshal <band> <.qa/reports/<pr>.json>
QA_GATE_NAME=g7
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
qa_need jq
MODE="${1:?oracle|marshal}"; BAND="${2:?band}"; FILE="${3:?file}"
PR_FILES_SRC="$QA_ROOT/.qa/risk/${QA_PR:-local}.json"
[[ -f "$FILE" ]] || qa_die "missing $FILE"

RULES="$QA_ROOT/.qa/RISK-RULES.yaml"
minprops=$(python3 -c "
import yaml,sys
d=yaml.safe_load(open('$RULES')) or {}
print((d.get('gates',{}).get('oracle_min_propositions',{}) or {}).get('$BAND',3))" 2>/dev/null || echo 3)
floor=$(python3 -c "
import yaml
d=yaml.safe_load(open('$RULES')) or {}
print((d.get('gates',{}) or {}).get('oracle_citation_rate_floor',0.7))" 2>/dev/null || echo 0.7)
swa=$(python3 -c "
import yaml
d=yaml.safe_load(open('$RULES')) or {}
print(str(d.get('ship_with_watch_available',False)).lower())" 2>/dev/null || echo false)

if [[ "$MODE" == "oracle" ]]; then
  props=$(grep -cE '^\s*-\s*\[[OIB][0-9]+\]' "$FILE" || true)
  cited=$(grep -cE '^\s*-\s*source:' "$FILE" || true)
  rate=$(python3 -c "p=$props;c=$cited;print(round(c/p,3) if p else 0)")
  status=PASS; notes=()

  if [[ "$props" -lt "$minprops" ]]; then
    status=FAIL
    notes+=("only $props proposition(s); band '$BAND' requires $minprops")
  fi
  cap=""
  if python3 -c "import sys;sys.exit(0 if $rate < $floor else 1)"; then
    cap="oracle_citation_rate_below_${floor}"
    notes+=("citation rate $rate is below $floor — report confidence caps at MEDIUM")
  fi
  # A refactor PR with no ticket yields no propositions. Spec §5 G7: that is not
  # a pass, it is an automatic MEDIUM with an explicit untested entry.
  if [[ "$props" -eq 0 ]]; then
    status=PASS
    cap="no_specification_available"
    notes+=("no specification available — automatic MEDIUM, untested must say so")
  fi

  qa_log "$status — $props propositions, $cited cited (rate $rate)"
  printf '  %s\n' "${notes[@]:-none}" >&2
  qa_emit_result g7-oracle "$status" "$(jq -nc --argjson p "$props" --argjson c "$cited" \
    --argjson r "$rate" --arg cap "$cap" --arg b "$BAND" \
    '{propositions:$p,cited:$c,citation_rate:$r,confidence_cap:$cap,band:$b}')"
  [[ "$status" == PASS ]] && exit "$QA_EXIT_PASS" || exit "$QA_EXIT_GATE_FAILED"
fi

# ---- marshal ---------------------------------------------------------------
status=PASS; notes=()
untested_n=$(jq -r '(.untested // []) | length' "$FILE")
verdict=$(jq -r '.verdict // ""' "$FILE")
props=$(jq -r '(.evidence.oracle_propositions // 0)' "$FILE")
covered=$(jq -r '(.evidence.propositions_covered_by_tests // 0)' "$FILE")

if [[ "$BAND" == "high" || "$BAND" == "critical" ]] && [[ "$untested_n" -eq 0 ]]; then
  status=FAIL
  notes+=("'untested' is empty on a $BAND PR. If the marshal cannot name what it did not test, it is not thinking.")
fi

# Every proposition must be accounted for: covered by a test, or named in untested.
unaccounted=$(( props - covered - untested_n ))
if [[ "$props" -gt 0 && "$unaccounted" -gt 0 ]]; then
  status=FAIL
  notes+=("$unaccounted proposition(s) neither covered by a test nor listed in untested")
fi

if [[ "$verdict" == "SHIP_WITH_WATCH" && "$swa" != "true" ]]; then
  status=FAIL
  notes+=("SHIP_WITH_WATCH used but ship_with_watch_available is false — no rollout machinery is confirmed to exist (§15 Q17), so the verdict is unactionable")
fi

# SHIP_WITH_WATCH is only meaningful if the watcher can actually undo the change.
# Here the mechanism is redeploying the previous version, which cannot reverse an
# applied migration, a completed payment, or an email already sent. When the diff
# touches one of those, "watch it" offers a response that does not exist.
if [[ "$verdict" == "SHIP_WITH_WATCH" && "$swa" == "true" ]]; then
  mapfile -t UNSAFE < <(python3 - "$QA_ROOT" "$PR_FILES_SRC" <<'PY2'
import sys, os, re, subprocess
try:
    import yaml
except ImportError:
    sys.exit(0)
root = sys.argv[1]
d = yaml.safe_load(open(os.path.join(root, ".qa/RISK-RULES.yaml"))) or {}
pats = ((d.get("rollback") or {}).get("rollback_unsafe_paths")) or []
if not pats:
    sys.exit(0)

src = sys.argv[2] if len(sys.argv) > 2 else ""
files = []
if src and os.path.exists(src):
    import json
    try:
        files = json.load(open(src)).get("changed_files", []) or []
    except Exception:
        files = []
if not files:
    base = os.environ.get("QA_BASE_REF", "origin/" + os.environ.get("QA_DEFAULT_BRANCH", "main"))
    try:
        mb = subprocess.run(["git", "merge-base", "HEAD", base], capture_output=True, text=True).stdout.strip()
        if mb:
            files = subprocess.run(["git", "diff", "--name-only", mb + "...HEAD"],
                                   capture_output=True, text=True).stdout.split()
    except Exception:
        files = []

def to_re(pat):
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i): out.append("(?:.*/)?"); i += 3
        elif pat.startswith("**", i): out.append(".*"); i += 2
        elif pat[i] == "*": out.append("[^/]*"); i += 1
        elif pat[i] == "?": out.append("[^/]"); i += 1
        else: out.append(re.escape(pat[i])); i += 1
    return re.compile("^" + "".join(out) + "$")

rx = [to_re(p) for p in pats]
for f in files:
    if any(r.match(f) for r in rx):
        print(f)
PY2
)
  if [[ ${#UNSAFE[@]} -gt 0 ]]; then
    status=FAIL
    notes+=("SHIP_WITH_WATCH used, but ${#UNSAFE[@]} changed file(s) cannot be undone by a rollback: ${UNSAFE[*]:0:5}. Redeploying old code does not revert an applied migration, recall a payment, or unsend an email. Use SHIP or HOLD.")
  fi
fi

qa_log "$status"
printf '  %s\n' "${notes[@]:-ok}" >&2
qa_emit_result g7-marshal "$status" "$(jq -nc --argjson u "$untested_n" --argjson p "$props" \
  --argjson c "$covered" --arg v "$verdict" \
  '{untested_count:$u,propositions:$p,covered:$c,verdict:$v}')"
[[ "$status" == PASS ]] && exit "$QA_EXIT_PASS" || exit "$QA_EXIT_GATE_FAILED"
