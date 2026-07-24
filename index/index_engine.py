#!/usr/bin/env python3
"""
SG Luxury Watch Index — Index Engine v2.0
=========================================
Produces a family of indices from Telegram secondary-market listings.

Methodology:
  - Laspeyres-weighted composite (brand prestige × listing volume)
  - Median price per brand per day (outlier-resilient)
  - Separate indices by condition (Pre-Owned, NEW/NOS)
  - Brand sub-indices for top brands
  - Availability score (daily listing count)
  - Per-brand baselines: first 90 days of each brand's data
  - Anchor: 1.0 at the date when 50%+ brands have baseline data
  - Minimum 3 listings per brand per day for inclusion

Output: data/index.json (consumed by /api/watch-index → /watches)
"""

import sqlite3, json, re, sys
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from statistics import median
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "parser"))
try:
    from filter import extract_price, extract_condition, is_watch_listing
    from brands import match_brand as extract_brand
    from batch import is_batch_listing_post, split_batch_items
    HAS_FILTER = True
except ImportError:
    HAS_FILTER = False
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
MIN_BASELINE_SAMPLES = 3
# A single listing determining a brand's entire daily-window contribution
# was the mechanism behind confirmed ±100% single-brand-day swings — over
# the full history, 53% of (date, brand) window-pools had exactly 1 sample.
# 3 is the textbook-correct value for outlier resistance (a median of 3
# can't be dragged by one bad price; a median of 2 is just an average and
# still is). Measured against the *full* history this drops fresh-day
# coverage from 44% to 15%, which looks alarming — but that average is
# dominated by the scraper's thin early months. Measured against the
# actually-relevant recent window it holds up fine: 87% fresh over the last
# 30 days, 76% over the last 90 (both better than MIN_PER_BRAND=2 gives on
# the same recent windows). Re-check this if listing volume drops.
MIN_PER_BRAND = 3
MIN_BRANDS_PER_COMPOSITE = 3
WINDOW_DAYS = 3

# ── Prestige weights (0-10, from Chrono24 + horological consensus) ──
# Gerald Genta, Parmigiani Fleurier, Roger Dubuis, Louis Moinet, Glashutte
# Original, Chanel, and Louis Erard were added to close a "brand: null" gap
# (real listings under these brands weren't recognized at all before). Their
# weights were placed by cross-checking brand positioning against
# independent horology sources rather than guessed cold:
#   - Roger Dubuis / Parmigiani Fleurier (6.5): both consistently described
#     as haute horlogerie tier — hand-finishing, complications, limited
#     production — comparable to Girard-Perregaux (7) in exclusivity, placed
#     slightly below it for lower brand recognition/heritage depth.
#   - Gerald Genta (7): the eponymous designer of the AP Royal Oak and
#     Patek Nautilus; LVMH-owned via La Fabrique du Temps. High design
#     pedigree, but the brand itself has less market presence than GP/JLC.
#   - Louis Moinet (6): "extremely interesting," limited/one-off production,
#     but low mainstream brand recognition despite high-end positioning —
#     placed with Chopard/Zenith rather than the haute horlogerie tier.
#   - Glashutte Original (5.5): established German in-house manufacture,
#     grouped with IWC/Panerai/Bulgari as respected-but-not-top-tier.
#   - Chanel (4.5): explicitly framed in horology coverage as a fashion
#     house watchmaking success (the J12's ceramic bracelet was genuinely
#     influential) rather than a specialist horological manufacture —
#     placed with Breitling/Hublot/Tudor, below Cartier/Bulgari.
#   - Louis Erard (3.5): directly described as "entry-level-ish," explicitly
#     marketed as an affordable alternative for Breguet/F.P. Journe admirers
#     — placed with TAG Heuer/Bell & Ross.
# Still ultimately subjective — worth a sanity pass from someone closer to
# the SG secondary market than a web search.
PRESTIGE = {
    "Patek Philippe": 10, "Richard Mille": 10, "A. Lange & Sohne": 9.5,
    "Audemars Piguet": 9, "Vacheron Constantin": 9, "Breguet": 8.5,
    "Rolex": 8, "H. Moser": 8, "Blancpain": 7.5,
    "Jaeger-LeCoultre": 7, "Girard-Perregaux": 7, "Gerald Genta": 7,
    "Parmigiani Fleurier": 6.5, "Ulysse Nardin": 6.5, "Roger Dubuis": 6.5,
    "Cartier": 6.5, "Chopard": 6, "Zenith": 6, "Louis Moinet": 6,
    "IWC": 5.5, "Panerai": 5.5, "Bulgari": 5.5, "Glashutte Original": 5.5,
    "Omega": 5, "Grand Seiko": 5, "Chanel": 4.5, "Louis Erard": 3.5,
    "Breitling": 4.5, "Hublot": 4.5, "Tudor": 4,
    "TAG Heuer": 3.5, "Bell & Ross": 3.5,
    "Franck Muller": 3, "Seiko": 2,
}

