#!/usr/bin/env bash
# Sync .claude/agents/ -> agents/ (see agents/README.md for why both exist).
#   --check  compare only; exit 1 on drift. Used by the self-test.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/.claude/agents"; DST="$ROOT/agents"
CHECK=0; [[ "${1:-}" == "--check" ]] && CHECK=1
mkdir -p "$DST"
drift=0
for f in "$SRC"/*.md; do
  b="$(basename "$f")"
  if [[ ! -f "$DST/$b" ]] || ! cmp -s "$f" "$DST/$b"; then
    drift=1
    [[ $CHECK -eq 1 ]] && echo "  drift: $b" || cp "$f" "$DST/$b"
  fi
done
for f in "$DST"/*.md; do
  b="$(basename "$f")"
  # No exemptions: every .md here is auto-loaded as an agent definition, so a
  # stray README becomes an agent called "README". Documentation lives in
  # docs/, never in this directory.
  if [[ ! -f "$SRC/$b" ]]; then
    drift=1
    [[ $CHECK -eq 1 ]] && echo "  orphan: $b" || rm -f "$f"
  fi
done
if [[ $CHECK -eq 1 ]]; then
  [[ $drift -eq 0 ]] && echo "  ok    agents/ matches .claude/agents/" || \
    echo "  FAIL  agents/ has drifted — run scripts/qa-sync-agents.sh"
  exit $drift
fi
echo "synced $(ls -1 "$SRC"/*.md | wc -l | tr -d ' ') agent(s) to agents/"
