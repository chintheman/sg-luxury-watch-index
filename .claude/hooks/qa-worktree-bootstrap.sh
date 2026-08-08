#!/usr/bin/env bash
# Worktree bootstrap (spec §7.3).
#
# `git worktree add` gives you source files and NOTHING else: no node_modules,
# no venv, no .env, no seeded database. Without this, step one of the mutation
# loop fails with "module not found" and the agent burns 30 turns on dependency
# installation it may not even have permission to perform.
#
# Delegates to the adapter, which knows what this stack needs. An adapter with
# no qa_bootstrap_worktree means worktree isolation is unavailable — in which
# case serialise the writers (§11 fallback) rather than running them in parallel
# against a broken tree.
set -uo pipefail
QA_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export QA_ROOT
. "$QA_ROOT/.qa/gates/lib.sh"
qa_load_adapter

WT="${1:?usage: qa-worktree-bootstrap.sh <worktree-dir>}"

if ! declare -f qa_bootstrap_worktree >/dev/null; then
  echo "adapter '$QA_ADAPTER_NAME' does not implement qa_bootstrap_worktree." >&2
  echo "Worktree isolation is unavailable: serialise writers instead of running them in parallel." >&2
  exit 91
fi

qa_bootstrap_worktree "$WT"