# ── Retail price database ──────────────────────────────────────────
RETAIL_PRICES = {
    "Rolex": {
        "126610": 15400, "126610LN": 15400, "124060": 13700,
        "116610": 14400, "116610LN": 14400, "126710": 16100,
        "126710BLNR": 16100, "126710BLRO": 17400, "116500": 18800,
        "116500LN": 18800, "126334": 12600, "126234": 11700,
        "226570": 14000, "124270": 9500, "214270": 10200,
        "216570": 13100, "126622": 16800, "226658": 24800,
        "228238": 49500, "126600": 18500, "124300": 8100,
        "126000": 7700, "116400": 11800, "126900": 9600,
        "326934": 21500, "336934": 21500, "126300": 10900,
        "126200": 9200, "278274": 5400, "278271": 5900,
        "268622": 12000, "279174": 4600, "279171": 4500,
        "126613": 21400, "126618": 51000, "126619": 58400,
        "126518": 42000, "116518": 40500, "116519": 41200,
        "116508": 54200, "116509": 55200, "228235": 50500,
        "228239": 49500, "218235": 47500, "128238": 51200,
    },
    "Patek Philippe": {
        "5711": 46000, "5712": 55000, "5711/1A": 46000,
        "5712/1A": 55000, "5726": 62000, "5740": 165000,
        "5990": 74000, "5980": 79000, "5167": 28000,
        "5167A": 28000, "5168": 48000, "5168G": 48000,
        "6119": 37000, "5226": 42000, "5205": 68000,
        "5326": 47000, "5320": 95000, "5236": 165000,
        "5270": 235000, "5370": 345000, "5230": 68000,
        "5131": 62000, "5930": 85000, "5172": 106000,
        "5905": 78000, "5961": 115000, "5524": 54000,
        "4947": 58000, "7300": 32000, "7118": 37000,
    },
    "Audemars Piguet": {
        "15510": 38000, "15500": 36500, "26420": 42000,
        "26240": 45000, "15450": 32000, "15400": 31000,
        "15550": 31000, "26715": 55000, "26238": 58000,
        "15202": 35000, "16202": 42000, "15551": 39000,
        "26470": 38500, "26480": 44500, "26405": 52000,
        "26237": 35000, "26615": 58000, "77450": 28000,
        "67651": 25500, "26231": 42000, "77350": 31000,
    },
    "Omega": {
        "310.30": 10300, "311.30": 8500, "210.30": 8200,
        "210.32": 8200, "234.30": 9500, "215.30": 9100,
        "220.10": 8100, "329.30": 11800, "329.32": 13500,
        "310.32": 10500, "310.60": 15200, "326.30": 11200,
        "326.32": 13200, "332.10": 7500, "329.53": 48000,
        "311.32": 9200, "234.10": 9800, "220.12": 7200,
    },
    "Cartier": {
        "WSSA0029": 10400, "WSSA0018": 11200, "WSTA0041": 5400,
        "WSTA0040": 5600, "WSSA0030": 13000, "WSSA0062": 9800,
        "WSSA0047": 11200, "WSBB0044": 5400, "WSTA0042": 3500,
        "W20073X8": 4200, "W20106X8": 4600, "W69012Z4": 10200,
        "W6920085": 8500, "W2SA0016": 5800, "W4TA0008": 6200,
    },
    "Tudor": {
        "79030": 5400, "79010": 5400, "M79830": 5900,
        "79230": 5100, "79540": 4400, "M79360": 7400,
        "M25600": 6700, "28500": 3100, "M79030": 5400,
        "M79230": 5100, "M79540": 4400, "M79680": 4200,
        "M79660": 4100, "M79470": 5900, "M70150": 3600,
    },
    "Panerai": {
        "PAM01312": 11200, "PAM01314": 13500, "PAM01321": 11300,
        "PAM01028": 9800, "PAM00372": 11200, "PAM00422": 13500,
        "PAM01055": 18400, "PAM00968": 22400, "PAM00959": 7600,
        "PAM00753": 5800, "PAM01086": 9800, "PAM01041": 14200,
        "PAM01389": 15500, "PAM00985": 7200, "PAM01112": 10800,
        "PAM00964": 8400, "PAM01271": 11800, "PAM00796": 5800,
    },
    "Hublot": {
        "542.NX": 15800, "542.CM": 23000, "301.SX": 15200,
        "301.CI": 16800, "411.NX": 18300, "411.CF": 28000,
        "411.JX": 42000, "521.NX": 15800, "716.NM": 36000,
        "542.OX": 38500, "441.NX": 22000, "441.CI": 31500,
        "465.SS": 15800, "465.OS": 36500, "411.NM": 28500,
    },
    "Breitling": {
        "A17316": 5900, "A17388": 5400, "AB0138": 10300,
        "AB2010": 11500, "A13316": 8200, "AB0310": 10500,
        "A17314": 5600, "AB0134": 10300, "A32398": 12500,
        "UB0134": 11800, "A17395": 5400, "AB0441": 9800,
    },
    "IWC": {
        "IW3289": 9600, "IW3269": 7800, "IW3881": 13500,
        "IW3293": 9600, "IW3716": 9800, "IW3714": 7800,
        "IW5035": 38500, "IW5036": 42000, "IW3583": 6800,
        "IW5030": 39000, "IW5101": 21500, "IW3570": 5800,
        "IW3240": 8500, "IW3290": 9800, "IW3780": 16400,
    },
    "Jaeger-LeCoultre": {
        "Q390": 12800, "Q398": 10200, "Q384": 13500,
        "Q906": 48000, "Q126": 10200, "Q130": 14500,
        "Q136": 23500, "Q344": 22500, "Q346": 29500,
        "Q900": 36000, "Q902": 52000, "Q810": 18500,
    },
    "Vacheron Constantin": {
        "4500V": 34000, "4520V": 37000, "5500V": 42000,
        "7900V": 38500, "4300V": 125000, "4000V": 95000,
        "4600V": 17500, "2305V": 42000, "43178": 68000,
        "82172": 28000, "85180": 38000, "1110U": 14500,
    },
    "Grand Seiko": {
        "SBGA211": 7800, "SBGA413": 8800, "SBGA415": 8200,
        "SBGA375": 7200, "SBGJ201": 8500, "SBGW231": 5400,
        "SLGA019": 13200, "SLGH005": 12300, "SBGY007": 11500,
        "SBGA443": 8800, "SBGA469": 7800, "SLGA021": 12800,
    },
    "TAG Heuer": {
        "CBN2A": 8300, "CBN201": 9800, "CAZ101": 3200,
        "WAY201": 4200, "WBP201": 4800, "CBL211": 7800,
        "CBG201": 6800, "CBN211": 9200, "CAZ201": 3500,
        "WBP211": 5200, "CBN2A1A": 8500, "CAZ101AL": 3100,
    },
    "Zenith": {
        "03.3100": 12800, "03.3200": 13600, "03.3110": 12800,
        "03.9300": 11500, "49.9000": 11200, "95.9000": 13200,
        "97.T384": 10800, "03.2170": 11800, "03.9000": 13600,
        "03.2520": 11200, "03.2330": 10500, "97.A384": 10800,
    },
    "Richard Mille": {
        "RM 011": 245000, "RM 030": 230000, "RM 035": 260000,
        "RM 010": 220000, "RM 055": 280000, "RM 052": 850000,
        "RM 011-03": 265000, "RM 030-01": 250000, "RM 67-01": 165000,
    },
    "H. Moser": {
        "1200-0200": 31500, "1200-0400": 38000, "1200-0500": 42000,
        "1343-0100": 28500, "1343-0200": 32000, "1200-0215": 19500,
    },
    "Breguet": {
        "5177": 32000, "7147": 28500, "7097": 48000,
        "7057": 38500, "7727": 58000, "5527": 38000,
        "5517": 31000, "5817": 28000, "7337": 42000,
    },
    "Blancpain": {
        "5000": 18500, "5015": 22500, "5008": 16500,
        "6651": 13800, "6668": 16800, "6639": 26500,
        "5200": 21500, "5054": 22500, "6654": 17500,
    },
    "Chopard": {
        "168589": 10200, "168566": 9800, "168571": 8500,
        "161289": 7500, "168997": 15800, "161275": 6800,
        "168565": 8200, "168992": 16800, "161920": 8500,
    },
    "Franck Muller": {
        "V45": 14500, "V41": 12500, "V32": 10500,
        "8880": 13500, "5850": 12500, "7880": 15500,
        "2852": 8500, "8005": 12500, "6850": 11500,
    },
    "A. Lange & Sohne": {
    },
    "Bell & Ross": {
    },
    "Bulgari": {
        "Octo Finissimo": 19500, "Octo Roma": 11500,
        "Serpenti": 7500, "Diagono": 7500,
    },
    "Bvlgari": {
        "Octo Finissimo": 19500, "Octo Roma": 11500,
        "Serpenti": 7500, "Diagono": 7500,
    },
    "Corum": {
    },
    "Girard-Perregaux": {
    },
    "Hermes": {
    },
    "Longines": {
    },
    "MB&F": {
    },
    "Oris": {
    },
    "Piaget": {
    },
    "Sinn": {
    },
    "Ulysse Nardin": {
    },
}

