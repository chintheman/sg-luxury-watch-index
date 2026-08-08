#!/usr/bin/env bash
# Shared plumbing for the mechanical gates (spec §5).
#
# Design rule for everything in this directory: a gate must never be able to
# pass by doing nothing. Missing tooling, an unimplemented adapter, or an
# unparseable report are all failures or explicit INCONCLUSIVE results — never
# a silent success (P5).

set -uo pipefail

QA_ROOT="${QA_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export QA_ROOT
QA_CONFIG="$QA_ROOT/.qa/config.env"

# Exit codes, so callers and CI can distinguish "the gate said no" from
# "the gate could not run". Conflating these is how a broken gate becomes a
# green build.
QA_EXIT_PASS=0
QA_EXIT_GATE_FAILED=1
QA_EXIT_INCONCLUSIVE=3
QA_EXIT_MISCONFIGURED=90

qa_log()  { printf '[%s] %s\n' "${QA_GATE_NAME:-qa}" "$*" >&2; }
qa_die()  { qa_log "FATAL: $*"; exit "$QA_EXIT_MISCONFIGURED"; }

qa_need() { command -v "$1" >/dev/null 2>&1 || qa_die "required tool '$1' not on PATH"; }

# Load .qa/config.env then the selected adapter.
qa_load_adapter() {
  [[ -f "$QA_CONFIG" ]] && . "$QA_CONFIG"
  local name="${QA_ADAPTER:-}"
  if [[ -z "$name" ]]; then
    name="$("$QA_ROOT/.qa/adapters/detect.sh" | cut -f1)"
    qa_log "no QA_ADAPTER set; auto-detected '$name'"
  fi
  local f="$QA_ROOT/.qa/adapters/${name}.sh"
  [[ -f "$f" ]] || qa_die "adapter '$name' not found at $f (copy custom.sh.template)"
  # shellcheck disable=SC1090
  . "$f"
  qa_log "adapter: $QA_ADAPTER_NAME"
}

# Files changed against the merge base. Used by every gate that scopes to a diff.
qa_changed_files() {
  local base="${QA_BASE_REF:-origin/${QA_DEFAULT_BRANCH:-main}}"
  if git rev-parse --verify -q "$base" >/dev/null; then
    git diff --name-only --diff-filter=ACMR "$(git merge-base HEAD "$base")"...HEAD
  else
    # No base ref (new repo, shallow clone): fall back to the last commit rather
    # than silently reporting "nothing changed", which would pass every gate.
    qa_log "base ref '$base' unresolvable; falling back to HEAD~1"
    git diff --name-only --diff-filter=ACMR HEAD~1...HEAD 2>/dev/null || git ls-files
  fi
}

# Filter a file list through the mutation_paths allow/deny globs in RISK-RULES.yaml.
# Patterns beginning with "!" are exclusions, applied after inclusions (§5 G2).
qa_filter_mutation_paths() {
  local rules="$QA_ROOT/.qa/RISK-RULES.yaml"
  [[ -f "$rules" ]] || { cat; return; }
  python3 - "$rules" <<'PY'
import sys, fnmatch, re
try:
    import yaml
except ImportError:
    # No PyYAML: pass everything through rather than silently dropping files,
    # which would shrink the gate's scope without anyone noticing.
    sys.stderr.write("[g2] PyYAML missing; mutation_paths not applied\n")
    for line in sys.stdin: sys.stdout.write(line)
    raise SystemExit(0)

pats = (yaml.safe_load(open(sys.argv[1])) or {}).get("mutation_paths") or []
inc = [p for p in pats if not str(p).startswith("!")]
exc = [str(p)[1:] for p in pats if str(p).startswith("!")]

def match(path, pat):
    # fnmatch does not treat "**" specially, so translate it ourselves.
    rx = re.escape(pat).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", ".")
    return re.fullmatch(rx, path) is not None

for line in sys.stdin:
    p = line.strip()
    if not p: continue
    if inc and not any(match(p, i) for i in inc): continue
    if any(match(p, e) for e in exc): continue
    print(p)
PY
}

# Write a gate result as JSON so release-marshal reads evidence, not prose.
qa_emit_result() { # name status json-extra
  local name="$1" status="$2" extra="${3:-{\}}"
  local out="$QA_ROOT/.qa/metrics/gates"
  mkdir -p "$out"
  jq -nc --arg n "$name" --arg s "$status" --argjson e "$extra" \
     --arg pr "${QA_PR:-local}" --arg t "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
     '{gate:$n,status:$s,pr:$pr,at:$t} + $e' > "$out/${name}-${QA_PR:-local}.json"
}
