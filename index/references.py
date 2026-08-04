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

# Above this, a "fair range" stops describing one market. Rolex 124300 is the
# worked example: the Oyster Perpetual 41 asks $9,900 to $32,900 because the
# Celebration and Tiffany dials are a different watch wearing the same
# reference number. Publishing a plus-or-minus 55% band as if it were a single
# price would mislead exactly the reader this is built for, so the card carries
# the warning with it rather than only tripping an ops alert.
WIDE_SPREAD_PCT = 60.0


# ── Reference families ─────────────────────────────────────────────
# Rolex encodes the variant in a suffix (126710BLNR) and the base number is
# already the unit people shop for, so it needs nothing here. Several other
# brands put the whole specification in the reference, which fragments them
# into groups of two and three:
#
#   Audemars Piguet  15510ST.OO.1320ST.06   model.case / bracelet / dial
#   Omega            310.32.42.50.02.001    case+movement / dial / bracelet
#   Hublot           411.NM.1170.RX         model / metal / dial / strap
#
# Truncating to the part that actually drives price (model plus case metal)
# turns 118 unusable AP references into a handful of real ones. Verified
# against the corpus: 26240OR (rose gold chrono) and 26240ST (steel) separate
# correctly at $95,300 and $73,900 medians, which is the distinction a buyer
# cares about.
#
# Cartier, Patek and Panerai are deliberately absent: their references have no
# variant structure to strip (WSSA0062, 5711, PAM01312), so they stay thin
# until volume arrives. There is no parser fix for those.
REF_FAMILIES = {
    "Audemars Piguet": lambda r: r.split(".")[0] if "." in r else None,
    "Omega": lambda r: ".".join(r.split(".")[:4]) if r.count(".") >= 4 else None,
    "Hublot": lambda r: ".".join(r.split(".")[:2]) if r.count(".") >= 2 else None,
}


def ref_family(brand, ref):
    """A coarser reference that still names one buyable thing, or None."""
    fn = REF_FAMILIES.get(brand)
    if not fn or not ref:
        return None
    fam = fn(ref)
    return fam if fam and fam != ref else None


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


def _grain_key(L, recent_by_exact, recent_by_family, recent_by_model):
    """Most specific unit that can actually be published.

    Mirrors index_engine._unit(): reference, then variant family, then model.
    A listing lands in exactly one, so nothing is counted in two cards.

    The model tier exists because reference-level pricing only works for brands
    that reuse a reference across many listings. Rolex does (682 references,
    busiest 179). Cartier does not: 261 listings across 106 references, busiest
    7, and WSSA0062 has no structure to group on. But people do not shop for
    WSSA0062 — they shop for a Santos. The model is the real buying unit there.
    """
    brand, ref, model = L["brand"], L.get("ref"), L.get("model")
    if ref and recent_by_exact[(brand, ref)] >= MIN_RECENT_LIMITED:
        return (brand, ref), "reference"
    fam = ref_family(brand, ref) if ref else None
    if fam and recent_by_family[(brand, fam)] >= MIN_RECENT_LIMITED:
        return (brand, fam), "family"
    if model and recent_by_model[(brand, model)] >= MIN_RECENT_LIMITED:
        return (brand, model), "model"
    return ((brand, ref), "reference") if ref else (None, None)


