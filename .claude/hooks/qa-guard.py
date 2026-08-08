#!/usr/bin/env python3
"""G5 separation-of-duties guard + P2 oracle blindness + G4 snapshot ban.

Runs as a settings-level PreToolUse hook. Reads the hook payload on stdin,
adjudicates against .qa/policy.yaml, and exits 2 to block (stderr is fed back
to the model as the reason).

Why one guard rather than one CI job per agent (spec §11's fallback): the
PreToolUse payload on this CLI carries `agent_type`, so a single guard can tell
who is calling. See .qa/DECISIONS.md D-002. The spec assumed it could not, and
warned such a guard would fail open or closed — so the policy here fails CLOSED
by construction:

  * agent_type present but unknown  -> deny all writes
  * agent_type absent (main session) -> orchestrator; global rules only
  * policy file missing/unparseable  -> deny the call outright

A guard that cannot read its policy must never wave traffic through.
"""
import json
import os
import re
import sys
from pathlib import Path

BLOCK, ALLOW = 2, 0

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}


def die_block(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"[qa-guard] BLOCKED: {msg}", file=sys.stderr)
    sys.exit(BLOCK)


def glob_to_re(pat: str) -> re.Pattern:
    """Translate a glob to a regex. fnmatch has no '**', and '*' must not cross
    a path separator, so neither fnmatch nor a naive replace is correct here."""
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif pat.startswith("**", i):
            out.append(".*"); i += 2
        elif pat[i] == "*":
            out.append("[^/]*"); i += 1
        elif pat[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(pat[i])); i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(path: str, patterns) -> bool:
    return any(glob_to_re(p).match(path) for p in (patterns or []))


def rel_to_repo(p: str, repo: Path) -> str:
    """Normalise to a repo-relative POSIX path.

    Absolute paths outside the repo are returned unchanged so they can never
    accidentally satisfy a repo-relative allow-glob: writing to /etc/passwd must
    not match 'src/**'.
    """
    if not p:
        return ""
    try:
        # Resolve relative paths against the REPO, not the process CWD. A hook
        # does not necessarily run from the repo root, and resolving "src/x.py"
        # against the wrong base silently changes which rules match.
        base = p if os.path.isabs(p) else os.path.join(repo, p)
        return os.path.relpath(os.path.realpath(base), repo).replace(os.sep, "/")
    except (ValueError, OSError):
        return p


