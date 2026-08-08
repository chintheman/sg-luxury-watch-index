#!/usr/bin/env bash
# Capability probe for the Agentic QA Team (build spec §11, Phase 0).
#
# Purpose: verify — empirically, against the *installed* CLI — that every
# enforcement mechanism the design leans on actually exists. Spec §11 is blunt
# about why: "Designing around an unverified mechanism and discovering it in
# Phase 3 costs the whole phase."
#
# Two classes of check:
#   STATIC — inspects the CLI binary/help. Free, no API calls.
#   LIVE   — spawns `claude -p` subprocesses. Costs a few cents. Enabled with
#            --live. These are the checks that actually settle the question,
#            because a string in a binary is not proof of a working mechanism.
#
# Usage:
#   .qa/probe/capability-probe.sh            # static only
#   .qa/probe/capability-probe.sh --live     # static + live (recommended)
#
# Writes a machine-readable summary to .qa/probe/results.json and prints a
# human-readable table. Re-run this in any target repo before Phase 1.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$REPO_ROOT/.qa/probe"
RESULTS="$OUT_DIR/results.json"
LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1

# Scratch space for live probes. Deliberately outside the repo so a probe run
# never pollutes the working tree that the gates are about to inspect.
TMP="$(mktemp -d -t qa-probe-XXXXXX)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

pass=0; fail=0; skip=0
declare -a ROWS

record() { # name status detail
  local name="$1" status="$2" detail="$3"
  case "$status" in
    PASS) pass=$((pass+1)) ;;
    FAIL) fail=$((fail+1)) ;;
    *)    skip=$((skip+1)) ;;
  esac
  ROWS+=("$(jq -nc --arg n "$name" --arg s "$status" --arg d "$detail" \
    '{mechanism:$n,status:$s,detail:$d}')")
  printf '  %-34s %-14s %s\n' "$name" "$status" "$detail"
}

echo "=== Agentic QA Team — capability probe (spec §11) ==="
echo

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
CLI_BIN="$(command -v claude || true)"
if [[ -z "$CLI_BIN" ]]; then
  echo "FATAL: no 'claude' on PATH. The whole design depends on the CLI." >&2
  exit 2
fi
CLI_VERSION="$(claude --version 2>/dev/null | head -1)"
# Resolve the real executable: the PATH entry is often a shim in front of a
# native binary, and only the native binary carries the strings worth grepping.
REAL_BIN="$CLI_BIN"
for candidate in /opt/claude-code/bin/claude "$HOME/.local/share/claude/bin/claude"; do
  [[ -x "$candidate" ]] && REAL_BIN="$candidate" && break
done

echo "CLI: $CLI_VERSION"
echo "bin: $REAL_BIN"
echo
echo "--- STATIC checks ---"

HELP="$(claude --help 2>&1)"

# Detecting a CLI flag by grepping --help gives false negatives: several flags
# this design uses (notably --max-turns) are real and functional but hidden
# from help output. Instead, ask the argument parser directly.
#
# Trick: pass the flag under test followed by a sentinel flag that certainly
# does not exist. The parser reports the FIRST unknown option it meets, and
# bails out before any API call — so this is both accurate and free.
#   flag known   -> it complains about the sentinel
#   flag unknown -> it complains about the flag itself
flag_present() {
  local flag="$1"
  local err
  err="$(timeout 20 claude -p "x" "$flag" 1 --qa-probe-sentinel 1 2>&1 | head -2)"
  if grep -q "unknown option '$flag'" <<<"$err"; then
    return 1                      # parser rejected it: genuinely absent
  elif grep -q "unknown option '--qa-probe-sentinel'" <<<"$err"; then
    return 0                      # parser accepted it, tripped on the sentinel
  fi
  # Neither message: the parser did not reach the sentinel (e.g. the flag takes
  # no value and consumed our "1"). Fall back to the help text.
  grep -q -- "$flag" <<<"$HELP"
}

# The CLI flags the design's CI wiring depends on (spec §8).
for f in --settings --allowedTools --disallowedTools --permission-mode \
         --max-turns --output-format --model --max-budget-usd; do
  if flag_present "$f"; then
    if grep -q -- "$f" <<<"$HELP"; then
      record "cli-flag $f" PASS "accepted by parser; documented"
    else
      record "cli-flag $f" PASS "accepted by parser; UNDOCUMENTED (hidden flag)"
    fi
  else
    record "cli-flag $f" FAIL "rejected by parser — §8 CI wiring must change"
  fi
done

# §8 warns against --bare because it skips hooks. Confirm that's still true, so
# the warning in our CI comments stays accurate rather than becoming folklore.
if grep -q -- '--bare' <<<"$HELP" && grep -qi 'skip hooks' <<<"$HELP"; then
  record "bare-skips-hooks" PASS "--bare documented as skipping hooks; §8 ban stands"
