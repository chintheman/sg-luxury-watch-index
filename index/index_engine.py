#!/usr/bin/env python3
"""
SG Luxury Watch Index — Index Engine v3.1
=========================================
Produces a family of indices from Telegram secondary-market listings.

Methodology:
  - Volume-weighted composite: sqrt(listing volume), no prestige term
  - Matched-model units (reference > model > brand), each against its
    own baseline, so a change in model mix cannot masquerade as a
    price move
  - Median price per unit per day (outlier-resilient)
  - Separate indices by condition (Pre-Owned, NEW/NOS)
  - Brand sub-indices for top brands
  - Availability score (daily listing count)
  - Per-unit baselines: each unit's first 30 listings
  - Anchor: 1.0 at the date when 50%+ brands have baseline data
  - Minimum 3 listings per brand per day for inclusion

Output: data/index.json (consumed by /api/watch-index → /watches)
"""

import sqlite3, json, re, sys
from datetime import datetime, timedelta, timezone

# Everything upstream stamps dates in SGT. index_engine used naive
# datetime.now(), i.e. the box's UTC clock, so "today" could be yesterday
# relative to the listing dates it was comparing against.
SGT = timezone(timedelta(hours=8))
from collections import Counter, defaultdict, deque
from statistics import median
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "parser"))
try:
    from filter import extract_price, extract_condition, is_watch_listing, extract_model
    from brands import match_brand as extract_brand
    from batch import is_batch_listing_post, split_batch_items
    from attributes import extract_attributes
    from dedupe import dedupe
    HAS_FILTER = True
except ImportError:
    HAS_FILTER = False
    def extract_attributes(t): return {}
    def dedupe(rs): return rs, {"removed": 0, "removed_pct": 0.0, "groups_with_repeats": 0}
    def extract_brand(t): return None
    def extract_price(t): return None
    def extract_condition(t): return "u"
    def is_watch_listing(t): return True
    def is_batch_listing_post(t): return False
    def split_batch_items(t): return []

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "listings.db"
OUT = BASE / "data" / "index.json"

ANCHOR_VALUE = 1.0
INDEX_VERSION = "3.2"
MIN_BASELINE_SAMPLES = 3

# ── v3 pooling parameters ─────────────────────────────────────────────────
# v2 pooled 3 days and required 3 listings per brand. Measured over the
# deduplicated corpus that produced a mean daily move of 13.6%, with 76% of
# days moving more than 5% — noise, not a luxury-watch market.
#
# Widening the pool to 21 days brings that to 3.4% mean and 20% of days,
# and simultaneously gives the best freshness available (38% of series days
# are genuinely computed rather than carried forward; every tighter config
# scored worse on BOTH axes). A three-week rolling median is a lot of
# smoothing for a twice-daily index, and that is a deliberate trade: this
# market is thin enough that a shorter window measures sampling noise rather
# than price.
WINDOW_DAYS = 21
MIN_PER_BRAND = 3
MIN_BRANDS_PER_COMPOSITE = 3

# Condition sub-indices stay wider still: Brand New is a small share of
# listings, so they need a bigger pool than the composite to be stable.
COND_WINDOW_DAYS = 28
MIN_COND_PER_BRAND = 2
MIN_COND_BRANDS = 2

# Availability ceiling — a trailing window, not an all-time max, so the score
# reads as "activity vs the recent norm" rather than "vs this codebase's
# best-ever scrape".
AVAILABILITY_ROLLING_DAYS = 60

# The baseline is each brand's FIRST N LISTINGS, not its first N days.
#
# v2 anchored on a 180-day calendar window from a brand's first appearance,
# which lands in the sparsest part of the scrape. Audemars Piguet first
# appeared 2025-03-27 and had 2 listings in the next 180 days, so it got no
# baseline and was dropped from the index entirely — despite 161 listings
# overall. 26 of 55 brands were being excluded this way, including Hublot,
# Breitling, Zenith and Chopard. Deduplication made it worse by removing the
# repeat postings that were padding those thin early windows.
#
# Anchoring on sample count instead means every brand with enough listings to
# be measured at all gets a baseline, whenever those listings happened to
# arrive. The trade-off is that for a sparse brand the baseline may span a
# long period and blend eras; that is still far better than excluding the
# brand from its own market index.
BASELINE_SAMPLE_TARGET = 30