def log_violation(repo: Path, record: dict) -> None:
    """Record rejections. §5 G5: a rising count means an agent's prompt is
    fighting its permissions and needs rewriting — that signal only exists if
    the rejections are written down."""
    try:
        d = repo / ".qa" / "metrics" / "violations"
        d.mkdir(parents=True, exist_ok=True)
        pr = os.environ.get("QA_PR", "local")
        with open(d / f"{pr}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # never let logging failure change the verdict


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        die_block("unparseable hook payload")

    repo = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".").resolve()

    policy_path = repo / ".qa" / "policy.yaml"
    try:
        import yaml
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # missing file, bad YAML, no PyYAML
        die_block(
            f"cannot load {policy_path} ({exc}). Refusing the call: an "
            "unreadable policy must fail closed, not open."
        )

    agent = payload.get("agent_type")           # absent => main session
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    defaults = policy.get("defaults") or {}
    agents = policy.get("agents") or {}

    ctx = {"agent": agent or "(orchestrator)", "tool": tool}

    # ---- Global rules: apply to every caller, orchestrator included --------
    if tool == "Bash":
        cmd = ti.get("command", "") or ""
        for rx in defaults.get("bash_deny") or []:
            if re.search(rx, cmd):
                log_violation(repo, {**ctx, "rule": "defaults.bash_deny", "detail": cmd[:400]})
                die_block(
                    f"command matches a globally denied pattern ({rx}).\n"
                    "Snapshot updating and edits to the gates/policy are denied for every "
                    "agent (spec P8/G4). If a snapshot is genuinely stale, a human updates it."
                )

    # Path a write is targeting, if any.
    target = rel_to_repo(ti.get("file_path") or ti.get("notebook_path") or "", repo)

    if tool in WRITE_TOOLS and target:
        if matches_any(target, defaults.get("write_deny_always")):
            log_violation(repo, {**ctx, "rule": "defaults.write_deny_always", "detail": target})
            die_block(
                f"'{target}' is immutable from inside a session. The gates, the policy and "
                "the workflows are the referee — an agent may not edit them mid-game."
            )

    # ---- Orchestrator: no per-agent duties to separate --------------------
    if agent is None:
        return ALLOW

    rules = agents.get(agent)
    if rules is None:
        # Fail closed. Reads stay permitted so an unregistered agent can still
        # explain itself; anything that mutates state is refused.
        if tool in WRITE_TOOLS or tool == "Bash":
            log_violation(repo, {**ctx, "rule": "unknown_agent", "detail": target or tool})
            die_block(
                f"agent '{agent}' is not listed in .qa/policy.yaml. Unknown agents get no "
                "write or shell access. Add an explicit entry to the P4 table first."
            )
        return ALLOW

    # ---- Per-agent Bash denials (P7: no retrieving the answer) ------------
    if tool == "Bash":
        cmd = ti.get("command", "") or ""
        for rx in rules.get("bash_deny") or []:
            if re.search(rx, cmd):
                log_violation(repo, {**ctx, "rule": "bash_deny", "detail": cmd[:400]})
                die_block(
                    f"'{agent}' may not run this command (matched {rx}).\n"
                    "Analysts get history from .qa/metrics/history.json, which a plain script "
                    "precomputes; solving agents get no history at all (spec P7)."
                )

    # ---- Per-agent read blindness (P2) ------------------------------------
    # §7.2: blocking Read alone is not enough. Grep with content output returns
    # file bodies and WebFetch on a PR URL returns the whole diff, so the same
    # matcher covers every content-returning tool.
    if tool in READ_TOOLS:
        probe = rel_to_repo(ti.get("file_path") or ti.get("path") or ti.get("pattern") or "", repo)
        raw = ti.get("file_path") or ti.get("path") or ti.get("pattern") or ""
        for candidate in {probe, str(raw)}:
            if candidate and matches_any(candidate, rules.get("read_deny")):
                log_violation(repo, {**ctx, "rule": "read_deny", "detail": candidate})
                die_block(
                    f"'{agent}' may not read '{candidate}'.\n"
                    "This agent derives intended behaviour from specifications only. Reading the "
                    "implementation would make it encode current behaviour as correct — which is "
                    "the exact failure this role exists to prevent (spec P2). Use the ticket, "
                    "docs/, the API schema, and public type signatures instead. If the spec does "
                    "not determine the answer, that is an Ambiguity and belongs in your output."
                )

    if tool == "WebFetch":
        url = str(ti.get("url", ""))
        for frag in rules.get("url_deny") or []:
            if frag in url:
                log_violation(repo, {**ctx, "rule": "url_deny", "detail": url})
                die_block(
                    f"'{agent}' may not fetch '{url}' (matched '{frag}').\n"
                    "Fetching a pull request, commit or blob URL returns the diff — the same "
                    "implementation information the read rules deny. Do not route around it."
                )

    # ---- Per-agent write scoping (the P4 table) ---------------------------
    if tool in WRITE_TOOLS:
        if not target:
            die_block(f"'{agent}' attempted a write with no resolvable target path")
        if matches_any(target, rules.get("write_deny")):
            log_violation(repo, {**ctx, "rule": "write_deny", "detail": target})
            die_block(
                f"'{agent}' is explicitly forbidden from writing '{target}'.\n"
                "Separation of duties: the agent that fixes code may not also edit the test "
                "that judges the fix (spec P4). If you believe the test is wrong, write "
                ".qa/disputes/<id>.md citing the oracle proposition it misencodes, and stop."
            )
        allow = rules.get("write_allow")
        if not allow:
            log_violation(repo, {**ctx, "rule": "no_write_allow", "detail": target})
            die_block(f"'{agent}' has no write permissions at all.")
        if not matches_any(target, allow):
            log_violation(repo, {**ctx, "rule": "write_allow", "detail": target})
            die_block(
                f"'{agent}' may not write '{target}'.\n"
                f"Permitted: {', '.join(allow)}.\n"
                "This is the P4 separation-of-duties table, not a misconfiguration — do not "
                "ask for it to be relaxed. If your deliverable does not fit these paths, you "
                "are being asked for the wrong artefact."
            )

    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
