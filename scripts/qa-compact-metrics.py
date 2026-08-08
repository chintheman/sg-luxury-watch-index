#!/usr/bin/env python3
"""Compact per-PR metric files into a rolling corpus (spec §4, §6.3 step 6).

Spec §4 is emphatic that metrics are ONE FILE PER PR, not a shared append-only
log: "Shared append-only .jsonl files conflict on every parallel merge, and the
calibration corpus rots into merge-conflict resolution within a month."

So the per-PR files are the source of truth during the day, and this job folds
them into a single corpus nightly — when nothing else is writing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

QA = Path(".qa/metrics")


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    corpus_path = QA / "corpus.json"
    corpus = load(corpus_path) or {"verdicts": [], "costs": [], "compacted_at": None}
    seen = {v.get("pr") for v in corpus["verdicts"]}

    for p in sorted((QA / "verdicts").glob("*.json")) if (QA / "verdicts").exists() else []:
        d = load(p)
        if d and d.get("pr") not in seen:
            corpus["verdicts"].append(d)
            seen.add(d.get("pr"))

    cost_seen = {c.get("pr") for c in corpus["costs"]}
    for p in sorted((QA / "cost").glob("*.json")) if (QA / "cost").exists() else []:
        if p.name.endswith(".stop.json"):
            continue
        d = load(p)
        if d and d.get("pr") not in cost_seen:
            corpus["costs"].append({"pr": d.get("pr"), "total_usd": d.get("total_usd")})
            cost_seen.add(d.get("pr"))

    corpus["compacted_at"] = datetime.now(timezone.utc).isoformat()
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    print(f"corpus: {len(corpus['verdicts'])} verdict(s), {len(corpus['costs'])} cost record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
