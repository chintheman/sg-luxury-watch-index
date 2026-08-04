#!/usr/bin/env python3
"""Per-reference price aggregates — the "what's it worth" layer.

The composite index answers "is the market moving". Nobody buys the market.
They buy a specific reference, and the question they actually have is whether
the price in front of them is fair. That question is answerable here because
asking prices within a single reference are tight: across references with
enough volume the interquartile range is typically ±8% of the median.

Everything is computed per (brand, reference) over the FULL corpus, not the
14-day publishing window in export_pipeline.py — the whole point is history.

Two rules this module exists to enforce:

  * Attributes are consensus, never per-listing. For Rolex 126334 the parser
    reads "Material: Stainless Steel & White Gold" inconsistently and yields
    two-tone (107), steel (15), white gold (9) and null (39) for one watch
    whose material is fixed. Taking the mode and publishing its backing count
    is honest; segmenting a card by the per-listing value is not.

  * A range is never shown without its sample size. A fair-price band is a
    claim about the market, and the reader needs to know how much market is
    behind it.

Output: data/references.json
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))
sys.path.insert(0, str(ROOT / "index"))

from signals import load_rows, parse_listings, dist, _days, SOLD_RE, MAX_CHAIN_HOPS, MAX_SELL_DAYS  # noqa: E402
from dedupe import build_groups, summarise  # noqa: E402
from filter import is_junk_ref  # noqa: E402

SGT = timezone(timedelta(hours=8))
OUT = ROOT / "data" / "references.json"

# The window a "fair asking price" describes. Long enough to gather a sample
# in a market this thin, short enough that it still describes today.
RECENT_DAYS = 90

# Publishing tiers. 20 recent listings puts roughly 5 in each quartile, which
# is the point at which an IQR stops being an artefact of one or two dealers.
MIN_RECENT_FULL = 20
MIN_RECENT_LIMITED = 10

# A monthly point built on one or two listings is a single dealer's asking
# price drawn as a market level. Suppress rather than plot.
MIN_PER_MONTH = 3
MIN_PER_YEAR = 3

# Confirmed sales are scarce corpus-wide (~109, 2.4% of watches), so a
# per-reference figure is thinner still. Same withholding principle as
# signals.MIN_BRAND_SALES: omit the field rather than publish an n=1 "median".
MIN_SALES_PER_REF = 3
MIN_REPOSTS_PER_REF = 5


def slugify(brand, ref):
    """A URL-safe identity for a reference.

    Brand-prefixed because bare references collide: 9 reference tokens in this
    corpus are claimed by more than one brand.
    """
    s = f"{brand}-{ref}".lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _consensus(values):
    """Modal value plus how many listings back it, or None if never stated.

    None means "not stated" — never "no". See parser/attributes.py.
    """
    vals = [v for v in values if v is not None and v != ""]
    if not vals:
        return None
    value, count = Counter(vals).most_common(1)[0]
    return {"value": value, "n": count, "of": len(vals)}


def build_references():
    rows = load_rows()
    listings = parse_listings(rows, with_attributes=True)
    by_id = {(r["channel_handle"], r["message_id"]): r for r in rows}

    today = datetime.now(SGT).date()
    recent_cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()

    # ── Group the corpus by reference ──
    by_ref = defaultdict(list)
    with_ref = 0
    for L in listings.values():
        if not L.get("ref"):
            continue
        # Phase 0 rejects these at extraction; assert rather than trust.
        if is_junk_ref(L["ref"]):
            continue
        with_ref += 1
        by_ref[(L["brand"], L["ref"])].append(L)

    # ── Confirmed sales per reference, from dealer SOLD replies ──
    sales_by_ref = defaultdict(list)
    for r in rows:
        if not r["reply_to_message_id"] or not SOLD_RE.search(r["message_text"] or ""):
            continue
        target = (r["channel_handle"], r["reply_to_message_id"])
        for _ in range(MAX_CHAIN_HOPS):
            parent = by_id.get(target)
            if parent is None:
                target = None
                break
            if not SOLD_RE.search(parent["message_text"] or ""):
                break
            if not parent["reply_to_message_id"]:
                target = None
                break
            target = (parent["channel_handle"], parent["reply_to_message_id"])
        else:
            target = None
        if not target or target not in listings:
            continue
        L = listings[target]
        if not L.get("ref"):
            continue
        d = _days(L["posted_at"], r["posted_at"])
        if d is None or not (0 <= d <= MAX_SELL_DAYS):
            continue
        sales_by_ref[(L["brand"], L["ref"])].append(d)

    # ── Repost / price-cut behaviour per reference ──
    cuts_by_ref = defaultdict(list)
    reposts_by_ref = Counter()
    spans_by_ref = defaultdict(list)
    for g in build_groups(list(listings.values())):
        if len(g) < 2:
            continue
        last = g[-1]
        if not last.get("ref"):
            continue
        key = (last["brand"], last["ref"])
        s = summarise(g)
        reposts_by_ref[key] += 1
        spans_by_ref[key].append(s["days_listed"])
        if s["price_change_pct"] is not None and s["price_change_pct"] < 0:
            cuts_by_ref[key].append(s["price_change_pct"])

    references = []
    rejected_thin = 0
    for (brand, ref), recs in by_ref.items():
        recs.sort(key=lambda r: r["date"])
        recent = [r for r in recs if r["date"] >= recent_cutoff]
        if len(recent) < MIN_RECENT_LIMITED:
            rejected_thin += 1
            continue

        prices = sorted(r["price"] for r in recent)
        q1 = prices[len(prices) // 4]
        q3 = prices[3 * len(prices) // 4]
        med = median(prices)

        # ── Monthly medians, thin months suppressed ──
        by_month = defaultdict(list)
        for r in recs:
            by_month[r["date"][:7]].append(r["price"])
        monthly = [
            {"month": m, "median": int(median(v)), "n": len(v)}
            for m, v in sorted(by_month.items()) if len(v) >= MIN_PER_MONTH
        ]

        # ── Asking price by stated year of manufacture ──
        # The strongest within-reference driver: same reference, 2018 stock
        # asks materially less than 2026 stock. Note `year` is dealer-stated,
        # not a verified manufacture date.
        by_year = defaultdict(list)
        for r in recent:
            y = (r.get("attrs") or {}).get("year")
            if y:
                by_year[y].append(r["price"])
        years = [
            {"year": y, "median": int(median(v)), "n": len(v)}
            for y, v in sorted(by_year.items()) if len(v) >= MIN_PER_YEAR
        ]

        specs = {
            f: _consensus([(r.get("attrs") or {}).get(f) for r in recs])
            for f in ("case_size_mm", "case_material", "bracelet",
                      "dial_colour", "dial_nickname", "box_papers")
        }
        model = _consensus([r.get("model") for r in recs])

        key = (brand, ref)
        sales = sales_by_ref.get(key, [])
        cuts = cuts_by_ref.get(key, [])

        card = {
            "slug": slugify(brand, ref),
            "brand": brand,
            "ref": ref,
            "model": model["value"] if model else None,
            "confidence": "full" if len(recent) >= MIN_RECENT_FULL else "limited",
            "n_recent": len(recent),
            "n_total": len(recs),
            "window_days": RECENT_DAYS,
            "median": int(med),
            "fair_low": int(q1),
            "fair_high": int(q3),
            "spread_pct": round((q3 - q1) / med * 100, 1) if med else None,
            "low": prices[0],
            "high": prices[-1],
            "first_seen": recs[0]["date"],
            "last_seen": recs[-1]["date"],
            "days_since_last_seen": (today - datetime.strptime(recs[-1]["date"], "%Y-%m-%d").date()).days,
            "channels": len({r["channel"] for r in recs}),
            "monthly": monthly,
            "by_year": years,
            "specs": {k: v for k, v in specs.items() if v},
            "time_to_sell": dist(sales) if len(sales) >= MIN_SALES_PER_REF else None,
            "sales_observed": len(sales),
            "price_cuts": ({
                "reposted": reposts_by_ref[key],
                "cut": len(cuts),
                "median_cut_pct": round(median(cuts), 1) if cuts else None,
                "median_days_listed": int(median(spans_by_ref[key])) if spans_by_ref[key] else None,
            } if reposts_by_ref[key] >= MIN_REPOSTS_PER_REF else None),
        }

        # ── Invariants. A broken card is worse than a missing one. ──
        assert card["brand"] and card["ref"], f"nameless card: {card}"
        assert card["fair_low"] <= card["median"] <= card["fair_high"], \
            f"{card['slug']}: fair range does not contain the median"
        assert card["n_recent"] >= MIN_RECENT_LIMITED, f"{card['slug']}: too thin"
        references.append(card)

    references.sort(key=lambda c: -c["n_recent"])

    slugs = Counter(c["slug"] for c in references)
    collisions = {s: n for s, n in slugs.items() if n > 1}
    assert not collisions, f"slug collisions: {collisions}"

    by_brand = Counter(c["brand"] for c in references)
    full = [c for c in references if c["confidence"] == "full"]

    out = {
        "generated": datetime.now(SGT).isoformat(),
        "window_days": RECENT_DAYS,
        "thresholds": {
            "full_confidence_min_recent": MIN_RECENT_FULL,
            "limited_confidence_min_recent": MIN_RECENT_LIMITED,
            "min_listings_per_month": MIN_PER_MONTH,
            "min_listings_per_year": MIN_PER_YEAR,
            "min_sales_to_publish_speed": MIN_SALES_PER_REF,
        },
        "caveat": (
            "These are asking prices from Singapore dealer channels, not "
            "transacted prices — no sale price is observable. The fair range is "
            f"the interquartile range of the last {RECENT_DAYS} days, so half of "
            "current asking prices fall inside it. Coverage is concentrated: "
            "Rolex dominates because its listings cluster on a few references, "
            "while brands of similar volume spread across many and never reach "
            "a publishable sample. Specifications are the most common value "
            "across listings, not a verified catalogue spec."
        ),
        "coverage": {
            "references_published": len(references),
            "full_confidence": len(full),
            "limited_confidence": len(references) - len(full),
            "listings_with_a_reference": with_ref,
            "references_too_thin_to_publish": rejected_thin,
            "by_brand": dict(by_brand.most_common()),
        },
        "references": references,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    print(f"References: {len(references)} published "
          f"({len(full)} full confidence, {len(references) - len(full)} limited) "
          f"across {len(by_brand)} brand(s); {rejected_thin} too thin")
    top = references[0] if references else None
    if top:
        print(f"  deepest: {top['brand']} {top['ref']} n={top['n_recent']} "
              f"fair ${top['fair_low']:,}-${top['fair_high']:,} "
              f"(±{top['spread_pct'] / 2:.0f}%)")
    return out


if __name__ == "__main__":
    build_references()
