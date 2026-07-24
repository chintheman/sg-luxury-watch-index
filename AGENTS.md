# SG Luxury Watch Index — AGENTS.md

> Project root for the Singapore Luxury Watch Price Index. Real-time composite index of pre-owned watch asking prices scraped from 15 SG Telegram dealer channels.

## Quick Start

```bash
cd /home/workspace/projects/sg-luxury-watch-index

# Full pipeline (scraper → export → index)
python3 pipeline.py

# Individual steps:
python3 scraper/scraper.py           # Incremental scrape (new messages only)
python3 scraper/scraper.py --full    # Full history re-scrape
python3 scraper/scraper.py --list    # DB stats
python3 index/export_pipeline.py     # Export listings.json + recalc index
python3 index/index_engine.py        # Index recalculation only
```

## Architecture

```
projects/sg-luxury-watch-index/
├── pipeline.py          # Full pipeline (scraper → export → index)
├── scraper/
│   └── scraper.py       # Layer 1 — t.me/s/ scraper (HTTP + BeautifulSoup + SQLite)
├── parser/
│   └── filter.py        # Layer 2 — Listing filter: brand detection, price extraction, noise rejection
├── index/
│   ├── index_engine.py  # Layer 3 — SG-LWIX composite index engine
│   └── export_pipeline.py # Export listings.json + trigger index recalc
├── data/
│   ├── listings.db      # raw_messages table (~15K rows)
│   ├── listings.json    # Exported listings (last 90 days, with brand/price/condition)
│   ├── index.json       # SG-LWIX output → uploaded as space asset /data/watch-index.json
│   └── scraper_log.json # Run history
└── AGENTS.md
```

## Index Methodology (v2.0)

- **Type:** Laspeyres-weighted composite
- **Brand weights:** 50% Horological Prestige (0–10 scale) + 50% Listing Volume (6mo rolling)
- **Baseline:** Per-brand 180-day window median from first appearance
- **Scale:** 1.0 represents brands trading exactly at their own baseline on
  average. anchor_date (50%+ brands baselined) is a data-sufficiency
  milestone, not a date the series is pinned to — it usually doesn't have
  enough brands to compute a value itself. See index.json's
  `meta.first_computed` for the actual first computed value/date.
- **Window:** 3-day rolling median per brand (smooths sparse daily data)
- **Thresholds:** 3 listings per brand (median needs 3+ to actually resist
  an outlier), 3+ brands required for valid composite day
- **Gap filling:** Carry-forward of last valid value, marked `stale: true`
  on every carried-forward point so it's distinguishable from a fresh one

## Key Decisions

- **Sparse data strategy:** 3-day rolling window × 3-brand minimum eliminates noise. Before this fix (2026-06-21), single-brand days could swing the index ±100%.
- **Web-only scraping:** HTTP + BeautifulSoup against t.me/s/ — no API key, no Telethon.
- **Data lives on Zo:** Full pipeline runs via hourly automation (`ae2776ca`).
- **Condition sub-indices (Pre-Owned vs NEW):** Computed but noisy — NEW listings are scarce.

## Automation

- **`ae2776ca`** — "Run SG Luxury Watch Index Incremental Scraper" — runs every 6h, scrapes → exports → recalculates → uploads asset → reports to Telegram

## Known Issues

- Only 3 of 15 channels consistently have new daily messages; others are fully scraped or inactive.
- **NEW condition sub-index is unreliable** — Brand New listings make up only ~14% of all priced listings (462 vs 2,366 Pre-Owned). The sub-index spikes dramatically (daily swings ±40% are common) because individual brands have 0-5 Brand New listings per rolling window. When a Rolex Daytona BN is listed at $45K and the only Rolex BN listing from the previous week was a Datejust at $15K, the median jumps 3×.
  - **Fix path:** Increase the rolling window for condition sub-indices from 3 days to 14 days (smooths sparse BN data) and require minimum 2 listings per brand for a valid BN sub-index day instead of 1.
- **8 brands lack baselines** (total counts across all messages):
  - Hermes: 1 listing (single listing, Jun 2026)
  - Bulgari: 2 listings (Apr–May 2026)
  - Girard-Perregaux: 2 listings (May–Jun 2026)
  - Corum: 4 listings (May 2023 – May 2026, extremely sparse)
  - Sinn: 6 listings (Dec 2025 – Jun 2026)
  - Oris: 9 listings (Oct 2022 – Jun 2026)
  - Chopard: 24 listings over 3+ years (Apr 2023 – Jun 2026)
  - Breitling: 61 total listings, but these are spread thinly across years — the 180-day baseline window finds <3 in any one period.
  The index engine requires ≥3 samples in a brand's first 180-day window to establish a baseline. These brands simply don't appear often enough in SG dealer channels. The baseline algorithm is working correctly; the data is just too sparse.
  - **Fix path:** Lower baseline threshold to 2 samples, or relax the 180-day window to 365 days for low-volume brands. Accept that brands with <10 total listings will never have meaningful sub-indices.

## Sold Detection

Three-layer system to keep the website clean:

1. **Keyword filter** (`parser/filter.py`): Rejects any message containing "SOLD" — prevents SOLD messages from becoming listings
2. **Sold tracer** (`sold_tracer.py`): Cross-references SOLD messages against active listings by item number (GML####), batch parsing, and brand+model matching. Outputs `data/removed.json`
3. **Time-based expiry** (`index/export_pipeline.py`): Listings older than 14 days are automatically dropped
4. **Link checking** (optional, `--link-check` flag): Verifies each t.me link still resolves; dead links are removed

The sold tracer matches with three strategies (in priority order):
- Item number match (Goldman Luxury SG: GML3589 → find same GML in active listing)
- Batch SOLD parsing (SG Watch Insider: parse ❌ markers in batch posts)
- Brand + model match (same channel, same brand/model, SOLD posted after listing)
