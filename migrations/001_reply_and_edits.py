#!/usr/bin/env python3
"""
Migration 001 — reply links and edit tracking.

Additive only. Adds columns and an index; never drops, renames or rewrites
existing data. Safe to run repeatedly.

Why these columns:

  reply_to_message_id
      Sold detection has never worked: 6,782 "SOLD" messages produced 0
      removals. The reason is structural — sold posts are bare "SOLD!"
      replies with no brand and no price, so no amount of text matching can
      tie them to a listing. Telegram's public HTML does expose the link, as
      an <a class="tgme_widget_message_reply" href=".../<parent_id>">, and
      the scraper was simply discarding it. Measured against live channels:
      87% of SOLD messages carry a reply link, and 58% resolve to a parent
      that is a real listing already in this database.

  first_seen_at / text_updated_at / edit_count
      The scraper used INSERT OR IGNORE, so a message was captured once and
      never looked at again. A dealer editing a post to say SOLD, or cutting
      the price, was invisible. Tracking when text last changed turns edits
      into a usable signal (price-cut history) instead of a blind spot.

Run:  python3 migrations/001_reply_and_edits.py [--db path]
"""

import sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "listings.db"

# column name -> DDL type/default
COLUMNS = {
    "reply_to_message_id": "INTEGER",
    "first_seen_at":       "TEXT",
    "text_updated_at":     "TEXT",
    "edit_count":          "INTEGER NOT NULL DEFAULT 0",
}

INDEXES = {
    # Sold tracing looks up "which message replies to this listing", so the
    # useful index is on the channel + parent pair, not the parent alone.
    "idx_raw_reply_to": "CREATE INDEX IF NOT EXISTS idx_raw_reply_to "
                        "ON raw_messages(channel_handle, reply_to_message_id)",
}


def migrate(db_path=None):
    db_path = Path(db_path or DEFAULT_DB)
    if not db_path.exists():
        print(f"ERROR: no database at {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    existing = {r[1] for r in conn.execute("PRAGMA table_info(raw_messages)")}
    before = conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]

    added = []
    for name, ddl in COLUMNS.items():
        if name in existing:
            print(f"  = {name} already present, skipping")
            continue
        conn.execute(f"ALTER TABLE raw_messages ADD COLUMN {name} {ddl}")
        added.append(name)
        print(f"  + added {name} {ddl}")

    for name, ddl in INDEXES.items():
        conn.execute(ddl)
        print(f"  + index {name} ensured")

    # Backfill first_seen_at from the existing scraped_at so the column means
    # the same thing for rows captured before this migration. Only touches
    # rows where it is NULL, so re-running is a no-op.
    if "first_seen_at" in added or True:
        n = conn.execute(
            "UPDATE raw_messages SET first_seen_at = scraped_at "
            "WHERE first_seen_at IS NULL AND scraped_at IS NOT NULL"
        ).rowcount
        if n:
            print(f"  ~ backfilled first_seen_at from scraped_at on {n} row(s)")

    conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
    cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_messages)")}
    conn.close()

    print(f"\n  rows before: {before}   rows after: {after}")
    if before != after:
        print("  ERROR: row count changed — this migration must never do that.")
        return 1
    missing = set(COLUMNS) - cols
    if missing:
        print(f"  ERROR: columns still missing after migration: {missing}")
        return 1
    print("  ✅ migration 001 complete (additive, row count unchanged)")
    return 0


if __name__ == "__main__":
    db = None
    if "--db" in sys.argv:
        db = sys.argv[sys.argv.index("--db") + 1]
    sys.exit(migrate(db))
