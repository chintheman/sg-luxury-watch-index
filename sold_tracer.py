#!/usr/bin/env python3
"""
Sold Tracer — cross-references SOLD messages against active listings.

Strategies (in priority order):
  1. Item number match (GML#### → same item number in active listing)
  2. Brand + model match (same channel, same brand/model, SOLD posted AFTER listing)

(Batch "[WATCH DEALS ...]" roundup posts are handled separately — see
parser/batch.py — since each item's own status marker is a more reliable
sold signal than cross-referencing a later SOLD message.)

Output: data/removed.json — {removed_ids: [...], reasons: {id: reason}}
"""

import sqlite3, json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from parser.filter import extract_price, extract_condition
from parser.filter import extract_model as filt_extract_model
from parser.brands import match_brand as extract_brand_local
from parser.batch import listing_key

SGT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "listings.db"
REMOVED_OUT = ROOT / "data" / "removed.json"
LOOKBACK_DAYS = 90


# ── Item number extraction ────────────────────────────────────────────────
ITEM_RE = re.compile(r'GML\d+', re.I)
ITEM_RE_GENERIC = re.compile(r'(?:item|ref|listing)\s*(?:no|#|number|:)?\s*[:\-]?\s*([A-Z0-9]{3,20})', re.I)


def extract_item_number(text):
    """Extract item/reference number like GML3589."""
    m = ITEM_RE.search(text)
    if m:
        return m.group(0).upper()
    m = ITEM_RE_GENERIC.search(text)
    if m:
        return m.group(1).upper()
    return None


# ── Main ──────────────────────────────────────────────────────────────────

