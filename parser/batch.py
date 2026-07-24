#!/usr/bin/env python3
"""Splits multi-item "batch roundup" posts into individual per-item
candidates.

Confirmed via the live data: the sgwatchinsider channel posts ~10 watches per
message under a "[WATCH DEALS ...]" header, each numbered item tagged
inline with an availability marker:

    ✅
    (AVAILABLE)
    ✅
    (1) Rolex Submariner
    126610LN "Sub-Date"
    ...
    🏷
    S$17,700

    ❌
    SOLD
    ❌
    (2) Rolex GMT Master II
    ...

Every one of these messages contains the word "SOLD" somewhere (since older
items are kept in the roundup for reference), which trips the blanket
NOISE_PATTERNS SOLD-reject and discards the entire message — meaning this
channel's inventory was previously 100% invisible regardless of how many
items in a given post were actually still available. Splitting per-item
before classification is what makes this channel's listings visible at all.
"""
import re

BATCH_PREFIX_RE = re.compile(r'^\s*\[\s*WATCH\s+DEALS', re.I)

_ITEM_RE = re.compile(
    r'(✅\s*\(AVAILABLE\)\s*✅|❌\s*SOLD\s*❌)\s*\((\d+)\)\s*(.*?)'
    r'(?=✅\s*\(AVAILABLE\)\s*✅\s*\(\d+\)|❌\s*SOLD\s*❌\s*\(\d+\)|\Z)',
    re.S,
)


def is_batch_listing_post(text):
    return bool(text) and bool(BATCH_PREFIX_RE.match(text))


def split_batch_items(text):
    """Return [{"item_number": int, "available": bool, "body": str}, ...]
    for each numbered item found. Status (available/sold) comes directly
    from the post's own marker — the freshest signal available at scrape
    time — rather than a separate cross-message SOLD match."""
    items = []
    for status, num, body in (m.groups() for m in _ITEM_RE.finditer(text)):
        items.append({
            "item_number": int(num),
            "available": "AVAILABLE" in status,
            "body": body.strip(),
        })
    return items


def listing_key(l):
    """Unique identity for a listing dict, whether it came from a single-item
    post (c-m) or one item of a split batch post (c-m-si, since several
    listings can share the same underlying message/m in that case)."""
    base = f"{l.get('c', '')}-{l.get('m')}"
    si = l.get("si")
    return f"{base}-{si}" if si is not None else base
