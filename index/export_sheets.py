#!/usr/bin/env python3
"""Export everything we track to CSVs you can open in a spreadsheet.

Most of what this project extracts is never shown on the page — case
material, box and papers, warranty, dial variant, time to sell, price cuts,
attention. This writes it all out so trends can be explored before deciding
what is worth publishing.

Written to /home/workspace/watch-index-data/ (outside the repo, since it is
generated output) and refreshed on every pipeline run.

Files:
  listings.csv        one row per published listing, every extracted field
  index_history.csv   the composite and its sub-series over time
  brand_summary.csv   per-brand rollup: volume, price levels, speed, attention
  sold.csv            confirmed sales with days-to-sell
  price_changes.csv   watches whose asking price moved while listed
  references.csv      per-reference fair asking range and sample size
  reference_history.csv  monthly median asking price per reference
  README.md           what each column means and what not to trust
"""
import csv
import json
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))

OUT_DIR = Path("/home/workspace/watch-index-data")
DATA = ROOT / "data"


def _load(name):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def _write(name, header, rows):
    path = OUT_DIR / name
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def export():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    listings = _load("listings.json") or []
    index = _load("index.json") or {}
    signals = _load("signals.json") or {}
    refs = _load("references.json") or {}
    removed = _load("removed.json") or {}
    written = {}

    # ── listings.csv ──
    cols = [
        ("channel", "c"), ("message_id", "m"), ("date", "d"), ("brand", "b"),
        ("model", "md"), ("reference", "ref"), ("price_sgd", "p"),
        ("condition", "n"), ("case_size_mm", "case_size_mm"),
        ("case_material", "case_material"), ("bracelet", "bracelet"),
        ("box_papers", "box_papers"), ("warranty", "warranty"),
        ("year_stated", "year"), ("dial_colour", "dial_colour"),
        ("dial_nickname", "dial_nickname"), ("dealer_stock_code", "stock_code"),
        ("photos", "f"), ("views", "v"), ("link", "l"),
    ]
    rows = []
    for l in listings:
        row = [l.get(k) for _, k in cols]
        dup = l.get("dup") or {}
        row += [dup.get("times_listed"), dup.get("first_price"),
                dup.get("price_change_pct"), dup.get("days_listed")]
        rows.append(row)
    written["listings.csv"] = _write(
        "listings.csv",
        [n for n, _ in cols] + ["times_listed", "first_price",
                                "price_change_pct", "days_on_market"],
        rows)

    # ── index_history.csv ──
    def series(key, sub=None):
        node = index.get(key) or {}
        return {p["date"]: p.get("value") for p in (node.get("series") or [])}
    comp = (index.get("composite") or {}).get("series") or []
    po = series("condition_indices")
    pre = {p["date"]: p.get("value")
           for p in ((index.get("condition_indices") or {}).get("preowned") or {}).get("series", [])}
    new = {p["date"]: p.get("value")
           for p in ((index.get("condition_indices") or {}).get("new") or {}).get("series", [])}
    avail = series("availability")
    rows = []
    for p in comp:
        d = p["date"]
        rows.append([d, p.get("value"), p.get("stale"), p.get("brands_tracked"),
                     p.get("total_listings"), pre.get(d), new.get(d),
                     avail.get(d)])
    written["index_history.csv"] = _write(
        "index_history.csv",
        ["date", "composite", "is_carried_forward", "brands_tracked",
         "listings_in_window", "preowned_index", "new_index",
         "availability_score"], rows)

    # ── brand_summary.csv ──
    counts = index.get("brand_counts") or {}
    weights = index.get("brand_weights") or {}
    subs = index.get("brand_subindices") or {}
    speed = ((signals.get("time_to_sell") or {}).get("by_brand")) or {}
    withheld = ((signals.get("time_to_sell") or {})
                .get("by_brand_withheld_too_few_sales")) or {}
    attention = ((signals.get("attention") or {})
                 .get("relative_attention_by_brand")) or {}
    prices = {}
    for l in listings:
        if l.get("b") and l.get("p"):
            prices.setdefault(l["b"], []).append(l["p"])
    rows = []
    for b in sorted(set(counts) | set(prices)):
        sp = speed.get(b) or {}
        rows.append([
            b, counts.get(b), round(weights.get(b, 0), 5) if b in weights else None,
            (subs.get(b) or {}).get("current"),
            len(prices.get(b, [])) or None,
            int(median(prices[b])) if prices.get(b) else None,
            min(prices[b]) if prices.get(b) else None,
            max(prices[b]) if prices.get(b) else None,
            sp.get("median"), sp.get("n") or withheld.get(b),
            "yes" if b in speed else ("too few sales" if b in withheld else "no sales seen"),
            attention.get(b),
        ])
    written["brand_summary.csv"] = _write(
        "brand_summary.csv",
        ["brand", "listings_180d", "index_weight", "brand_index",
         "live_listings", "median_price_sgd", "min_price_sgd", "max_price_sgd",
         "median_days_to_sell", "sales_observed", "speed_published",
         "relative_attention"], rows)

    # ── sold.csv ──
    rows = [[k, v] for k, v in (removed.get("reasons") or {}).items()]
    written["sold.csv"] = _write("sold.csv", ["listing_id", "why"], rows)

    # ── price_changes.csv ──
    rows = []
    for l in listings:
        d = l.get("dup") or {}
        if d.get("price_change_pct") is None:
            continue
        rows.append([l.get("b"), l.get("md"), l.get("ref"), l.get("c"),
                     d.get("first_price"), d.get("last_price"),
                     d.get("price_change_pct"), d.get("days_listed"),
                     d.get("times_listed")])
    rows.sort(key=lambda r: r[6])
    written["price_changes.csv"] = _write(
        "price_changes.csv",
        ["brand", "model", "reference", "channel", "first_price", "last_price",
         "change_pct", "days_on_market", "times_listed"], rows)

    # ── references.csv ──
    cards = refs.get("references") or []
    rows = []
    for c in cards:
        specs = c.get("specs") or {}
        def spec(name):
            s = specs.get(name)
            return s["value"] if s else None
        tts = c.get("time_to_sell") or {}
        cuts = c.get("price_cuts") or {}
        rows.append([
            c.get("slug"), c.get("brand"), c.get("ref"), c.get("model"),
            c.get("confidence"), c.get("n_recent"), c.get("n_total"),
            c.get("fair_low"), c.get("median"), c.get("fair_high"),
            c.get("spread_pct"), c.get("low"), c.get("high"),
            c.get("first_seen"), c.get("last_seen"), c.get("days_since_last_seen"),
            c.get("channels"), spec("case_size_mm"), spec("case_material"),
            spec("bracelet"), spec("dial_colour"), spec("box_papers"),
            tts.get("median"), c.get("sales_observed"),
            cuts.get("cut"), cuts.get("median_cut_pct"), cuts.get("median_days_listed"),
        ])
    written["references.csv"] = _write(
        "references.csv",
        ["slug", "brand", "reference", "model", "confidence", "n_recent",
         "n_total", "fair_low", "median_asking", "fair_high", "spread_pct",
         "lowest", "highest", "first_seen", "last_seen", "days_since_last_seen",
         "channels", "case_size_mm", "case_material", "bracelet", "dial_colour",
         "box_papers", "median_days_to_sell", "sales_observed", "price_cuts",
         "median_cut_pct", "median_days_listed"], rows)

    # ── reference_history.csv ── long format, one row per reference-month
    rows = []
    for c in cards:
        for m in c.get("monthly") or []:
            rows.append([c.get("slug"), c.get("brand"), c.get("ref"),
                         c.get("model"), m["month"], m["median"], m["n"]])
    written["reference_history.csv"] = _write(
        "reference_history.csv",
        ["slug", "brand", "reference", "model", "month", "median_asking",
         "listings"], rows)

    _write_readme(index, signals, written)
    print("Sheets: " + ", ".join(f"{k} ({v})" for k, v in written.items())
          + f" -> {OUT_DIR}")
    return written