def trace_sold_messages(db_path=None, listings=None, listings_path=None):
    """Cross-reference SOLD messages against the currently active listing set.

    `listings` should be the in-memory list of listings about to be exported
    THIS run (same shape as listings.json entries) — matching against that,
    rather than the on-disk listings.json from the previous run, is what lets
    a listing that's scraped and marked sold within the same run get caught.
    Falls back to reading listings_path from disk (previous run's snapshot)
    when `listings` isn't supplied, e.g. for standalone/CLI use.
    """
    db_path = Path(db_path or DB)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Active listings: prefer the freshly-computed in-memory set for this run
    if listings is not None:
        active = listings
    else:
        listings_path = Path(listings_path or ROOT / "data" / "listings.json")
        active = json.loads(listings_path.read_text()) if listings_path.exists() else []

    # IDs of listings actually about to be published — only messages in this
    # set can ever be worth "removing", so the match pool below is scoped to
    # it directly rather than every non-SOLD message in the lookback window.
    # (Previously the match pool was every raw message from the last 90 days,
    # which meant most matches were against listings that had already aged
    # out of the 14-day display window regardless — wasted work, and a
    # source of stale/coincidental brand+price false-positive matches.)
    #
    # Split-batch sub-items (listing_key() returns "c-m-si" for those) never
    # match a raw message's plain "c-m" id below, so they're intentionally
    # excluded from this cross-message matching pool — their own SOLD status
    # already comes straight from the post itself (see parser/batch.py) and
    # is refreshed every time the dealer reposts, so cross-referencing them
    # against separate SOLD messages here would be redundant.
    current_ids = {listing_key(l) for l in active}

    # Get all messages (last LOOKBACK_DAYS) — SOLD messages themselves are
    # still searched across the full window, since a sold post can lag the
    # original listing by weeks.
    cutoff = (datetime.now(SGT) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    all_msgs = conn.execute(
        "SELECT id, channel_handle, message_id, posted_at, message_text "
        "FROM raw_messages WHERE posted_at >= ? ORDER BY posted_at DESC",
        (cutoff,)
    ).fetchall()

    # Separate SOLD messages from active candidates
    sold_msgs = []
    active_candidates = []
    for m in all_msgs:
        text = m["message_text"] or ""
        if re.search(r'\bSOLD\b', text, re.I):
            sold_msgs.append(m)
        elif f"{m['channel_handle']}-{m['message_id']}" in current_ids:
            active_candidates.append(m)

    # Active by item number
    active_by_item = defaultdict(list)
    for m in active_candidates:
        item = extract_item_number(m["message_text"] or "")
        if item:
            active_by_item[(m["channel_handle"] or "").lower(), item].append(m)

    # Active by (channel, brand)
    active_by_brand = defaultdict(list)
    for m in active_candidates:
        brand = extract_brand_local(m["message_text"] or "")
        if brand:
            active_by_brand[(m["channel_handle"] or "").lower(), brand].append(m)

    removed = {}  # listing_id → reason
    strategies = {"item_number": 0, "brand_model": 0}

    for sm in sold_msgs:
        s_text = sm["message_text"] or ""
        s_channel = (sm["channel_handle"] or "").lower()
        s_date = sm["posted_at"][:10] if sm["posted_at"] else ""

        # ── Strategy 1: Item number match ──
        item = extract_item_number(s_text)
        if item:
            candidates = active_by_item.get((s_channel, item), [])
            for c in candidates:
                c_id = f"{c['channel_handle']}-{c['message_id']}"
                if c_id not in removed:
                    if c["posted_at"] and c["posted_at"][:10] <= s_date:
                        removed[c_id] = f"Item {item} sold ({sm['message_id']})"
                        strategies["item_number"] += 1

        # Strategy 2 (cross-message batch-SOLD parsing) was removed: every
        # "[WATCH DEALS ...]" batch post contains the word "SOLD" somewhere
        # (older items are kept for reference), so it always landed in
        # sold_msgs above and never in active_candidates — this strategy
        # could never find a batch listing to match against, confirmed
        # against the full live corpus (0/95 batch posts ever appeared in
        # active_candidates). parser/batch.py now splits these posts into
        # per-item listings directly from each item's own status marker,
        # which makes this cross-message approach unnecessary as well as
        # non-functional.

        # ── Strategy 3: Brand + model match (same channel, sold after listing) ──
        s_brand = extract_brand_local(s_text)
        if s_brand and not item:  # only if strategy 1 didn't apply
            candidates = active_by_brand.get((s_channel, s_brand), [])
            # Try to extract model from SOLD message
            s_model, _ = filt_extract_model(s_text, s_brand)

            for c in candidates:
                c_id = f"{c['channel_handle']}-{c['message_id']}"
                if c_id in removed:
                    continue
                c_text = c["message_text"] or ""
                c_price = extract_price(c_text)

                if c["posted_at"] and c["posted_at"][:10] <= s_date:
                    # If we have a model match, high confidence
                    if s_model:
                        c_model, _ = filt_extract_model(c_text, s_brand)
                        if c_model and s_model.lower() == c_model.lower():
                            removed[c_id] = f"Brand+model match: {s_brand} {s_model} sold ({sm['message_id']})"
                            strategies["brand_model"] += 1
                    # No model match but same brand — only match if price range matches
                    elif c_price:
                        s_price = extract_price(s_text)
                        if s_price and abs(s_price - c_price) / max(s_price, c_price) < 0.15:
                            removed[c_id] = f"Brand+price match: {s_brand} ${s_price} sold ({sm['message_id']})"
                            strategies["brand_model"] += 1

    conn.close()

    # Build output — since active_candidates was already scoped to
    # current_ids above, every match here is already a real candidate, but
    # keep the explicit filter as a guard in case that invariant ever changes.
    matched_removals = {k: v for k, v in removed.items() if k in current_ids}
    removal_ids = list(matched_removals.keys())

    output = {
        "generated": datetime.now(SGT).isoformat(),
        "total_removed": len(removal_ids),
        "strategies": strategies,
        "removed_ids": removal_ids,
        "reasons": matched_removals,
    }

    REMOVED_OUT.write_text(json.dumps(output, indent=2))
    print(f"Sold tracer: removed {len(removal_ids)} listings")
    print(f"  Item number matches: {strategies['item_number']}")
    print(f"  Brand/model matches: {strategies['brand_model']}")

    return output


if __name__ == "__main__":
    trace_sold_messages()
