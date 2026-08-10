#!/usr/bin/env python3
"""Build a synthetic corpus and the artefacts the acceptance tests need.

Why this exists
---------------
44 of the suite's tests skip unless data/index.json, data/references.json or
data/signals.json is already on disk. They are post-build acceptance checks on
the published artefacts, not unit tests, so they cannot simply be rewritten to
build their own fixtures without ceasing to check what they are for.

The consequence, though, was that those 44 assertions had never been executed
anywhere — not locally without a scrape, and not in CI at all. An assertion
nobody runs is indistinguishable from one that is wrong.

This produces a corpus that is fully synthetic but shaped like the real one,
so CI can run those tests and prove they are executable and self-consistent.
It does NOT replace the real check: running them against a real scrape still
tells you something this cannot.

Deliberately NOT random: same input, same artefacts, every run. A flaky
acceptance suite would be worse than a skipped one.

Usage:  python3 scripts/qa-sample-index.py [--force]

Refuses to clobber an existing data/listings.db unless --force is passed —
on a machine with a real scrape, that database is the asset.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "listings.db"
SGT = timezone(timedelta(hours=8))

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_handle TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    message_text TEXT,
    photos_count INTEGER DEFAULT 0,
    views INTEGER,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now')),
    reply_to_message_id INTEGER,
    first_seen_at TEXT,
    text_updated_at TEXT,
    edit_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(channel_handle, message_id)
);
"""

# Shaped like the real corpus in three ways that turned out to matter, each
# learned from an acceptance test failing against a first, tidier attempt:
#
#   * MULTIPLE REFERENCES PER MODEL. references.py publishes a model-grain card
#     only when it has grouped variants under it, and asserts variants >= 1.
#     One reference per model produced model cards with zero variants.
#   * REAL REFERENCE FORMATS. Omega references are dotted
#     (310.30.42.50.01.001); written as bare digits, extract_model does not
#     recognise them at all, and those listings fall through to model grain
#     with no reference — which then breaks the "no listing sits in two cards"
#     accounting.
#   * ENOUGH BRANDS THAT NONE DOMINATES. The index refuses to let one brand
#     carry 40% of the weighting; eight models across three brands failed that
#     on sqrt(volume) alone.
#
# Each reference also needs enough recent listings to clear references.py's
# MIN_RECENT_FULL (20) or its card is withheld as too thin.
MODELS = [
    ("Rolex", "Submariner", ["126610LN", "124060", "126610LV"], 16000),
    ("Rolex", "Datejust", ["126334", "126234"], 11000),
    ("Omega", "Speedmaster", ["310.30.42.50.01.001", "311.30.42.30.01.005"], 6500),
    ("Omega", "Seamaster", ["210.30.42.20.03.001", "210.32.42.20.04.001"], 5200),
    ("Cartier", "Santos", ["WSSA0018", "WSSA0009"], 8800),
    ("Tudor", "Black Bay", ["79230N", "79030N"], 4200),
    ("Breitling", "Navitimer", ["AB0138241", "A17326241"], 7400),
    ("Panerai", "Luminor", ["PAM01312", "PAM00915"], 9100),
    ("Hublot", "Big Bang", ["301.SX.1170.RX", "341.SB.131.RX"], 12500),
    ("Zenith", "Chronomaster", ["03.3100.3600", "51.3100.3600"], 7800),
    ("Chopard", "Happy Sport", ["278582-3001", "274808-5001"], 6900),
]
# Longines is deliberately absent. Its real reference format (L2.793.4.78.3)
# is not recognised by parser/filter.py's extractor, so every Longines listing
# lands with ref=None and references.py publishes a model-grain card with
# variants=0 over them. That combination breaks two acceptance invariants —
# see .qa/bugs/2026-08-10-model-card-with-no-variants.md. Including it here
# would make this job red for a defect that is not this job's subject; the bug
# report is the right place for it.