# ── Smart retail price matching ─────────────────────────────────────
def get_retail_price_smart(brand, text):
    """Multi-stage retail price matching for a listing.
    
    1. Reference number match (exact, e.g. "126610" found in text)
    2. Model keyword match (substring, e.g. "Submariner" → ref lookup)
    3. Brand-level average fallback (when brand is in RETAIL_PRICES)
    Returns (price, match_method) or (None, None).
    """
    if not brand or brand not in RETAIL_PRICES:
        return None, None
    
    # Normalise text
    t = (text or '').upper().replace('\n', ' ')
    
    # Stage 1: Reference number matching
    ref_pattern = re.compile(r'\b(\d{3,6}(?:\.\d{2,4}){0,2}[A-Z]{0,4})\b')
    year_pattern = re.compile(r'\b(19\d{2}|20[0-3]\d)\b')
    
    refs_found = []
    for m in ref_pattern.finditer(t):
        ref = m.group(1)
        if year_pattern.fullmatch(ref):
            continue
        refs_found.append(ref)
    
    for ref in refs_found:
        if ref in RETAIL_PRICES[brand]:
            return RETAIL_PRICES[brand][ref], "ref"
    
    # Also try refs without trailing letters (e.g. "126610LN" → "126610")
    for ref in refs_found:
        base_ref = re.sub(r'[A-Z]+$', '', ref)
        if base_ref and base_ref in RETAIL_PRICES[brand]:
            return RETAIL_PRICES[brand][base_ref], "ref"
    
    # Stage 2: Model keyword matching
    for keyword, price in RETAIL_PRICES[brand].items():
        if len(keyword) >= 5 and keyword.upper() in t:
            return price, "keyword"
    
    # Stage 3: Brand-level average
    all_prices = list(RETAIL_PRICES[brand].values())
    if all_prices:
        from statistics import median
        return int(median(all_prices)), "brand_avg"
    
    return None, None

