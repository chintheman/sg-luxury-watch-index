#!/usr/bin/env python3
"""Collapse repeat listings of the same physical watch.

35% of classified listings are the same watch posted more than once. Left
alone this inflates every volume count, and since the index weights brands by
volume, the distortion would be baked into every baseline.

WITHIN A DEALER ONLY. The original plan called for cross-channel matching on
(brand, reference, +/-2% price) as well. The data says that is wrong:

  - A dealer stock code never appears on two channels (0 of 4,437), so there
    is no evidence of the same watch being consigned to two dealers.
  - Where two dealers list the same reference, the median price spread
    between them is 36%, and only 4% of such groups agree within 2%.

Two dealers listing "Submariner 126610LN" are holding two different watches
with different years, condition and completeness. Merging them would delete
real inventory and understate the market. So cross-channel matching is
deliberately not implemented.

Matching, in order of confidence:
  1. (channel, dealer stock code)  — the dealer's own identifier. Definitive.
  2. (channel, brand, reference)   — for the 46% of listings with no stock
     code, clustered only when prices agree within PRICE_TOLERANCE_PCT, since
     a dealer may hold two of the same reference at different price points.

The group is kept, not thrown away. 506 of 1,161 reposted watches changed
price, 493 of those downwards (median -1.7%) — that is the price-cut history
Phase 6 needs, and it only exists because the same watch was seen repeatedly.
"""
from collections import defaultdict

# A repost may carry a revised price. Reposts observed in the corpus move by
# a median of 1.7%, so a 10% band captures genuine re-pricing while staying
# well inside the 36% spread that separates different watches.
PRICE_TOLERANCE_PCT = 10.0


def _key_stock(r):
    sc = r.get("stock_code")
    return ("sc", r.get("channel"), sc) if sc else None


def _key_ref(r):
    ref = r.get("ref")
    return ("ref", r.get("channel"), r.get("brand"), ref) if ref else None


def _within_tolerance(a, b):
    lo, hi = min(a, b), max(a, b)
    return lo > 0 and (hi - lo) / lo * 100 <= PRICE_TOLERANCE_PCT


def build_groups(records):
    """Cluster records into groups of the same physical watch.

    `records` are dicts with: id, channel, brand, price, date, ref, stock_code.
    Returns a list of groups, each a list of records sorted oldest first.
    """
    groups = []
    by_stock = defaultdict(list)
    leftover = []

    for r in records:
        k = _key_stock(r)
        if k:
            by_stock[k].append(r)
        else:
            leftover.append(r)
    groups.extend(by_stock.values())

    # Reference fallback: cluster only while prices stay within tolerance, so
    # a dealer holding two of the same reference at different price points
    # stays as two watches rather than being merged into one.
    by_ref = defaultdict(list)
    for r in leftover:
        k = _key_ref(r)
        if k:
            by_ref[k].append(r)
        else:
            groups.append([r])

    for bucket in by_ref.values():
        bucket = sorted(bucket, key=lambda x: x.get("price") or 0)
        cluster = [bucket[0]]
        for r in bucket[1:]:
            if _within_tolerance(cluster[-1].get("price") or 0, r.get("price") or 0):
                cluster.append(r)
            else:
                groups.append(cluster)
                cluster = [r]
        groups.append(cluster)

    return [sorted(g, key=lambda x: (x.get("date") or "", x.get("id") or 0)) for g in groups]


def summarise(group):
    """Repost/price history for one physical watch."""
    prices = [g.get("price") for g in group if g.get("price")]
    dates = [g.get("date") for g in group if g.get("date")]
    first_p, last_p = (prices[0], prices[-1]) if prices else (None, None)
    change = None
    if first_p and last_p and first_p != last_p:
        change = round((last_p - first_p) / first_p * 100, 2)
    return {
        "times_listed": len(group),
        "first_seen": dates[0] if dates else None,
        "last_seen": dates[-1] if dates else None,
        "first_price": first_p,
        "last_price": last_p,
        "price_change_pct": change,
        # Days between first and last sighting. Not time-to-sell on its own --
        # a watch still listed has simply not sold yet -- but it becomes that
        # once Phase 6 can tell "stopped being reposted" from "sold".
        "days_listed": _daydiff(dates[0], dates[-1]) if len(dates) > 1 else 0,
    }


def _daydiff(a, b):
    from datetime import datetime
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return 0


def dedupe(records):
    """Return (canonical_records, stats).

    One record survives per physical watch: the most recent sighting, since
    that carries the current asking price. Each survivor gains a `dup` summary
    of its repost history.
    """
    groups = build_groups(records)
    canonical = []
    repeated = 0
    for g in groups:
        keep = dict(g[-1])                      # newest sighting wins
        if len(g) > 1:
            repeated += len(g) - 1
            keep["dup"] = summarise(g)
        canonical.append(keep)

    stats = {
        "input": len(records),
        "output": len(canonical),
        "removed": repeated,
        "groups_with_repeats": sum(1 for g in groups if len(g) > 1),
        "removed_pct": round(100 * repeated / len(records), 1) if records else 0.0,
    }
    return canonical, stats