else
  record "bare-skips-hooks" SKIP "could not confirm from --help; keep the §8 ban anyway"
fi

# Agent frontmatter keys, read out of the binary. Weak evidence on its own —
# a string is not a schema — so this is corroboration for the LIVE checks.
if [[ -r "$REAL_BIN" ]]; then
  for key in disallowedTools permissionMode maxTurns memory isolation effort mcpServers; do
    if grep -aqm1 -- "$key" "$REAL_BIN"; then
      record "frontmatter-string $key" PASS "string present in binary (corroborating)"
    else
      record "frontmatter-string $key" FAIL "string absent — assume unsupported"
    fi
  done
else
  record "frontmatter-strings" SKIP "binary not readable"
fi

# ---------------------------------------------------------------------------
# LIVE checks — the ones that actually settle §11
# ---------------------------------------------------------------------------
if [[ "$LIVE" -eq 0 ]]; then
  echo
  echo "--- LIVE checks SKIPPED (pass --live to run them) ---"
  record "live-probes" SKIP "not run; §11 remains UNVERIFIED"
else
  echo
  echo "--- LIVE checks (spawns claude -p; costs a few cents) ---"

  # A live probe needs a throwaway git repo: worktree isolation requires one,
  # and we must never let a probe write into the real working tree.
  PROBE_REPO="$TMP/repo"
  mkdir -p "$PROBE_REPO/.claude/agents" "$PROBE_REPO/.claude/hooks"
  git -C "$PROBE_REPO" init -q
  git -C "$PROBE_REPO" config user.email probe@example.com
  git -C "$PROBE_REPO" config user.name probe
  echo "seed" > "$PROBE_REPO/seed.txt"
  git -C "$PROBE_REPO" add -A
  git -C "$PROBE_REPO" commit -qm "seed"

  run_claude() { # prompt extra-args... ; prints combined output
    local prompt="$1"; shift
    ( cd "$PROBE_REPO" && timeout 180 claude -p "$prompt" \
        --model claude-haiku-4-5-20251001 \
        --max-turns 4 \
        --permission-mode dontAsk \
        "$@" 2>&1 )
  }

  # --- L1: does the CLI accept the agent frontmatter this design uses? -------
  cat > "$PROBE_REPO/.claude/agents/probe-fields.md" <<'AGENT'