# ── Matched-model matching ────────────────────────────────────────────────
# A brand's median price moves when the MIX of references listed changes, not
# only when prices change. Measured: Rolex's brand-level index read -25%,
# but at reference level its actual models were flat to slightly up (126334
# -3%, 126234 +6%, 278271 +11%). The baseline sample was Submariners and
# Daytonas; today's listings are dominated by Datejust, the cheapest common
# Rolex. The index was reading a change in WHAT IS LISTED as a change in
# PRICE. Matched at model level the same comparison reads +13%.
#
# Each listing is assigned a matching unit, most specific first:
#   reference number, when that reference has enough listings to be stable
#   model name,       when the reference is unknown or too thin
#   brand,            last resort
# Every unit is measured against its OWN baseline, and units aggregate up to
# brands. This covers 99% of listings across 256 units.
UNIT_REF_MIN_LISTINGS = 8
UNIT_MODEL_MIN_LISTINGS = 3

# ── Gap filling ────────────────────────────────────────────────────
def fill_series(series):
    """Carry the last computed value forward through days that didn't
    qualify (not enough brands/samples that day). Marks each carried-forward
    point with stale=True so consumers — and the site — can tell a freshly
    computed value apart from a repeat of an earlier one instead of both
    looking identical, which is exactly the kind of silent-discontinuity gap
    that erodes trust in a "daily" index once carry-forwards get frequent."""
    result = []
    last = None
    for pt in series:
        if pt["value"] is not None:
            last = pt["value"]
            result.append({**pt, "stale": False})
        elif last is not None:
            result.append({**pt, "value": last, "stale": True})
        else:
            result.append({**pt, "stale": False})
    return result

OUTLIER_LOW_MULT = 0.2
OUTLIER_HIGH_MULT = 5.0


def find_price_outliers(daily_by_brand, baseline_median,
                         low_mult=OUTLIER_LOW_MULT, high_mult=OUTLIER_HIGH_MULT):
    """Flag same-day per-brand prices far outside that brand's long-run
    baseline median. Log-only signal — callers should keep these listings in
    the index (the median is already outlier-resilient) and surface the flags
    for review rather than dropping anything."""
    outliers = []
    for date, by_brand in daily_by_brand.items():
        for brand, prices in by_brand.items():
            base = baseline_median.get(brand)
            if not base:
                continue
            for p in prices:
                if p < base * low_mult or p > base * high_mult:
                    outliers.append({"date": date, "brand": brand, "price": p, "baseline": base})
    return outliers


def compute_baseline_median(prices, min_samples=None,
                             low_mult=OUTLIER_LOW_MULT, high_mult=OUTLIER_HIGH_MULT):
    """Outlier-resistant baseline median for one brand's first-appearance
    window. Returns (value, outliers_excluded_count), or None if there
    aren't enough samples to baseline at all. Falls back to the unfiltered
    median if excluding outliers would drop below min_samples."""
    min_samples = MIN_BASELINE_SAMPLES if min_samples is None else min_samples
    if len(prices) < min_samples:
        return None
    raw_median = median(prices)
    filtered = [p for p in prices if low_mult * raw_median <= p <= high_mult * raw_median]
    if len(filtered) >= min_samples:
        return median(filtered), len(prices) - len(filtered)
    return raw_median, 0


def val_at_date(series, target_date):
    target = datetime.strptime(target_date, "%Y-%m-%d")
    best = None
    for pt in series:
        pt_date = datetime.strptime(pt["date"], "%Y-%m-%d")
        if pt_date <= target:
            best = pt["value"]
    return best

