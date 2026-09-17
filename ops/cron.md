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

## Telegram group delivery — known failure (2026-08-10)

The report's intended target, the group "(Project) Luxury Watch Index" (chat ID `-5370852148`), is reachable by the Hermes bot but NOT by Zo's Telegram bot (`@steamboat0x0`) — `send_telegram_message` fails with "No Telegram binding found for recipient". The run falls back to the user's DM. To restore in-group delivery: add Zo's bot to the group (as admin), or change the automation's delivery target.

Update 2026-08-20: `hermes send --to telegram:-5370852148` now also fails with
`Telegram send failed: Unauthorized`, and the group no longer appears in
`hermes send --list telegram` — the Hermes bot has lost access to the group
as well (removed, or bot token rotated). Both bots are out; fallback to the
user's DM is the only working path until one bot is re-added to the group as
admin.

Update 2026-09-10: still unreachable. `send_telegram_message` to
`-5370852148` → "No Telegram binding found for recipient"; `hermes send
--to telegram:-5370852148` → `Telegram send failed: Unauthorized`. `hermes
send --list telegram` now shows only the DM (`telegram:0xsteamboat`) and one
other group, `telegram:Collab` (`-5510157259`) — a different chat ID, so the
original group is gone from both bots' scopes, not renamed. Report continues
to fall back to the user's DM.

Update 2026-09-12: unchanged. `send_telegram_message` to `-5370852148` →
"No Telegram binding found for recipient '-5370852148'. Connected accounts:
steamboat0x0." Report delivered to the user's DM instead.

Update 2026-09-13: unchanged. `hermes send --list telegram` still shows only
`telegram:0xsteamboat` and `telegram:Collab`; group `-5370852148` is absent
from both bots' scopes. Report delivered to the user's DM instead. Pipeline
itself healthy: exit 0, 150 new messages across 14 channels, composite 1.1015
(−0.41% 1d), 2 anomaly flags, route drift and page contract both clean.
Zero-new-message channel this run: `goldmanluxurysg` (still at message id 544,
verified directly against t.me/s/goldmanluxurysg).

(Note on the 2026-09-13 run: the direct group send was not exercised — the run
hit the per-turn limit on `send_telegram_message` first, so the "unreachable"
call rests on `hermes send --list telegram` (group absent from both bots'
scope, unchanged from 2026-09-12) plus the 2026-09-12 result. The DM fallback
delivered successfully.)

Update 2026-09-13 (18:00 SGT run): unchanged. Direct group send not
re-attempted — `hermes send --list telegram` still shows only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`); group
`-5370852148` absent from both bots' scopes. Report delivered to the user's
DM. Pipeline healthy: exit 0, 134 new messages across 14 channels, composite
`1.1013` (−0.30% 1d), 2 anomaly flags, route drift and page contract both
clean, asset refreshed. Zero-new-message channels this run: `ChuanwatchSG`,
`watchcapital`, `goldmanluxurysg`, `sgwatchinsider`, `HengWatch`, `kbluxury`,
`watchhunts`.

Update 2026-09-13 (18:15 SGT, mid-run state): Hermes has now lost Telegram
delivery entirely, not just the group. `hermes send --to telegram:0xsteamboat`
(the DM target that was working on 2026-09-12) → `Telegram send failed:
Unauthorized`, despite `hermes send --list telegram` still listing
`telegram:0xsteamboat` and `telegram:Collab`. So Hermes' bot token is dead or
rotated, and `send_telegram_message` to the DM is the only remaining Telegram
path. On this run that path then hit the per-turn limit (3 calls) before
delivering, so the report went out by email instead. Two separate failures to
fix: (1) Zo's bot `@steamboat0x0` is not in group `-5370852148`; (2) Hermes'
Telegram credentials are rejected. Until at least one is resolved, expect
either DM-only delivery or the per-turn limit to swallow a run when a group
send is attempted first.

Update 2026-09-14 (12:00 SGT run): unchanged. `send_telegram_message` to
`-5370852148` → "No Telegram binding found for recipient '-5370852148'.
Connected accounts: steamboat0x0." Report delivered to the user's DM instead.
Pipeline healthy: exit 0, 144 new messages across 14 channels, composite
`1.1030` (+1.33% 1d, +0.0145), 2 anomaly flags, route drift and page contract
both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`).
Zero-new-message channels this run (9): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`,
`kbluxury`, `tagtimesingapore`, `watchhunts`.

Update 2026-09-14 (18:00 SGT run): unchanged. `send_telegram_message` to
`-5370852148` → "No Telegram binding found for recipient '-5370852148'.
Connected accounts: steamboat0x0." Report delivered to the user's DM instead.
Pipeline healthy: exit 0, 183 new messages across 14 channels, composite
`1.1036` (+0.94% 1d, +0.0103), 2 anomaly flags, route drift and page contract
both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`).
Zero-new-message channels this run (6): `watchdistrictsg`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`.

Update 2026-09-15 (12:00 SGT run): unchanged on both fronts. Direct group send
re-attempted — `send_telegram_message` to `-5370852148` → "No Telegram binding
found for recipient '-5370852148'. Connected accounts: steamboat0x0."
`hermes send --list telegram` still shows only `telegram:0xsteamboat` and
`telegram:Collab` (`-5510157259`); group `-5370852148` absent from both bots'
scopes. Report delivered to the user's DM. Pipeline healthy: exit 0, 195 new
messages across 14 channels, composite `1.1032` (+0.50% 1d, +0.0055), 2 anomaly
flags, route drift and page contract both clean, asset refreshed (verified live
at `https://0xsteamboat.zo.space/data/watch-index.json`, size 413072, updated
2026-09-15T12:15:34+08:00).
Zero-new-message channels this run (5): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `watchhunts`.

