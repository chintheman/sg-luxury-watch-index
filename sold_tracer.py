#!/usr/bin/env python3
"""
Sold tracer — decide which published listings have already sold.

The previous implementation matched SOLD messages to listings by brand, model
and price. It found nothing, ever: 6,782 SOLD messages produced 0 removals.
That was structural rather than a tuning problem. Sold posts are bare
"SOLD!" replies — 0% carry a brand, 0% carry a price — so there is nothing in
their text to match on. All the heuristics have been removed.

Two signals replace them, both from the ingestion work in migration 001:

  1. REPLY LINK (primary). Telegram exposes the parent of a reply in its
     public HTML, and the scraper now stores it. A SOLD message replying to a
     listing is an explicit, dealer-authored statement that that listing sold.
     Chains are followed, because dealers frequently reply "SOLD!" to their
     own previous "SOLD!" — 2,597 of 2,713 reply links point at another sold
     notice rather than at a listing.

  2. EDIT (secondary). Dealers also mark a sale by editing the listing itself.
     The scraper now re-reads recent messages and records when a text changed,
     so a listing that gains the word SOLD after first being seen is treated
     as sold.

     Caveat, deliberately enforced in code: the first scrape after migration
     001 also CORRECTED text on every reply message (they previously stored
     the quoted parent's text). Those corrections are indistinguishable from
     genuine edits at the row level, so edits stamped during the migration
     window are ignored outright rather than being trusted as dealer activity.

Output: data/removed.json — removed_ids, reasons, and time-to-sell samples.
"""

import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from parser.batch import listing_key

SGT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "listings.db"
REMOVED_OUT = ROOT / "data" / "removed.json"

SOLD_RE = re.compile(r"\bSOLD\b", re.I)

# How far to follow a chain of "SOLD!" replying to "SOLD!" before giving up.
MAX_CHAIN_HOPS = 6

# Edits recorded inside this window are migration artefacts, not dealer
# activity — see the module docstring. Anything from migration 001's backfill.
MIGRATION_EDIT_WINDOW = ("2026-08-03T00:00", "2026-08-03T23:59")


def _is_migration_artifact(stamp):
    if not stamp:
        return False
    lo, hi = MIGRATION_EDIT_WINDOW
    return lo <= stamp[:16] <= hi


def _days_between(a, b):
    try:
        da = datetime.fromisoformat((a or "").replace("Z", "+00:00"))
        db = datetime.fromisoformat((b or "").replace("Z", "+00:00"))
        return (db - da).days
    except (ValueError, TypeError):
        return None


def trace_sold_messages(db_path=None, listings=None, listings_path=None):
    """Return {removed_ids, reasons, strategies, time_to_sell, ...}.

    `listings` is this run's in-memory candidate set, so a listing scraped and
    marked sold in the same run is still caught.
    """
    db_path = Path(db_path or DB)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    if listings is None:
        listings_path = Path(listings_path or ROOT / "data" / "listings.json")
        listings = json.loads(listings_path.read_text()) if listings_path.exists() else []

    # Only listings about to be published can be worth removing.
    current = {}
    for l in listings:
        current[(l.get("c"), l.get("m"))] = listing_key(l)

    rows = list(conn.execute(
        "SELECT channel_handle, message_id, posted_at, message_text, "
        "       reply_to_message_id, edit_count, text_updated_at, first_seen_at "
        "FROM raw_messages"
    ))
    conn.close()

    by_id = {(r["channel_handle"], r["message_id"]): r for r in rows}

    removed = {}
    strategies = {"reply_link": 0, "edited_to_sold": 0}
    time_to_sell = []

    # ── 1. Reply links ──
    for r in rows:
        if not r["reply_to_message_id"] or not SOLD_RE.search(r["message_text"] or ""):
            continue
        # Walk the chain: dealers reply SOLD to their own previous SOLD.
        target = (r["channel_handle"], r["reply_to_message_id"])
        for _ in range(MAX_CHAIN_HOPS):
            parent = by_id.get(target)
            if parent is None:
                target = None
                break
            if not SOLD_RE.search(parent["message_text"] or ""):
                break                      # reached something that is not a sold notice
            if not parent["reply_to_message_id"]:
                target = None
                break
            target = (parent["channel_handle"], parent["reply_to_message_id"])
        else:
            target = None

        if not target or target not in current:
            continue
        lid = current[target]
        if lid in removed:
            continue
        removed[lid] = f"Dealer replied SOLD to this listing (msg {r['message_id']})"
        strategies["reply_link"] += 1

        parent = by_id.get(target)
        days = _days_between(parent["posted_at"], r["posted_at"]) if parent else None
        if days is not None and 0 <= days <= 365:
            time_to_sell.append(days)

    # ── 2. Listings edited to say SOLD ──
    for key, lid in current.items():
        if lid in removed:
            continue
        r = by_id.get(key)
        if r is None or not r["edit_count"]:
            continue
        if not SOLD_RE.search(r["message_text"] or ""):
            continue
        if _is_migration_artifact(r["text_updated_at"]):
            continue                        # a text correction, not a dealer edit
        removed[lid] = "Listing was edited to say SOLD"
        strategies["edited_to_sold"] += 1
        days = _days_between(r["first_seen_at"], r["text_updated_at"])
        if days is not None and 0 <= days <= 365:
            time_to_sell.append(days)

    time_to_sell.sort()

    def _pct(p):
        return time_to_sell[int(len(time_to_sell) * p)] if time_to_sell else None

    output = {
        "generated": datetime.now(SGT).isoformat(),
        "total_removed": len(removed),
        "strategies": strategies,
        "removed_ids": list(removed.keys()),
        "reasons": removed,
        "time_to_sell": {
            "samples": len(time_to_sell),
            "median_days": _pct(0.5),
            "p25_days": _pct(0.25),
            "p75_days": _pct(0.75),
        },
    }
    REMOVED_OUT.parent.mkdir(parents=True, exist_ok=True)
    REMOVED_OUT.write_text(json.dumps(output, indent=2))
    print(f"Sold tracer: {len(removed)} listing(s) marked sold "
          f"({strategies['reply_link']} by reply link, "
          f"{strategies['edited_to_sold']} by edit)")
    if time_to_sell:
        print(f"  Time to sell: median {_pct(0.5)}d "
              f"(p25 {_pct(0.25)}d, p75 {_pct(0.75)}d, n={len(time_to_sell)})")
    return output


if __name__ == "__main__":
    trace_sold_messages()