# ── Main ───────────────────────────────────────────────────────────
def build_indices():
    conn = sqlite3.connect(str(DB))
    rows = list(conn.execute(
        "SELECT channel_handle, message_id, posted_at, message_text FROM raw_messages"
    ))
    conn.close()

    # Phase 1: Parse all records. Batch "roundup" posts (e.g. sgwatchinsider's
    # "[WATCH DEALS ...]") are split into per-item candidates first — same as
    # export_pipeline.py — since this function parses raw_messages
    # independently rather than reusing export_pipeline's already-split
    # listings. Without this the index and the published listings.json would
    # silently run on divergently-filtered data.
    records = []

    def _record_from(text, date):
        if not text or (HAS_FILTER and not is_watch_listing(text)):
            return None
        brand = extract_brand(text)
        price = extract_price(text)
        if not brand or not price or not (500 <= price <= 500000):
            return None
        attrs = extract_attributes(text)
        return {
            "brand": brand, "price": price, "cond": extract_condition(text),
            "date": date,
            "ref": extract_model(text, brand)[1] if HAS_FILTER else None,
            "model": extract_model(text, brand)[0] if HAS_FILTER else None,
            "stock_code": attrs.get("stock_code"),
        }

    for ch, mid, ts, text in rows:
        if not text:
            continue
        date = ts[:10]
        _channel = ch
        if date < "2025-01-01":
            continue

        if HAS_FILTER and is_batch_listing_post(text):
            for item in split_batch_items(text):
                if not item["available"]:
                    continue
                rec = _record_from(item["body"], date)
                if rec:
                    rec["channel"] = _channel
                    records.append(rec)
            continue

        rec = _record_from(text, date)
        if rec:
            rec["channel"] = _channel
            records.append(rec)

    if not records:
        print("ERROR: No priced records found.")
        return

    # Collapse reposts BEFORE any weighting. Brand weights are volume-driven,
    # so counting one watch five times would inflate that brand's weight and
    # bake the error into every baseline.
    for i, r in enumerate(records):
        r["id"] = i
        r["channel"] = r.get("channel") or "unknown"
    records, dstats = dedupe(records)
    print(f"Dedupe: {dstats['removed']} repost(s) collapsed ({dstats['removed_pct']}%), "
          f"{len(records)} unique watches remain")

    # ── Assign each record its matching unit (see UNIT_* above) ──
    ref_counts = Counter((r["brand"], r["ref"]) for r in records if r.get("ref"))
    model_counts = Counter((r["brand"], r["model"]) for r in records if r.get("model"))

    def _unit(r):
        if r.get("ref") and ref_counts[(r["brand"], r["ref"])] >= UNIT_REF_MIN_LISTINGS:
            return ("ref", r["brand"], r["ref"])
        if r.get("model") and model_counts[(r["brand"], r["model"])] >= UNIT_MODEL_MIN_LISTINGS:
            return ("model", r["brand"], r["model"])
        return ("brand", r["brand"], None)

    for r in records:
        r["unit"] = _unit(r)
    tier_counts = Counter(r["unit"][0] for r in records)
    print(f"Matching units: {len(set(r['unit'] for r in records))} distinct "
          f"({tier_counts.get('ref',0)} by reference, {tier_counts.get('model',0)} by model, "
          f"{tier_counts.get('brand',0)} brand-level fallback)")

    records.sort(key=lambda r: r["date"])
    all_dates = sorted(set(r["date"] for r in records))
    all_brands = set(r["brand"] for r in records)
    print(f"Priced records: {len(records)}")
    print(f"Date range: {all_dates[0]} → {all_dates[-1]} ({len(all_dates)} days)")
    print(f"Brands: {len(all_brands)}")

    # Phase 2: Per-brand baselines (first 90 days of each brand)
    brand_first_seen = {}
    for r in records:
        if r["brand"] not in brand_first_seen:
            brand_first_seen[r["brand"]] = r["date"]

    # Unlike the daily outlier flag (log-only — a bad price is diluted by
    # tomorrow's window and gets flagged again for review, it's never the
    # only thing setting a number), a baseline outlier is effectively
    # permanent: it's computed from a brand's first ~90 days once and every
    # later day's ratio is measured against it forever. So here outliers are
    # actually excluded before taking the median, not just flagged.
    baseline_median = {}
    baseline_outliers_excluded = 0
    # Unit-level baselines are what the composite is actually built on. The
    # brand-level baseline below is kept only for the condition sub-series,
    # which does not decompose by model.
    prices_by_unit = defaultdict(list)
    for r in records:                      # records are already date-sorted
        prices_by_unit[r["unit"]].append(r["price"])
    unit_baseline = {}
    for unit, prices in prices_by_unit.items():
        result = compute_baseline_median(prices[:BASELINE_SAMPLE_TARGET])
        if result is not None:
            unit_baseline[unit] = result[0]
    unit_volume = {u: len(v) for u, v in prices_by_unit.items()}
    covered = sum(unit_volume[u] for u in unit_baseline)
    print(f"Unit baselines: {len(unit_baseline)} of {len(prices_by_unit)} units, "
          f"covering {covered} listings ({100*covered/len(records):.0f}%)")

    prices_by_brand = defaultdict(list)
    for r in records:
        prices_by_brand[r["brand"]].append(r["price"])
    for brand in all_brands:
        prices = prices_by_brand[brand][:BASELINE_SAMPLE_TARGET]
        result = compute_baseline_median(prices)
        if result is not None:
            value, excluded = result
            baseline_median[brand] = value
            baseline_outliers_excluded += excluded
    if baseline_outliers_excluded:
        print(f"Excluded {baseline_outliers_excluded} outlier price(s) from baseline computation")

    print(f"Brands with baseline: {len(baseline_median)} of {len(all_brands)}")
    missing = all_brands - set(baseline_median.keys())
    if missing:
        print(f"Missing baseline: {missing}")

    # Phase 3: Brand weights — sqrt of recent listing volume.
    #
    # v2 used 50% prestige + 50% volume, normalised so every brand got a
    # floor. Prestige is volume-blind, so the result was that six brands with
    # six listings each carried 59% of the index while Rolex's 142 carried
    # 24%: five Patek listings moved the number more than every Rolex
    # combined. Prestige is a subjective hand-assigned table and does not
    # belong in a price index.
    #
    # sqrt(volume) lets liquidity decide the weight while damping it, so
    # Rolex leads (about 21%) without the index becoming a pure Rolex
    # tracker, which is what raw volume produces.
    now = datetime.now(SGT)
    sixmo = now - timedelta(days=180)
    recent = [r for r in records if r["date"] >= sixmo.strftime("%Y-%m-%d")]
    brand_vol = Counter(r["brand"] for r in recent)
    total_vol = sum(brand_vol.values()) or 1

    brand_weight = {b: (brand_vol.get(b, 0) / total_vol) ** 0.5 for b in all_brands}
    total_bw = sum(brand_weight.values()) or 1
    brand_weight = {b: w / total_bw for b, w in brand_weight.items()}

    print(f"Top weights: {', '.join(f'{b}={w:.3f}' for b, w in sorted(brand_weight.items(), key=lambda x: -x[1])[:5])}")

    # Phase 4: Daily listings per brand (raw, for availability)
    daily_by_brand = defaultdict(lambda: defaultdict(list))
    for r in records:
        daily_by_brand[r["date"]][r["brand"]].append(r["price"])

    # ── Outlier flagging (log-only, never dropped from the index) ──
    # A single junk/mistyped price can still skew a low-sample-count brand's
    # daily median. Flag anything far outside that brand's long-run baseline
    # for review, without silently excluding real-but-unusual listings.
    price_outliers = find_price_outliers(daily_by_brand, baseline_median)
    if price_outliers:
        print(f"Flagged {len(price_outliers)} price outlier(s) (outside "
              f"{OUTLIER_LOW_MULT}x-{OUTLIER_HIGH_MULT}x brand baseline) — "
              f"kept in index, listed for review")

    # Phase 4b: Build 3-day rolling windows (pool [date-2, date])
    dates_sorted = sorted(daily_by_brand.keys())
    windowed_by_brand = defaultdict(lambda: defaultdict(list))
    for i, date in enumerate(dates_sorted):
        for j in range(max(0, i - WINDOW_DAYS + 1), i + 1):
            wdate = dates_sorted[j]
            for brand, prices in daily_by_brand[wdate].items():
                windowed_by_brand[date][brand].extend(prices)

    # Same pooling, but per matching unit — this is what the composite uses.
    daily_by_unit = defaultdict(lambda: defaultdict(list))
    for r in records:
        daily_by_unit[r["date"]][r["unit"]].append(r["price"])
    windowed_by_unit = defaultdict(lambda: defaultdict(list))
    for i, date in enumerate(dates_sorted):
        for j in range(max(0, i - WINDOW_DAYS + 1), i + 1):
            wdate = dates_sorted[j]
            for unit, prices in daily_by_unit[wdate].items():
                windowed_by_unit[date][unit].extend(prices)

    def brand_ratios_on(date):
        """Each brand's price level relative to its own baseline, built from
        matched models so a change in WHICH references are listed cannot
        masquerade as a price move.

        A unit qualifies with MIN_PER_BRAND listings in the window. Units are
        combined into a brand by their overall listing volume, so a brand's
        common references carry its number rather than whichever happened to
        be posted today.
        """
        out = {}
        agg = defaultdict(lambda: [0.0, 0.0, 0])   # brand -> [num, den, listings]
        for unit, prices in windowed_by_unit[date].items():
            if unit not in unit_baseline or len(prices) < MIN_PER_BRAND:
                continue
            brand = unit[1]
            w = unit_volume.get(unit, 1)
            agg[brand][0] += w * (median(prices) / unit_baseline[unit])
            agg[brand][1] += w
            agg[brand][2] += len(prices)
        for brand, (num, den, n) in agg.items():
            if den > 0:
                out[brand] = (num / den, n)
        return out

    # Availability score's ceiling: a rolling trailing max, not a fixed
    # all-time max. The channel roster isn't constant over the ~250-day
    # history (some channels went dormant, others only came online
    # partway through, sgwatchinsider's batch-post splitting could start
    # contributing more going forward) — an all-time max fixes the ceiling
    # to whichever era happened to have the most channels scraping, which
    # mechanically deflates every other era regardless of real listing
    # volume, and silently re-inflates every time channel coverage grows.
    # A trailing window means the ceiling reflects recent scraping
    # capacity, so the score is closer to "activity vs. the recent norm"
    # than "activity vs. this codebase's best-ever scrape."
    # Calendar-day window, not an index-count window: dates_sorted only
    # contains dates that actually have listings, so a large gap (real in
    # this data — some stretches have no scraped activity for weeks) would
    # otherwise let a stale date sit in an "N dates ago" window long past
    # when it should have aged out on the calendar.
    daily_totals = {d: sum(len(p) for p in daily_by_brand[d].values()) for d in dates_sorted}
    rolling_max_by_date = {}
    window_dq = deque()
    for date in dates_sorted:
        window_dq.append(date)
        cutoff = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=AVAILABILITY_ROLLING_DAYS - 1)).strftime("%Y-%m-%d")
        while window_dq and window_dq[0] < cutoff:
            window_dq.popleft()
        rolling_max_by_date[date] = max((daily_totals[d] for d in window_dq), default=1) or 1

    # Phase 5: Find anchor date (50%+ of baselined brands have appeared)
    anchor_date = None
    brands_seen = set()
    for date in sorted(daily_by_brand.keys()):
        brands_seen |= set(daily_by_brand[date].keys())
        qualified = sum(1 for b in brands_seen if b in baseline_median)
        if len(baseline_median) > 0 and qualified / len(baseline_median) >= 0.5:
            anchor_date = date
            break

    print(f"Anchor date (50%+ brands): {anchor_date or 'NOT FOUND'}")

    # Phase 6: Compute daily composite index
    composite = []
    preowned = []
    new_idx_list = []
    availability = []

    # Pre-group records by (date, condition) for O(n) sub-index computation
    records_by_date_cond = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r["brand"] in baseline_median:
            records_by_date_cond[r["date"]][r["cond"]].append(r)

    # Condition (New vs Pre-Owned) sub-indices get their own wider pooling
    # window: only ~14% of listings are Brand New, so a same-day-only pool
    # (what the composite's 3-day WINDOW_DAYS would still be too tight for)
    # swung the NEW index ±40% day to day — a single $45k Daytona landing on
    # the same day as a $15k Datejust was enough to triple the day's median.
    # This is the fix path documented in AGENTS.md but never implemented.
    windowed_by_date_cond = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for i, date in enumerate(dates_sorted):
        for j in range(max(0, i - COND_WINDOW_DAYS + 1), i + 1):
            wdate = dates_sorted[j]
            for cond_code, recs in records_by_date_cond[wdate].items():
                for r in recs:
                    windowed_by_date_cond[date][cond_code][r["brand"]].append(r["price"])

    for date in dates_sorted:
        day = windowed_by_brand[date]
        ratios_today = brand_ratios_on(date)

        if len(ratios_today) >= MIN_BRANDS_PER_COMPOSITE:
            weighted_sum = 0.0
            weight_used = 0.0
            for brand, (ratio, _n) in ratios_today.items():
                bw = brand_weight.get(brand, 0)
                weighted_sum += bw * ratio
                weight_used += bw
            val = round(ANCHOR_VALUE * weighted_sum / weight_used, 4) if weight_used > 0 else None
        else:
            val = None
        composite.append({
            "date": date, "value": val,
            "brands_tracked": len(ratios_today),
            "total_listings": sum(len(p) for p in day.values()),
        })

        # Availability — raw same-day count (not the 3-day-pooled `day`,
        # which would blur this into a smoothed figure) against a trailing
        # rolling ceiling rather than a fixed all-time one (see above).
        availability.append({
            "date": date,
            "value": round(daily_totals[date] / rolling_max_by_date[date] * 100),
        })

        # Condition sub-indices — pooled over COND_WINDOW_DAYS, see above.
        # Condition sub-indices use the SAME brand weighting as the composite.
        # v2 took an unweighted mean here while the composite was weighted, so
        # "the New-vs-Pre-Owned spread" subtracted two numbers built on
        # different scales from different brand mixes.
        for cond_code, output_list in [("p", preowned), ("n", new_idx_list)]:
            cond_prices = windowed_by_date_cond[date][cond_code]
            num = den = 0.0
            qualifying = 0
            for brand, prices in cond_prices.items():
                if len(prices) >= MIN_COND_PER_BRAND and brand in baseline_median:
                    bw = brand_weight.get(brand, 0)
                    num += bw * (median(prices) / baseline_median[brand])
                    den += bw
                    qualifying += 1
            value = (round(ANCHOR_VALUE * num / den, 4)
                     if qualifying >= MIN_COND_BRANDS and den > 0 else None)
            output_list.append({"date": date, "value": value})

    composite = fill_series(composite)
    preowned = fill_series(preowned)
    new_idx_list = fill_series(new_idx_list)
    availability = fill_series(availability)

    if not composite:
        print("ERROR: No valid composite index values.")
        return

    # Phase 7: Brand sub-indices
    top_brands = [b for b, _ in brand_vol.most_common(5)]
    brand_subindices = {}
    for brand in top_brands:
        if brand not in baseline_median:
            continue
        bidx = []
        for date in dates_sorted:
            r = brand_ratios_on(date).get(brand)
            val = round(ANCHOR_VALUE * r[0], 4) if r else None
            bidx.append({"date": date, "value": val})
        brand_subindices[brand] = fill_series(bidx)

    # Phase 9: Key metrics
    latest = composite[-1]
    prev = composite[-2] if len(composite) > 1 else latest
    chg_1d = round(latest["value"] - prev["value"], 4) if prev["value"] else 0
    chg_1d_pct = round(chg_1d / prev["value"] * 100, 2) if prev["value"] else 0

    # How many days back was the last genuinely fresh (non-carried-forward)
    # composite value — 0 means today's value is fresh.
    days_since_fresh = 0
    for pt in reversed(composite):
        if not pt.get("stale", False):
            break
        days_since_fresh += 1

    # The date/value data-sufficiency criteria first fire (anchor_date) is
    # NOT the same as the first date a composite value actually computes —
    # anchor_date itself usually doesn't have enough *brands* yet even
    # though 50%+ of *baselined* brands have appeared, so it rarely equals
    # 1.0 in practice. Surface the real first value/date explicitly rather
    # than letting "anchored at 1.0" imply the series starts there.
    first_computed = next((pt for pt in composite if pt["value"] is not None and not pt.get("stale")), None)

    now_str = datetime.now(SGT).strftime("%Y-%m-%d")
    d7 = (datetime.now(SGT) - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (datetime.now(SGT) - timedelta(days=30)).strftime("%Y-%m-%d")
    # v2 computed this from a 180-day lookback while the page labelled it
    # "90D" — and because the series began after that lookback it never
    # resolved, so the tile rendered blank permanently.
    d90 = (datetime.now(SGT) - timedelta(days=90)).strftime("%Y-%m-%d")
    v7 = val_at_date(composite, d7)
    v30 = val_at_date(composite, d30)
    v90 = val_at_date(composite, d90)

    # Brand contributions to the latest change.
    #
    # v2 reported bw * (today_ratio - yesterday_ratio) per brand and the
    # figures did not reconcile: they summed to about a third of the actual
    # move. Two reasons. The composite divides by the weight of the brands
    # that qualified THAT day, and that denominator changes daily; and brands
    # entering or leaving the qualifying set move the index without appearing
    # in any brand's contribution.
    #
    # Decompose it properly instead. With V = sum(w*ratio)/sum(w), a brand
    # present on both days contributes w/W_today * (ratio_t - ratio_y), and
    # the change in the denominator plus the set membership is reported
    # explicitly as a composition term rather than silently lost.
    brand_contribs = []
    composition_effect = 0.0
    contributions_total = 0.0
    if len(composite) > 1 and len(dates_sorted) > 1:
        t_win = windowed_by_brand[dates_sorted[-1]]
        t_all = brand_ratios_on(dates_sorted[-1])
        y_all = brand_ratios_on(dates_sorted[-2])
        t_med = {b: v[0] for b, v in t_all.items()}
        y_med = {b: v[0] for b, v in y_all.items()}
        W_t = sum(brand_weight.get(b, 0) for b in t_med) or 1.0
        W_y = sum(brand_weight.get(b, 0) for b in y_med) or 1.0
        V_t = sum(brand_weight.get(b, 0) * m for b, m in t_med.items()) / W_t
        V_y = sum(brand_weight.get(b, 0) * m for b, m in y_med.items()) / W_y

        shared = set(t_med) & set(y_med)
        explained = 0.0
        for brand in sorted(shared):
            bw = brand_weight.get(brand, 0)
            t_ratio = t_med[brand]
            y_ratio = y_med[brand]
            contrib = bw / W_t * (t_ratio - y_ratio)
            explained += contrib
            brand_contribs.append((brand, contrib, len(t_win.get(brand, []))))
        # Whatever the per-brand terms do not account for is composition:
        # brands entering or leaving, and the denominator shifting with them.
        composition_effect = (V_t - V_y) - explained
        contributions_total = explained
    brand_contribs.sort(key=lambda x: -abs(x[1]))

    po_latest = preowned[-1]["value"] if preowned else None
    new_latest = new_idx_list[-1]["value"] if new_idx_list else None
    cond_spread = round(new_latest - po_latest, 4) if (po_latest and new_latest) else None
    avail_latest = availability[-1]["value"] if availability else None

    trend_30d = "rising" if v30 and latest["value"] > v30 else "falling"

    # Phase 10: Insights
    insights = {}
    
    # Build a plain-English day summary
    day_direction = "rose" if chg_1d_pct > 0 else "fell" if chg_1d_pct < 0 else "held"
    week_direction = "up" if v7 and latest["value"] > v7 else "down" if v7 else None

    if brand_contribs:
        # v2 built this as "moved {dir_word}, led by {positive contributors}"
        # regardless of sign, so on a down day the page credited the brands
        # that had gone UP. Name the brands moving WITH the index first.
        up = [b for b, c, _ in brand_contribs if c > 0][:3]
        down = [b for b, c, _ in brand_contribs if c < 0][:3]
        rising = chg_1d_pct > 0
        leaders, opposers = (up, down) if rising else (down, up)

        dir_word = "up" if rising else "down" if chg_1d_pct < 0 else "flat"
        parts = [f"SG-LWIX moved {dir_word} {abs(chg_1d_pct):.1f}% today"]
        if leaders:
            parts.append(f"led by {', '.join(leaders)}")
        if opposers:
            parts.append(f"with {', '.join(opposers)} pulling the other way")
        insights["composite"] = ". ".join(parts) + "."
    elif latest["value"] and prev_day_idx["value"]:
        dir_word = "up" if latest["value"] > prev_day_idx["value"] else "down"
        insights["composite"] = f"SG-LWIX moved {dir_word} {abs(chg_1d_pct):.1f}% today across all tracked brands."

    if cond_spread is not None:
        insights["condition"] = (
            f"Brand New watches trade at a {cond_spread:+.4f} premium over Pre-Owned. "
            f"A widening gap signals stronger demand for unworn pieces."
        )
    if avail_latest is not None:
        insights["availability"] = (
            f"Availability Score: {avail_latest}/100. Higher = more watches entering market. "
            f"Falling scores often precede price increases."
        )

    # Output
    output = {
        "meta": {
            "name": "SG Luxury Watch Index",
            "symbol": "SG-LWIX",
            "version": INDEX_VERSION,
            "methodology": (
                "Weighted composite of secondary-market asking prices from "
                "Singapore Telegram watch dealer channels. Prices are matched "
                "at model level: each reference (or model, where the reference "
                "is unknown) is measured against its own baseline, so a change "
                "in which watches are listed cannot be mistaken for a change in "
                "price. Models aggregate to brands, and "
                "brands are weighted by the square root of their recent "
                "listing volume — liquidity decides the weight, damped so no "
                "single brand dominates. Prices are pooled over a "
                f"{WINDOW_DAYS}-day rolling window with at least "
                f"{MIN_PER_BRAND} listings per brand, because this market is "
                "thin enough that a shorter window measures sampling noise "
                "rather than price. Repeat postings of the same watch are "
                "collapsed before weighting. Non-Singapore stock is excluded, "
                "never converted. "
                f"{ANCHOR_VALUE} means brands trading exactly at their own "
                "baseline on average — a reference scale, not a value the "
                "series is pinned to on any date; see first_computed."
            ),
            "base_value": ANCHOR_VALUE,
            "anchor_date": anchor_date,
            "first_computed": first_computed,
            "updated": datetime.now(SGT).isoformat(),
            "total_records": len(records),
            "tracked_brands": len(all_brands),
        },
        "composite": {
            "current": latest["value"],
            "stale": latest.get("stale", False),
            "days_since_fresh": days_since_fresh,
            "change_1d": chg_1d,
            "change_1d_pct": chg_1d_pct,
            "change_7d": round(latest["value"] - v7, 4) if v7 else None,
            "change_7d_pct": round((latest["value"] - v7) / v7 * 100, 2) if v7 else None,
            "change_30d": round(latest["value"] - v30, 4) if v30 else None,
            "change_30d_pct": round((latest["value"] - v30) / v30 * 100, 2) if v30 else None,
            "change_90d": round(latest["value"] - v90, 4) if v90 else None,
            "change_90d_pct": round((latest["value"] - v90) / v90 * 100, 2) if v90 else None,
            "series": composite[-730:],
        },
        "condition_indices": {
            "preowned": {"current": po_latest, "series": preowned[-730:]},
            "new": {"current": new_latest, "series": new_idx_list[-730:]},
            "spread": cond_spread,
        },
        "availability": {"current": avail_latest, "series": availability[-730:]},
        "brand_subindices": {
            brand: {"current": bidx[-1]["value"] if bidx else None, "series": bidx[-730:] if bidx else []}
            for brand, bidx in brand_subindices.items()
        },
        "brand_weights": {b: round(w, 4) for b, w in sorted(brand_weight.items(), key=lambda x: -x[1])},
        "brand_counts": dict(brand_vol.most_common()),
        "brand_contributions": [
            {"brand": b, "contribution": round(c, 6), "listings": n}
            for b, c, n in brand_contribs[:8]
        ],
        # Sum of ALL per-brand terms, not just the top few published below.
        # Without this the reconciliation claim is not checkable from the
        # output: brand_contributions is truncated to the largest movers, so
        # adding those up will never match the total.
        "contributions_total": round(contributions_total, 6),
        # Per-brand terms plus this equal the actual move. Anything that is
        # not a price change in a brand present on both days -- brands
        # entering or leaving the qualifying set, and the weight denominator
        # moving with them -- lands here rather than going unexplained.
        "composition_effect": round(composition_effect, 6),
        "insights": insights,
        "price_outliers": price_outliers[-200:],
        "price_outlier_count": len(price_outliers),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2, default=str))

    print(f"\n{'='*60}")
    print(f"  SG-LWIX: {latest['value']:.4f}  ({chg_1d:+.4f}/day, {chg_1d_pct:+.2f}%)")
    print(f"  Anchor: {anchor_date}  |  Days tracked: {len(composite)}")
    print(f"  Brands baselined: {len(baseline_median)}/{len(all_brands)}")
    print(f"  Pre-Owned: {po_latest or 'N/A'}  |  NEW: {new_latest or 'N/A'}")
    if cond_spread is not None:
        print(f"  NEW-PO Spread: {cond_spread:+.4f}")
    print(f"{'='*60}")
    print(f"\n  {insights['composite']}")
    print(f"\n  Written to {OUT}")

if __name__ == "__main__":
    build_indices()