def _write_readme(index, signals, written):
    tts = (signals.get("time_to_sell") or {})
    cov = tts.get("coverage") or {}
    (OUT_DIR / "README.md").write_text(f"""# SG watch index — extracted data

Regenerated on every pipeline run (12:00 and 18:00 SGT). Open the CSVs in any
spreadsheet. Generated {index.get('meta', {}).get('updated', '?')}, index
version {index.get('meta', {}).get('version', '?')}.

| file | rows | what it is |
|---|---|---|
| `listings.csv` | {written.get('listings.csv', 0)} | every live listing with all extracted attributes |
| `index_history.csv` | {written.get('index_history.csv', 0)} | the index and sub-indices over time |
| `brand_summary.csv` | {written.get('brand_summary.csv', 0)} | per-brand rollup — the best sheet to start from |
| `price_changes.csv` | {written.get('price_changes.csv', 0)} | watches whose asking price moved while listed |
| `sold.csv` | {written.get('sold.csv', 0)} | listings confirmed sold this run |
| `references.csv` | {written.get('references.csv', 0)} | per-reference fair asking range — the price-card data |
| `reference_history.csv` | {written.get('reference_history.csv', 0)} | monthly median asking price per reference |

## Read these before drawing conclusions

**These are asking prices, not sales.** What dealers want, not what they got.

**`is_carried_forward` in index_history.csv matters.** When true, that day had
too little data to compute and the previous value was carried forward. About
70% of days are carried forward. Filter them out before plotting a trend.

**`median_days_to_sell` covers {cov.get('pct_of_watches', '?')}% of watches.**
A sale is only visible when the dealer posts a SOLD reply, and most do not.
Brands with fewer than {tts.get('min_sales_to_publish_a_brand', 8)} observed
sales are left blank rather than shown — see `speed_published`. Because only
*confirmed* sales appear, watches that never sell are invisible, so these
figures skew fast.

**`relative_attention` is indexed per channel**, where 1.0 is typical for the
channel a watch was posted on. Raw view counts mostly measure how many
subscribers a channel has, not interest in the watch.

**Blank is not zero.** An empty `box_papers` means the listing did not say,
not that the watch has no box.

**`times_listed` above 1 means the same watch was posted repeatedly.** Those
rows are already collapsed to one; the raw feed is about 78% larger than the
real number of watches.

**`fair_low`/`fair_high` in references.csv is an interquartile range** over the
last 90 days: half of current asking prices sit inside it. Always read it next
to `n_recent`. Rows marked `confidence = limited` have 10-19 listings behind
them, which is enough to be indicative and not enough to be authoritative.

**Specifications in references.csv are the most common value across listings,**
not a verified catalogue spec. Where dealers describe a watch inconsistently
the majority wins, so treat them as a strong hint rather than a fact.

**`reference_history.csv` suppresses months with fewer than 3 listings.** A
monthly median built on one listing is one dealer's asking price drawn as a
market level, so those months are absent rather than plotted.
""")


if __name__ == "__main__":
    export()