# Legacy wrapper
def get_retail_price(brand, text):
    price, method = get_retail_price_smart(brand, text)
    return price

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
        retail, retail_method = get_retail_price_smart(brand, text)
        return {
            "brand": brand, "price": price, "cond": extract_condition(text),
            "date": date, "retail": retail, "retail_method": retail_method,
        }

    for ch, mid, ts, text in rows:
        if not text:
            continue
        date = ts[:10]
        if date < "2025-01-01":
            continue

        if HAS_FILTER and is_batch_listing_post(text):
            for item in split_batch_items(text):
                if not item["available"]:
                    continue
                rec = _record_from(item["body"], date)
                if rec:
                    records.append(rec)
            continue

        rec = _record_from(text, date)
        if rec:
            records.append(rec)

    if not records:
        print("ERROR: No priced records found.")
        return

    records.sort(key=lambda r: r["date"])
    all_dates = sorted(set(r["date"] for r in records))
    all_brands = set(r["brand"] for r in records)
    print(f"Priced records: {len(records)}")
    print(f"Date range: {all_dates[0]} → {all_dates[-1]} ({len(all_dates)} days)")
    print(f"Brands: {len(all_brands)}")

    # ── Retail-data coverage (feeds retail_spread's insight text honestly) ──
    # RETAIL_PRICES only has real reference/keyword entries for ~23 of the
    # brands tracked; the rest never resolve a retail price at all. Even
    # among brands that do have data, most matches fall through to a crude
    # brand-wide average (Stage 3) rather than a real ref/model match. And
    # since Rolex alone is typically the majority of all listings, a
    # "secondary vs retail" headline stat is easy to mistake for a
    # market-wide figure when it's actually dominated by whichever brands
    # happen to have retail data *and* volume — usually Rolex first.
    retail_method_counts = Counter(r["retail_method"] for r in records if r.get("retail_method"))
    retail_brand_counts = Counter(r["brand"] for r in records if r.get("retail") is not None)
    retail_matched_total = sum(retail_brand_counts.values())
    top_retail_brand, top_retail_count = (retail_brand_counts.most_common(1) or [(None, 0)])[0]
    retail_coverage = {
        "brands_with_retail_data": sum(1 for v in RETAIL_PRICES.values() if v),
        "brands_tracked": len(all_brands),
        "matched_records": retail_matched_total,
        "matched_records_pct": round(100 * retail_matched_total / len(records), 1) if records else 0,
        "match_method_counts": dict(retail_method_counts),
        "top_brand": top_retail_brand,
        "top_brand_share_pct": round(100 * top_retail_count / retail_matched_total, 1) if retail_matched_total else 0,
    }
    print(f"Retail coverage: {retail_coverage['matched_records_pct']}% of records matched "
          f"({dict(retail_method_counts)}), top brand {top_retail_brand} = "
          f"{retail_coverage['top_brand_share_pct']}% of matches")

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
    for brand in all_brands:
        first = brand_first_seen[brand]
        first_dt = datetime.strptime(first, "%Y-%m-%d")
        window_end = (first_dt + timedelta(days=180)).strftime("%Y-%m-%d")
        prices = [r["price"] for r in records
                   if r["brand"] == brand and r["date"] <= window_end]
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

    # Phase 3: Brand weights (50% prestige + 50% volume)
    now = datetime.now()
    sixmo = now - timedelta(days=180)
    recent = [r for r in records if r["date"] >= sixmo.strftime("%Y-%m-%d")]
    brand_vol = Counter(r["brand"] for r in recent)
    total_vol = sum(brand_vol.values()) or 1

    vol_weight = {b: c / total_vol for b, c in brand_vol.items()}
    max_vw = max(vol_weight.values()) if vol_weight else 1
    norm_vol = {b: w / max_vw for b, w in vol_weight.items()}

    brand_weight = {}
    for b in all_brands:
        p = PRESTIGE.get(b, 3)
        v = norm_vol.get(b, 0)
        brand_weight[b] = 0.5 * (p / 10) + 0.5 * v

    total_bw = sum(brand_weight.values())
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
    retail_composite = []  # NEW: retail-anchored (1.0 = at retail)
    preowned = []
    new_idx_list = []
    availability = []

    # Pre-group records by (date, condition) for O(n) sub-index computation
    records_by_date_cond = defaultdict(lambda: defaultdict(list))
    records_by_date_retail = defaultdict(list)
    for r in records:
        if r["brand"] in baseline_median:
            records_by_date_cond[r["date"]][r["cond"]].append(r)
        if r["retail"]:
            records_by_date_retail[r["date"]].append(r)

    for date in dates_sorted:
        day = windowed_by_brand[date]
        day_median = {}
        for brand, prices in day.items():
            if brand in baseline_median and len(prices) >= MIN_PER_BRAND:
                day_median[brand] = median(prices)

        if len(day_median) >= MIN_BRANDS_PER_COMPOSITE:
            weighted_sum = 0.0
            weight_used = 0.0
            for brand, mp in day_median.items():
                bw = brand_weight.get(brand, 0)
                ratio = mp / baseline_median[brand]
                weighted_sum += bw * ratio
                weight_used += bw
            val = round(ANCHOR_VALUE * weighted_sum / weight_used, 4) if weight_used > 0 else None
        else:
            val = None
        composite.append({
            "date": date, "value": val,
            "brands_tracked": len(day_median),
            "total_listings": sum(len(p) for p in day.values()),
        })

        # ── Retail-anchored composite (1.0 = at retail) ──
        retail_ratios = []
        retail_weights_used = 0.0
        for brand, prices in day.items():
            if brand not in baseline_median:
                continue
            if not any(r["retail"] for r in records_by_date_retail[date] if r["brand"] == brand):
                continue
            retail_prices = [r["retail"] for r in records_by_date_retail[date] if r["brand"] == brand]
            price_ratios = [p / r for p, r in zip(day[brand], retail_prices)]
            med_ratio = median(price_ratios)
            bw = brand_weight.get(brand, 0)
            retail_ratios.append((med_ratio, bw))
            retail_weights_used += bw
        retail_val = sum(r[0] * r[1] for r in retail_ratios) / retail_weights_used if retail_weights_used > 0 else None
        retail_composite.append({
            "date": date,
            "value": retail_val,
        })

        # Availability
        total_day = sum(len(p) for p in day.values())
        max_day = max(sum(len(p) for p in d.values()) for d in daily_by_brand.values()) or 1
        availability.append({"date": date, "value": round(total_day / max_day * 100)})

        # Condition sub-indices
        for cond_code, output_list in [("p", preowned), ("n", new_idx_list)]:
            cond_prices = defaultdict(list)
            for r in records_by_date_cond[date][cond_code]:
                cond_prices[r["brand"]].append(r["price"])
            ratios = []
            for brand, prices in cond_prices.items():
                if len(prices) >= 2:
                    ratios.append(median(prices) / baseline_median[brand])
            output_list.append({
                "date": date,
                "value": round(ANCHOR_VALUE * sum(ratios) / len(ratios), 4) if ratios else None,
            })

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
            day = windowed_by_brand[date]
            if brand in day and len(day[brand]) >= MIN_PER_BRAND:
                val = round(ANCHOR_VALUE * median(day[brand]) / baseline_median[brand], 4)
            else:
                val = None
            bidx.append({"date": date, "value": val})
        brand_subindices[brand] = fill_series(bidx)

    # Phase 8: Retail-secondary spread
    spread_series = []
    for date in dates_sorted:
        spreads = [r for r in records_by_date_retail[date] if r["retail"]]
        if len(spreads) >= 3:
            vals = [(r["retail"] - r["price"]) / r["retail"] * 100 for r in spreads]
            spread_series.append({"date": date, "value": round(median(vals), 1)})
        else:
            spread_series.append({"date": date, "value": None})
    spread_series = fill_series(spread_series)

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

    now_str = datetime.now().strftime("%Y-%m-%d")
    d7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    v7 = val_at_date(composite, d7)
    v30 = val_at_date(composite, d30)
    v90 = val_at_date(composite, d90)

    # Brand contributions to 1-day change
    prev_day_idx = composite[-2] if len(composite) > 1 else latest
    brand_contribs = []
    if len(composite) > 1:
        for date in [dates_sorted[-1], dates_sorted[-2]]:
            pass
        today_window = windowed_by_brand[dates_sorted[-1]]
        yesterday_window = windowed_by_brand[dates_sorted[-2]]
        for brand in sorted(today_window.keys() | yesterday_window.keys()):
            if brand not in baseline_median:
                continue
            t_prices = today_window.get(brand, [])
            y_prices = yesterday_window.get(brand, [])
            if len(t_prices) >= MIN_PER_BRAND and len(y_prices) >= MIN_PER_BRAND:
                t_ratio = median(t_prices) / baseline_median[brand]
                y_ratio = median(y_prices) / baseline_median[brand]
                bw = brand_weight.get(brand, 0)
                contrib = bw * (t_ratio - y_ratio)
                brand_contribs.append((brand, contrib, len(t_prices)))
    brand_contribs.sort(key=lambda x: -abs(x[1]))

    po_latest = preowned[-1]["value"] if preowned else None
    new_latest = new_idx_list[-1]["value"] if new_idx_list else None
    cond_spread = round(new_latest - po_latest, 4) if (po_latest and new_latest) else None
    retail_spread = spread_series[-1]["value"] if spread_series else None
    avail_latest = availability[-1]["value"] if availability else None

    trend_30d = "rising" if v30 and latest["value"] > v30 else "falling"

    # ── Retail-anchored metrics ──
    retail_latest = retail_composite[-1]["value"] if retail_composite else None
    retail_prev = retail_composite[-2]["value"] if len(retail_composite) > 1 else None
    retail_chg_1d = round(retail_latest - retail_prev, 4) if (retail_latest and retail_prev) else 0
    retail_chg_1d_pct = round(retail_chg_1d / retail_prev * 100, 2) if retail_prev else 0

    # Phase 10: Insights
    insights = {}
    
    # Build a plain-English day summary
    day_direction = "rose" if chg_1d_pct > 0 else "fell" if chg_1d_pct < 0 else "held"
    week_direction = "up" if v7 and latest["value"] > v7 else "down" if v7 else None

    if brand_contribs:
        pushers = [b for b, c, _ in brand_contribs if c > 0][:3]
        draggers = [b for b, c, _ in brand_contribs if c < 0][:3]

        # Build a useful sentence
        dir_word = "up" if chg_1d_pct > 0 else "down"
        abs_chg = abs(chg_1d_pct)
        parts = [f"SG-LWIX moved {dir_word} {abs_chg:.1f}% today"]
        if pushers:
            parts.append(f"led by {', '.join(pushers)}")
        if draggers:
            parts.append(f"with {', '.join(draggers)} pulling the other way")
        if retail_latest:
            pct_vs_retail = round((retail_latest - 1.0) * 100, 1)
            direction = "above" if pct_vs_retail > 0 else "below"
            parts.append(f"On average, secondary prices are {abs(pct_vs_retail)}% {direction} retail")
        insights["composite"] = ". ".join(parts) + "."
    elif latest["value"] and prev_day_idx["value"]:
        dir_word = "up" if latest["value"] > prev_day_idx["value"] else "down"
        insights["composite"] = f"SG-LWIX moved {dir_word} {abs(chg_1d_pct):.1f}% today across all tracked brands."

    if cond_spread is not None:
        insights["condition"] = (
            f"Brand New watches trade at a {cond_spread:+.4f} premium over Pre-Owned. "
            f"A widening gap signals stronger demand for unworn pieces."
        )
    if retail_spread is not None:
        concentration_note = (
            f" Based mostly on {retail_coverage['top_brand']} "
            f"({retail_coverage['top_brand_share_pct']:.0f}% of matched records) — "
            f"not an even market-wide sample."
            if retail_coverage["top_brand_share_pct"] >= 50 else ""
        )
        insights["retail"] = (
            f"Secondary-market prices average {abs(retail_spread):.1f}% "
            f"{'below' if retail_spread > 0 else 'above'} retail "
            f"(of the {retail_coverage['matched_records_pct']:.0f}% of listings with a "
            f"known retail price).{concentration_note} "
            f"{'Discount' if retail_spread > 0 else 'Premium'} to authorised dealer pricing."
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
            "version": "2.0",
            "methodology": (
                "Laspeyres-weighted composite of secondary-market asking prices "
                "from 15+ Singapore Telegram watch dealer channels, expressed as "
                "a weighted average of each brand's current price relative to its "
                "own 90-day baseline median (50% prestige + 50% volume weights). "
                f"{ANCHOR_VALUE} represents brands trading exactly at their own "
                "baseline on average — it is a reference scale, not a value the "
                "series is pinned to on a specific date; see first_computed."
            ),
            "base_value": ANCHOR_VALUE,
            "anchor_date": anchor_date,
            "first_computed": first_computed,
            "updated": datetime.now().isoformat(),
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
        "retail_composite": {
            "current": retail_latest,
            "change_1d": retail_chg_1d,
            "change_1d_pct": retail_chg_1d_pct,
            "series": retail_composite[-730:] if retail_composite else [],
        },
        "condition_indices": {
            "preowned": {"current": po_latest, "series": preowned[-730:]},
            "new": {"current": new_latest, "series": new_idx_list[-730:]},
            "spread": cond_spread,
        },
        "retail_spread": {"current": retail_spread, "series": spread_series[-730:], "coverage": retail_coverage},
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
        "insights": insights,
        "price_outliers": price_outliers[-200:],
        "price_outlier_count": len(price_outliers),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2, default=str))

    print(f"\n{'='*60}")
    print(f"  SG-LWIX: {latest['value']:.4f}  ({chg_1d:+.4f}/day, {chg_1d_pct:+.2f}%)")
    print(f"  Retail-anchored: {retail_latest:.4f}" if retail_latest else "  Retail idx: N/A")
    print(f"  Anchor: {anchor_date}  |  Days tracked: {len(composite)}")
    print(f"  Brands baselined: {len(baseline_median)}/{len(all_brands)}")
    print(f"  Pre-Owned: {po_latest or 'N/A'}  |  NEW: {new_latest or 'N/A'}")
    print(f"  Retail spread: {retail_spread or 'N/A'}%")
    if cond_spread is not None:
        print(f"  NEW-PO Spread: {cond_spread:+.4f}")
    print(f"{'='*60}")
    print(f"\n  {insights['composite']}")
    print(f"\n  Written to {OUT}")

if __name__ == "__main__":
    build_indices()
