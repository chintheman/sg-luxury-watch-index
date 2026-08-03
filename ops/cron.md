# Scheduled pipeline — cron as code

Zo automations live in Zo's own scheduler, not in this repo, and there is no
API to export them. This file is the authoritative record: if the automation
is lost or altered, restore it from here.

## Automation

| Field | Value |
|---|---|
| id | `ae2776ca-440f-4ef6-bf32-1af550a66acd` |
| title | Run SG Luxury Watch Index Incremental Scraper |
| schedule | `DTSTART;TZID=Asia/Singapore:20260621T160906` / `RRULE:FREQ=DAILY;BYHOUR=12,18` |
| timezone | Asia/Singapore (12:00 and 18:00 SGT) |
| delivery | Telegram — group "(Project) Luxury Watch Index" |
| active | yes |

## Instruction (current — one command)

```
Run the SG Luxury Watch Index pipeline:

1. cd /home/workspace/projects/sg-luxury-watch-index && python3 pipeline.py 2>&1

2. Upload the refreshed index as a space asset:
   update_space_asset with
     source_file: /home/workspace/projects/sg-luxury-watch-index/data/index.json
     asset_path:  /data/watch-index.json

Report to the Telegram group "(Project) Luxury Watch Index":
- Current SG-LWIX value and day-over-day change
- Listings exported, and how many were dropped (expired / sold / dead links)
- Any line under "Anomalies flagged for review" — quote these verbatim
- Any channel reporting zero new messages
```

## Why this replaced the previous instruction

The automation used to invoke the three scripts by hand:

```
python3 scraper/scraper.py
python3 index/export_pipeline.py
python3 index/index_engine.py
```

That was wrong in four ways, all silent:

1. **`pipeline.py` never ran**, so its entire anomaly-check layer was dead
   code. The composite moved −11.3% in one day — past the 8% alert threshold —
   and nothing was reported. It also never surfaced unbranded listings or a
   stalled index.
2. **`--link-check` never ran**, so dead `t.me` links were never pruned. When
   it was finally run, the composite moved 1.2879 → 1.3294 purely from
   dropping listings that no longer resolve.
3. **The index was built twice.** `export_pipeline.py`'s `__main__` already
   calls `recalc_index()`; running `index_engine.py` afterwards repeated the
   whole computation.
4. **The comment claimed "last 90 days"** while `export_pipeline.py` defaults
   to a 14-day expiry window.

`pipeline.py` runs scrape → export (with link-check) → anomaly check →
deployed-route drift check, and takes roughly 3 minutes end to end.

## Retained step: the space asset

The instruction also uploads `data/index.json` to the space asset
`/data/watch-index.json`. Nothing in this repo or in `0xsteamboat-me` reads
it — the live API route reads `data/index.json` from disk directly — so it
looked like dead weight.

It was kept anyway. `https://0xsteamboat.zo.space/data/watch-index.json`
returns HTTP 200, so it is a live public URL and an external consumer cannot
be ruled out from inside the codebase. Dropping the step would not delete the
asset; it would leave it silently serving stale data, which is worse than
either keeping it or deleting it outright. Remove it only after confirming
nothing external polls it.