def build_references():
    rows = load_rows()
    listings = parse_listings(rows, with_attributes=True)
    by_id = {(r["channel_handle"], r["message_id"]): r for r in rows}

    today = datetime.now(SGT).date()
    recent_cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()

    # ── Group the corpus by reference ──
    # Two passes, mirroring index_engine._unit(): a listing lands in the most
    # specific group that can actually be published, so nothing is counted in
    # two cards.
    priced = []
    with_ref = 0
    for L in listings.values():
        # A listing needs either a usable reference or a model to be grouped.
        if L.get("ref") and is_junk_ref(L["ref"]):
            L = {**L, "ref": None}
        if not L.get("ref") and not L.get("model"):
            continue
        if L.get("ref"):
            with_ref += 1
        priced.append(L)

    recent = [L for L in priced if L["date"] >= recent_cutoff]
    recent_by_exact = Counter((L["brand"], L["ref"]) for L in recent if L.get("ref"))
    recent_by_family = Counter()
    for L in recent:
        fam = ref_family(L["brand"], L.get("ref")) if L.get("ref") else None
        if fam:
            recent_by_family[(L["brand"], fam)] += 1
    recent_by_model = Counter((L["brand"], L["model"]) for L in recent if L.get("model"))

    by_ref = defaultdict(list)
    grain_of = {}
    family_variants = defaultdict(set)
    for L in priced:
        key, grain = _grain_key(L, recent_by_exact, recent_by_family, recent_by_model)
        if key is None:
            continue
        by_ref[key].append(L)
        grain_of[key] = grain
        if grain == "family":
            family_variants[key].add(L["ref"])

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
    rejected_incoherent = 0
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

        variants = family_variants.get((brand, ref), set())
        grain = grain_of.get((brand, ref), "reference")
        card = {
            "slug": slugify(brand, ref),
            "brand": brand,
            # For a model card this holds the model name rather than a number.
            "ref": ref,
            # How specific this card is. "family" covers several references
            # differing by dial or bracelet; "model" covers a whole model line.
            # Saying so matters: neither may be read as a quote for one exact
            # configuration.
            "grain": grain,
            "variants": len(variants) if grain == "family"
                        else (len({r["ref"] for r in recs if r.get("ref")}) if grain == "model" else 0),
            "model": (ref if grain == "model" else (model["value"] if model else None)),
            "confidence": "full" if len(recent) >= MIN_RECENT_FULL else "limited",
            "n_recent": len(recent),
            "n_total": len(recs),
            "window_days": RECENT_DAYS,
            "median": int(med),
            "fair_low": int(q1),
            "fair_high": int(q3),
            "spread_pct": round((q3 - q1) / med * 100, 1) if med else None,
            "wide_spread": bool(med and (q3 - q1) / med * 100 > WIDE_SPREAD_PCT),
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

        # ── A grouped card must actually describe one thing ──
        # When an exact reference clears the bar it takes its own card, which
        # leaves the family holding only the leftovers — and those can be
        # wildly heterogeneous. Hublot 542.NX came out spanning $6,350 to
        # $19,900 that way. On a real reference a spread that wide is a fact
        # about the market (see WIDE_SPREAD_PCT); on a family it just means the
        # grouping is wrong, so the card is dropped rather than shown with a
        # caveat that cannot rescue it.
        if card["grain"] in ("family", "model") and card["wide_spread"]:
            rejected_incoherent += 1
            continue

        # ── Invariants. A broken card is worse than a missing one. ──
        assert card["brand"] and card["ref"], f"nameless card: {card}"
        assert card["fair_low"] <= card["median"] <= card["fair_high"], \
            f"{card['slug']}: fair range does not contain the median"
        assert card["n_recent"] >= MIN_RECENT_LIMITED, f"{card['slug']}: too thin"
        references.append(card)

    # ── Drop model cards that are only holding leftovers ──
    # See the module note on grain. If any reference or family card already
    # covers this (brand, model), the model card was built from the references
    # that were too thin to stand alone — a biased tail, not the model.
    # Normalised, because dealers write the same model both ways: the
    # reference cards agreed on "GMT Master" while the model card came out
    # "GMT-Master", and a plain lowercase compare let the leftovers through.
    def _mkey(brand, model):
        return (brand, re.sub(r"[^a-z0-9]", "", (model or "").lower()))

    priced_models = {
        _mkey(c["brand"], c["model"])
        for c in references if c["grain"] in ("reference", "family") and c.get("model")
    }
    before = len(references)
    references = [
        c for c in references
        if not (c["grain"] == "model" and _mkey(c["brand"], c["model"]) in priced_models)
    ]
    rejected_leftovers = before - len(references)

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
            "wide_spread_pct": WIDE_SPREAD_PCT,
            "family_grouped_brands": sorted(REF_FAMILIES),
        },
        "caveat": (
            "These are asking prices from Singapore dealer channels, not "
            "transacted prices — no sale price is observable. The fair range is "
            f"the interquartile range of the last {RECENT_DAYS} days, so half of "
            "current asking prices fall inside it. Coverage is concentrated: "
            "Rolex dominates because its listings cluster on a few references, "
            "while brands of similar volume spread across many and never reach "
            "a publishable sample. Where a brand encodes dial and bracelet in "
            "the reference itself (Audemars Piguet, Omega, Hublot), close "
            "variants are grouped. Where references are unique per watch and "
            "never repeat enough to price (Cartier, Patek Philippe, Panerai), "
            "the card covers a whole model line instead. Every card says which "
            "of the three it is. Specifications are the most common value "
            "across listings, not a verified catalogue spec."
        ),
        "coverage": {
            "references_published": len(references),
            "families": sum(1 for c in references if c["grain"] == "family"),
            "model_level": sum(1 for c in references if c["grain"] == "model"),
            "wide_spread": sum(1 for c in references if c["wide_spread"]),
            "full_confidence": len(full),
            "limited_confidence": len(references) - len(full),
            "listings_with_a_reference": with_ref,
            "references_too_thin_to_publish": rejected_thin,
            "groups_dropped_as_incoherent": rejected_incoherent,
            "model_cards_dropped_as_leftovers": rejected_leftovers,
            "by_brand": dict(by_brand.most_common()),
        },
        "references": references,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    fams = sum(1 for c in references if c["grain"] == "family")
    mods = sum(1 for c in references if c["grain"] == "model")
    print(f"References: {len(references)} published "
          f"({len(full)} full confidence, {len(references) - len(full)} limited; "
          f"{fams} variant-grouped, {mods} model-level) across {len(by_brand)} brand(s); "
          f"{rejected_thin} too thin, {rejected_incoherent} group(s) too broad, "
          f"{rejected_leftovers} model card(s) were leftovers")
    top = references[0] if references else None
    if top:
        print(f"  deepest: {top['brand']} {top['ref']} n={top['n_recent']} "
              f"fair ${top['fair_low']:,}-${top['fair_high']:,} "
              f"(±{top['spread_pct'] / 2:.0f}%)")
    return out


if __name__ == "__main__":
    build_references()
