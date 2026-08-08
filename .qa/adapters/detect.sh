#!/usr/bin/env bash
# Pick a stack adapter by inspecting the repo. Prints "<adapter>\t<reason>".
# Deliberately conservative: when the signals are ambiguous it prints "custom"
# rather than guessing, because a wrong adapter makes every gate lie.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

has() { [[ -e "$ROOT/$1" ]]; }
pkg_has() { [[ -f "$ROOT/package.json" ]] && jq -e --arg d "$1" \
  '((.dependencies//{}) + (.devDependencies//{})) | has($d)' "$ROOT/package.json" >/dev/null 2>&1; }

if has package.json; then
  if pkg_has vitest;  then echo -e "node-vitest\tpackage.json declares vitest"; exit 0; fi
  if pkg_has jest;    then echo -e "node-jest\tpackage.json declares jest";     exit 0; fi
  echo -e "custom\tpackage.json present but no recognised test runner"; exit 0
fi

if has pyproject.toml || has setup.cfg || has requirements.txt || has tox.ini; then
  echo -e "python-pytest\tPython project metadata present"; exit 0
fi

echo -e "custom\tno recognised stack; write an adapter from custom.sh.template"
