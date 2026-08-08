#!/usr/bin/env python3
"""Precompute .qa/metrics/history.json (spec §3.1, §6.3).

This resolves the tension between P7 and risk analysis. P7 says solving agents
must not mine git history — an audited fleet retrieved fixes rather than
deriving them in 63% of successful resolutions. But risk-scout genuinely needs
history to band a change. The resolution: a plain script (no LLM, no cost) does
the mining, and the agent reads the result.

Run nightly, before anything else. risk-scout is blind without it.

Usage: scripts/qa-history.py [--days 90] [--out .qa/metrics/history.json]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOTFIX_RX = re.compile(r"\b(hotfix|revert|rollback|emergency|incident|sev[- ]?[12])\b", re.I)


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout
    except subprocess.CalledProcessError as exc:
        print(f"git {' '.join(args)} failed: {exc.stderr.strip()}", file=sys.stderr)
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--hotfix-days", type=int, default=365)
    ap.add_argument("--out", default=".qa/metrics/history.json")
    args = ap.parse_args()

    if not git("rev-parse", "--git-dir").strip():
        print("not a git repository", file=sys.stderr)
        return 1

    # A shallow clone silently yields near-empty history, which would band every
    # file as low-risk. Say so rather than emitting confident nonsense.
    shallow = Path(git("rev-parse", "--git-dir").strip() or ".git") / "shallow"
    truncated = shallow.exists()
    if truncated:
        print("WARNING: shallow clone — history is truncated and banding will be "
              "under-informed. Run this job with fetch-depth: 0.", file=sys.stderr)

    files: dict[str, dict] = defaultdict(
        lambda: {"churn_90d": 0, "commits_90d": 0, "hotfix_touches_365d": 0,
                 "open_bugs": [], "last_incident": None})

    # --- churn and commit counts over the window ---------------------------
    log = git("log", f"--since={args.days}.days", "--numstat", "--format=%H")
    for line in log.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] != "-":       # binary files show "-"
            added, deleted, path = parts
            try:
                files[path]["churn_90d"] += int(added) + int(deleted)
            except ValueError:
                continue
            files[path]["commits_90d"] += 1

    # --- hotfix / revert touches, the best cheap defect-history proxy ------
    hotfix_log = git("log", f"--since={args.hotfix_days}.days",
                     "--format=%H%x00%cI%x00%s", "--name-only")
    current_is_hotfix, current_date = False, None
    for line in hotfix_log.splitlines():
        if "\x00" in line:
            _, date, subject = line.split("\x00", 2)
            current_is_hotfix = bool(HOTFIX_RX.search(subject))
            current_date = date
        elif line.strip() and current_is_hotfix:
            f = files[line.strip()]
            f["hotfix_touches_365d"] += 1
            if current_date and (f["last_incident"] is None or current_date > f["last_incident"]):
                f["last_incident"] = current_date

    # --- open bugs, harvested from .qa/bugs/*.md ---------------------------
    for bug in Path(".qa/bugs").glob("*.md") if Path(".qa/bugs").exists() else []:
        text = bug.read_text(encoding="utf-8", errors="replace")
        comp = re.search(r"^component:\s*(\S+)", text, re.M)
        bid = re.search(r"^id:\s*(\S+)", text, re.M)
        status = re.search(r"^status:\s*(\S+)", text, re.M)
        if comp and bid and (status is None or status.group(1).lower() not in {"closed", "fixed"}):
            files[comp.group(1)]["open_bugs"].append(bid.group(1))

    # Files ranked by hotfix touches feed the `paths_touched_in_last_3_hotfixes`
    # escalator in RISK-RULES.yaml.
    recent_hotfix_paths = sorted(
        (p for p, d in files.items() if d["hotfix_touches_365d"] > 0),
        key=lambda p: files[p]["hotfix_touches_365d"], reverse=True)

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "window_days": args.days,
        "history_truncated": truncated,
        "files": dict(sorted(files.items())),
        "recent_hotfix_paths": recent_hotfix_paths[:50],
    }

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {dest}: {len(files)} file(s), "
          f"{len(recent_hotfix_paths)} with hotfix history"
          + (" [TRUNCATED HISTORY]" if truncated else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