Update 2026-09-15 (12:00 SGT run): unchanged for the group. `send_telegram_message`
to `-5370852148` → "No Telegram binding found for recipient '-5370852148'.
Connected accounts: steamboat0x0." `hermes send --list telegram` still shows
only `telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`); group
`-5370852148` absent from both bots' scopes.

Delivery on this run went by EMAIL, not DM. The failed group attempt counted
against the per-turn `send_telegram_message` limit, so the DM fallback was
refused with "STOP: Do not call send_telegram_message again this turn." The
instruction to "report to the group" therefore costs the DM fallback whenever
the group send is attempted and fails. Recommended change: read
`hermes send --list telegram` first and skip the group attempt entirely when
`-5370852148` is absent, so the one available Telegram call goes to the DM.

Pipeline healthy: exit 0, 195 new messages across 14 channels, composite
`1.1032` (+0.50% 1d, +0.0055), 2 anomaly flags, route drift and page contract
both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, 413072 bytes).
Zero-new-message channels this run (5): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `watchhunts`.

Update 2026-09-15 (18:00 SGT run): unchanged for the group — and the group send
was NOT attempted this run. Per the recommendation above, `hermes send --list
telegram` was read first: it shows only `telegram:0xsteamboat` and
`telegram:Collab` (`-5510157259`), so group `-5370852148` remains absent from
both bots' scopes and the single available Telegram call went to the DM
instead. That worked: the report was delivered on the first
`send_telegram_message` call with the DM as the only target, no per-turn limit
hit. This is the pattern to keep using until one bot is re-added to the group.

Pipeline healthy: exit 0, 149 new messages across 14 channels, composite
`1.1004` (+0.61% 1d, +0.0067), 2 anomaly flags, route drift and page contract
both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 413164 bytes,
updated 2026-09-15T18:15:32+08:00).
Zero-new-message channels this run (5): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
carry uncommitted local modifications (pre-existing, not from this run). The
pipeline's route-drift check still reports the deployed route matching the repo;
left uncommitted deliberately rather than folded into an ops log commit.

Update 2026-09-16 (12:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 163 new messages across 14
channels, composite `1.0982` (−0.46% 1d, −0.0051), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 414242 bytes,
updated 2026-09-16T12:16:29+08:00).
Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`, `tagtimesingapore`,
`watchhunts`.

Update 2026-09-16 (18:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 119 new messages across 14
channels, composite `1.0959` (−0.61% 1d, −0.0067), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 414278 bytes,
updated 2026-09-16T18:16:22+08:00).
Zero-new-message channels this run (4): `watchcapital`, `goldmanluxurysg`,
`sgwatchinsider`, `HengWatch`.

Note on reconstructing per-channel counts: this run's stdout was piped through
`tail`, so the zero-new list was rebuilt from `raw_messages.scraped_at` within
the run window 10:10:13–10:11:00 UTC. `scraped_at` is UTC and `first_seen_at`
is SGT — do not mix the two, or you will silently pull rows from the wrong
window. The per-channel sums total 119, exactly matching the scraper's reported
total, which is what validates the method. Re-running the pipeline to
regenerate the log is NOT a valid fix: by then the incremental scraper has
already saved those messages, so a second run reports 0 new for every channel
and the zero-new answer becomes a false positive across the board.

Update 2026-09-17 (12:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 166 new messages across 14
channels, composite `1.0962` (+1.92% 1d, +0.0207), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 415389 bytes,
reads back composite `1.0962` / `+1.92`).
Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`, `kbluxury`, `watchhunts`.

Update 2026-09-17 (12:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 166 new messages across 14
channels, composite `1.0962` (+1.92% 1d, +0.0207), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 415389 bytes,
returning composite 1.0962 / +1.92%).
Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`, `kbluxury`, `watchhunts`.

Update 2026-09-17 (18:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 153 new messages across 14
channels, composite `1.0979` (+1.17% 1d, +0.0127), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 415386 bytes,
reads back composite `1.0979`).
Zero-new-message channels this run (7): `watchdistrictsg`, `ChuanwatchSG`,
`watchcapital`, `goldmanluxurysg`, `sgwatchinsider`, `HengWatch`,
`tagtimesingapore`.

Note: the two 2026-09-17 12:00 entries above are duplicates of each other
(appended by the same run, `358e4ff` / `365698f`) — not two separate runs.