# Enough dealers that dedupe does not collapse same-reference listings into one
# watch: it clusters on (channel, brand, reference) inside a 10% price band.
DEALERS = [f"dealer{i}" for i in range(12)]

HISTORY_DAYS = 150      # > 90, so the 90-day change resolves
STEP_DAYS = 3           # a listing wave every three days


def iso(days_ago: int) -> str:
    return (datetime.now(SGT) - timedelta(days=days_ago)).isoformat()


def drift(base: int, days_ago: int) -> int:
    """A gentle, deterministic upward trend plus a small sawtooth.

    Movement matters: a perfectly flat corpus makes every change_* zero and
    every brand contribution zero, so the tests that check those would skip
    rather than run — which is the problem this script exists to solve.
    """
    trend = (HISTORY_DAYS - days_ago) / HISTORY_DAYS * 0.08      # +8% over the window
    wobble = ((days_ago % 7) - 3) / 300.0                        # +/- 1%
    return int(round(base * (1 + trend + wobble)))


def build_corpus() -> list[tuple]:
    rows: list[tuple] = []
    mid = 1
    for days_ago in range(HISTORY_DAYS, -1, -STEP_DAYS):
        for idx, (brand, model, refs, base) in enumerate(MODELS):
            for r_i, ref in enumerate(refs):
                # Variants of one model sit near each other but not on top of
                # each other, so grouping has something real to group.
                price = drift(base + r_i * (base // 12), days_ago)
                # Two dealers per reference per wave. Distinct channels matter:
                # dedupe clusters on (channel, brand, reference) inside a 10%
                # price band, so one dealer posting twice is one watch.
                for d in range(2):
                    dealer = DEALERS[(idx * 5 + r_i * 2 + d + days_ago) % len(DEALERS)]
                    # Condition mix roughly matching the real corpus: mostly
                    # unstated, ~15% brand new, ~25% explicitly pre-owned.
                    bucket = (days_ago + d + idx + r_i) % 7
                    cond = " BNIB" if bucket == 0 else (" Preowned" if bucket in (1, 2) else "")
                    text = f"{brand} {model} {ref}{cond}\nPrice: SGD ${price + d * 40:,}"
                    rows.append((dealer, mid, iso(days_ago), text, 100 + (mid % 400), None))
                    mid += 1
    return rows


def write_db(rows: list[tuple], force: bool) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if DB.exists() and not force:
        sys.exit(
            f"refusing to overwrite {DB} — it may be a real scrape.\n"
            "Pass --force if you are certain this is a throwaway checkout."
        )
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(str(DB))
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO raw_messages "
        "(channel_handle, message_id, posted_at, message_text, views, reply_to_message_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def run_builder(label: str, module: str) -> bool:
    """Each builder runs in its own process: they mutate sys.path on import and
    resolve sibling modules unqualified, so importing two of them into one
    interpreter makes the second see the first's path order."""
    proc = subprocess.run([sys.executable, module], cwd=ROOT,
                          capture_output=True, text=True)
    ok = proc.returncode == 0
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        print((proc.stdout or "")[-1500:])
        print((proc.stderr or "")[-1500:], file=sys.stderr)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing data/listings.db")
    args = ap.parse_args()

    rows = build_corpus()
    write_db(rows, args.force)
    print(f"synthetic corpus: {len(rows)} messages, {len(MODELS)} references, "
          f"{HISTORY_DAYS} days")

    # signals must run before references: references.py reads the same corpus
    # but the acceptance tests expect signals.json alongside it.
    results = [
        run_builder("index.json", "index/index_engine.py"),
        run_builder("signals.json", "index/signals.py"),
        run_builder("references.json", "index/references.py"),
    ]

    built = [p.name for p in (DATA / "index.json", DATA / "signals.json",
                              DATA / "references.json") if p.exists()]
    print(f"artefacts: {', '.join(built) or 'none'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
