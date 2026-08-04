# SG Luxury Watch Index (SG-LWIX)

Real-time composite price index for Singapore's pre-owned luxury watch market. Aggregates asking prices from 15+ Telegram dealer channels, producing a volume-weighted, matched-model composite with brand sub-indices and condition spreads.

## Quick Start

```bash
# Full pipeline
python3 pipeline.py

# Individual steps
python3 scraper/scraper.py              # Incremental scrape (new messages only)
python3 scraper/scraper.py --full       # Full history re-scrape
python3 scraper/scraper.py --list       # DB stats
python3 index/export_pipeline.py        # Export listings JSON + recalc index
python3 index/index_engine.py           # Index recalculation only
```

## Architecture

```
├── pipeline.py              # Full pipeline orchestration
├── scraper/
│   └── scraper.py           # Layer 1 — t.me/s/ HTTP scraper (BeautifulSoup + SQLite)
├── parser/
│   └── filter.py            # Layer 2 — listing filter: brand detection, price extraction, noise rejection
├── index/
│   ├── index_engine.py      # Layer 3 — SG-LWIX composite index engine (v2)
│   └── export_pipeline.py   # Export listings JSON + sold tracing + trigger index
└── sold_tracer.py           # Cross-references SOLD messages against active listings
```

## Index Methodology (v3.1)

Every listing is compared only against its own trading history — never
against a list price, and never against other models. See METHODOLOGY.md for
the full write-up and the v2 → v3 break.

- **Type:** volume-weighted, matched-model composite
- **Matching unit:** exact reference (8+ listings), else model (3+), else
  brand. Units aggregate up to brands; this covers 99% of listings.
- **Baseline:** median of each unit's **first 30 listings**. Sample-anchored,
  not calendar-anchored — a calendar window silently excluded 26 of 55 brands
  that first appeared after it.
- **Brand weights:** sqrt of recent listing volume, normalised. No prestige
  term: a hand-assigned ranking is volume-blind and does not belong in a
  price index.
- **Scale:** 1.0 represents units trading exactly at their own baseline on
  average — a reference scale, not a value pinned to a specific date. See
  index.json's `meta.first_computed` for the actual first computed
  value/date.
- **Window:** 21-day rolling pool per brand (28 for the condition indices,
  which are much thinner)
- **Thresholds:** 3 listings per brand-day, 3+ brands for a valid composite
  day
- **Outliers:** excluded from baselines, flagged but retained in daily windows
- **Gap filling:** Carry-forward of last valid value, marked `stale: true`.
  Roughly 70% of series days are carried forward.
- **Not measured:** premium/discount vs retail. See METHODOLOGY.md.

## Data Sources

14 Singapore-based Telegram watch dealer channels scraped via public `t.me/s/` pages — pure HTTP, no API key needed. Non-Singapore stock is excluded outright rather than currency-converted.

## Sold Detection

Three-layer system:
1. **Keyword filter** — rejects messages containing "SOLD"
2. **Sold tracer** — cross-references SOLD messages against active listings by item number (GML####), batch markers, or brand+model
3. **Time-based expiry** — listings older than 14 days are automatically dropped

## Requirements

- Python 3.10+
- `requests`, `beautifulsoup4`