---
name: probe-fields
description: Capability probe agent exercising the frontmatter fields the QA design relies on.
tools: Read, Write
disallowedTools: Edit, Bash
model: haiku
effort: low
maxTurns: 3
memory: project
color: cyan
---
Reply with exactly: FIELDS_OK
AGENT

  out="$(run_claude "Say FIELDS_OK" --agent probe-fields)"
  if grep -qi 'unknown field\|unknown key\|failed to parse' <<<"$out"; then
    record "agent-frontmatter" FAIL "CLI rejected a field: $(grep -io 'unknown field "[^"]*"' <<<"$out" | head -3 | tr '\n' ' ')"
  elif grep -q 'FIELDS_OK' <<<"$out"; then
    record "agent-frontmatter" PASS "all §7.1 fields accepted; agent dispatched"
  else
    record "agent-frontmatter" FAIL "agent did not run cleanly: $(tail -2 <<<"$out" | tr '\n' ' ')"
  fi

  # --- L2: per-agent hooks: frontmatter (spec §10 assumes this works) --------
  # Verified UNSUPPORTED on 2.1.226: the hook never fires. Kept as a live check
  # so a future CLI that fixes this is detected rather than assumed.
  cat > "$PROBE_REPO/.claude/hooks/deny-read.sh" <<'HOOK'
#!/usr/bin/env bash
echo "PROBE_HOOK_DENIED: reading is blocked for this agent" >&2
exit 2
HOOK
  chmod +x "$PROBE_REPO/.claude/hooks/deny-read.sh"

  cat > "$PROBE_REPO/.claude/agents/probe-hooked.md" <<'AGENT'
---
name: probe-hooked
description: Probe agent declaring a PreToolUse hook in its own frontmatter.
tools: Read
model: haiku
hooks:
  PreToolUse:
    - matcher: "Read"
      hooks:
        - type: command
          command: "${CLAUDE_PROJECT_DIR}/.claude/hooks/deny-read.sh"
---
Read seed.txt and report its contents.
AGENT

  out="$(run_claude "Read seed.txt and tell me exactly what it contains." --agent probe-hooked)"
  if grep -q 'PROBE_HOOK_DENIED' <<<"$out"; then
    record "per-agent hooks: frontmatter" PASS "frontmatter hook fired (CLI improved — G5 may simplify)"
  else
    record "per-agent hooks: frontmatter" FAIL "did NOT fire — use the settings-hook fallback (verified below)"
  fi

  # --- L3: settings-level hooks, including over SUBAGENT tool calls ----------
  # This is the fallback G5/P2 actually rest on, so it is tested on the harder
  # path: a tool call made by a subagent, not by the main session.
  #
  # Correctness note: do NOT assert on the transcript. Whether the parent agent
  # echoes the hook's message back is a matter of prose and turn budget, not of
  # enforcement. The hook itself records that it fired; that marker is the only
  # trustworthy evidence.
  cat > "$PROBE_REPO/.claude/hooks/deny-read-marked.sh" <<HOOK
#!/usr/bin/env bash
touch "$TMP/hook-fired"
echo "PROBE_HOOK_DENIED: reading is blocked for this agent" >&2
exit 2
HOOK
  chmod +x "$PROBE_REPO/.claude/hooks/deny-read-marked.sh"

  cat > "$TMP/probe-settings.json" <<HOOKSET
{ "hooks": { "PreToolUse": [ { "matcher": "Read",
    "hooks": [ { "type": "command", "command": "$PROBE_REPO/.claude/hooks/deny-read-marked.sh" } ] } ] } }
HOOKSET

  rm -f "$TMP/hook-fired"
  run_claude "Use the Task tool with subagent_type 'probe-hooked' to read seed.txt, then report what happened." \
    --settings "$TMP/probe-settings.json" >/dev/null
  if [[ -f "$TMP/hook-fired" ]]; then
    record "settings hooks over subagents" PASS "hook intercepted a subagent's Read — G5/P2 enforceable"
  else
    record "settings hooks over subagents" FAIL "hook never fired for a subagent — ESCALATE per §11"
  fi

  # --- L4: does the hook payload identify the calling agent? ----------------
  # Spec §11 assumes it does not, and prescribes one CI job per agent. If
  # agent_type is present, one global agent-aware guard is possible instead.
  cat > "$PROBE_REPO/.claude/hooks/dump.sh" <<HOOK
#!/usr/bin/env bash
cat > "$TMP/payload.json"
exit 0
HOOK
  chmod +x "$PROBE_REPO/.claude/hooks/dump.sh"
  cat > "$TMP/dump-settings.json" <<HOOKSET
{ "hooks": { "PreToolUse": [ { "matcher": "Read",
    "hooks": [ { "type": "command", "command": "$PROBE_REPO/.claude/hooks/dump.sh" } ] } ] } }
HOOKSET

  rm -f "$TMP/payload.json"
  run_claude "Read seed.txt" --agent probe-fields --settings "$TMP/dump-settings.json" >/dev/null
  if [[ -f "$TMP/payload.json" ]] && jq -e '.agent_type' >/dev/null 2>&1 < "$TMP/payload.json"; then
    at="$(jq -r '.agent_type' < "$TMP/payload.json")"
    record "hook payload agent_type" PASS "present (agent_type=$at) — one agent-aware guard suffices"
  else
    record "hook payload agent_type" FAIL "absent — fall back to one settings file per agent"
  fi

  # --- L5: what actually constrains an agent's tools ------------------------
  # Measured semantics on this CLI, in non-interactive (-p) mode:
  #   --tools            restricts the tool SURFACE outright.
  #   --disallowedTools  hard deny.
  #   --allowedTools     permission allowlist. In -p mode an un-allowlisted
  #                      tool cannot be approved by anyone, so it is denied in
  #                      practice — but that is a property of headless mode,
  #                      not of the flag. Interactively it only pre-approves.
  #   --permission-mode dontAsk does NOT widen the allowlist.
  #
  # Detection is by SIDE EFFECT. A blocked model routinely quotes the command
  # it was told to run ("I could not run `echo X`"), so grepping the transcript
  # reports phantom executions. Only the filesystem is honest.
  bash_ran() { # extra-args...  -> 0 if bash actually executed
    local marker="$PROBE_REPO/bash-marker"
    rm -f "$marker"
    run_claude "Run this bash command exactly: touch $marker" "$@" >/dev/null
    [[ -f "$marker" ]]
  }

  if bash_ran --tools "Read"; then
    record "--tools restricts surface" FAIL "Bash executed despite --tools Read"
  else
    record "--tools restricts surface" PASS "Bash unavailable under --tools Read"
  fi

  if bash_ran --disallowedTools "Bash"; then
    record "--disallowedTools denies" FAIL "Bash executed despite being disallowed"
  else
    record "--disallowedTools denies" PASS "Bash denied"
  fi

  # Positive control. Without this, every "BLOCKED" above could equally mean
  # "the model simply declined to use Bash", and the whole section proves nothing.
  if bash_ran --allowedTools "Bash"; then
    record "allowlist positive control" PASS "Bash ran when allowlisted — the negatives above are real"
  else
    record "allowlist positive control" FAIL "Bash never ran even when allowlisted; probe cannot distinguish deny from reluctance"
  fi

  if bash_ran --permission-mode dontAsk; then
    record "dontAsk does not auto-grant" FAIL "dontAsk alone granted Bash — allowlists would be decorative"
  else
    record "dontAsk does not auto-grant" PASS "dontAsk alone does not grant Bash; the allowlist still governs"
  fi

  # --- L6: path-scoped Write guard (the shape guard-path.sh relies on) ------
  cat > "$PROBE_REPO/.claude/hooks/guard-probe.sh" <<'HOOK'
#!/usr/bin/env bash
p=$(jq -r '.tool_input.file_path // ""')
case "$p" in
  */allowed/*) exit 0 ;;
  *) echo "PROBE_GUARD_BLOCKED: $p outside allowed dir" >&2; exit 2 ;;
esac
HOOK
  chmod +x "$PROBE_REPO/.claude/hooks/guard-probe.sh"
  cat > "$TMP/guard-settings.json" <<HOOKSET
{ "hooks": { "PreToolUse": [ { "matcher": "Write",
    "hooks": [ { "type": "command", "command": "$PROBE_REPO/.claude/hooks/guard-probe.sh" } ] } ] } }
HOOKSET
  out="$(run_claude "Write a file notes.txt in the current directory containing hello." --settings "$TMP/guard-settings.json")"
  if [[ -f "$PROBE_REPO/notes.txt" ]]; then
    record "path-scoped Write guard" FAIL "write succeeded outside the allowed path"
  else
    record "path-scoped Write guard" PASS "write blocked outside the allowed path"
  fi

  # --- L7: Stop hook --------------------------------------------------------
  cat > "$PROBE_REPO/.claude/hooks/stop-probe.sh" <<HOOK
#!/usr/bin/env bash
cat > "$TMP/stop-payload.json"
exit 0
HOOK
  chmod +x "$PROBE_REPO/.claude/hooks/stop-probe.sh"
  cat > "$TMP/stop-settings.json" <<HOOKSET
{ "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "$PROBE_REPO/.claude/hooks/stop-probe.sh" } ] } ] } }
HOOKSET
  rm -f "$TMP/stop-payload.json"
  run_claude "Reply with exactly: STOP_OK" --settings "$TMP/stop-settings.json" >/dev/null
  if [[ -f "$TMP/stop-payload.json" ]]; then
    record "Stop hook" PASS "fired; in-session fast feedback available"
  else
    record "Stop hook" FAIL "did not fire — CI-step-only gating (§11 fallback)"
  fi

  # --- L8: worktree isolation ----------------------------------------------
  if grep -q -- '--worktree' <<<"$HELP" && git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    record "isolation: worktree" PASS "supported and repo is git; verify e2e in Phase 2 with bootstrap"
  else
    record "isolation: worktree" FAIL "unavailable — serialise writers per §11 fallback"
  fi

  # --- L9: cost in JSON output, for the G6 running budget -------------------
  # stdout only: run_claude folds stderr into stdout for transcript checks, and
  # a single CLI warning on stderr is enough to make the JSON unparseable.
  out="$( cd "$PROBE_REPO" && timeout 180 claude -p "Reply with exactly: COST_OK" \
            --model claude-haiku-4-5-20251001 --max-turns 4 \
            --permission-mode dontAsk --output-format json 2>/dev/null )"
  if jq -e '.total_cost_usd != null' >/dev/null 2>&1 <<<"$out"; then
    cost="$(jq -r '.total_cost_usd' <<<"$out")"
    record "cost in json output (G6)" PASS "total_cost_usd present (probe turn: \$$cost)"
  else
    record "cost in json output (G6)" FAIL "absent — G6 needs another cost source"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
mkdir -p "$OUT_DIR"
printf '%s\n' "${ROWS[@]}" | jq -s \
  --arg v "$CLI_VERSION" \
  --arg live "$LIVE" \
  --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{cli_version:$v, live_probes_run:($live=="1"), generated:$date, checks:.,
    summary:{pass:(map(select(.status=="PASS"))|length),
             fail:(map(select(.status=="FAIL"))|length),
             skip:(map(select(.status=="SKIP"))|length)}}' > "$RESULTS"

echo
echo "PASS=$pass FAIL=$fail SKIP=$skip  ->  $RESULTS"
# A failing mechanism is not a reason to abort the probe; it is a reason to
# record a fallback in .qa/DECISIONS.md before building on top of it.
[[ "$fail" -eq 0 ]] || echo "NOTE: $fail mechanism(s) failed — record a §11 fallback in .qa/DECISIONS.md before Phase 1."
exit 0
