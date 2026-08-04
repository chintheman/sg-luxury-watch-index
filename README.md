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

## Index Methodology (v2)

- **Type:** Laspeyres-weighted composite
- **Brand weights:** 50% horological prestige (0–10) + 50% listing volume (6mo rolling)
- **Baseline:** Per-brand 180-day window median from first appearance
- **Scale:** 1.0 represents brands trading exactly at their own baseline on
  average — it's a reference scale, not a value pinned to a specific date.
  See index.json's `meta.first_computed` for the actual first computed
  value/date.
- **Window:** 3-day rolling median per brand (smooths sparse daily data)
- **Thresholds:** 3 listings per brand (needed for the median to actually
  resist an outlier), 3+ brands for valid composite day
- **Gap filling:** Carry-forward of last valid value, marked `stale: true`

## Data Sources

15 Singapore-based Telegram watch dealer channels scraped via public `t.me/s/` pages — pure HTTP, no API key needed.

## Sold Detection

Three-layer system:
1. **Keyword filter** — rejects messages containing "SOLD"
2. **Sold tracer** — cross-references SOLD messages against active listings by item number (GML####), batch markers, or brand+model
3. **Time-based expiry** — listings older than 14 days are automatically dropped

## Requirements

- Python 3.10+
- `requests`, `beautifulsoup4`
