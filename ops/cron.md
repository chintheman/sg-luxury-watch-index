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

Update 2026-09-18 (12:15 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 189 new messages across 14
channels, composite `1.0978` (−0.15% 1d, −0.0016), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 416341 bytes,
reads back composite `1.0978`).
Zero-new-message channels this run (9): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`,
`kbluxury`, `tagtimesingapore`, `watchhunts`.

Note on reconstructing per-channel counts: this run's stdout was piped through
`tail`, so the zero-new list was rebuilt from `raw_messages.scraped_at` within
the run window 04:10:32–04:10:55 UTC. `scraped_at` is UTC and `first_seen_at`
is SGT — do not mix the two. The per-channel sums (watchexchangesg 104,
watchbooksg 56, pngwatchdealer 16, watchdistrictsg 7, thefinesttime 6) total
189, exactly matching the scraper's reported total, which is what validates
the method.

Update 2026-09-18 (18:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent). The single Telegram call went to the DM and delivered
on the first attempt. Pipeline healthy: exit 0, 204 new messages across 14
channels, composite `1.0963` (−0.47% 1d, −0.0052), 2 anomaly flags, route
drift and page contract both clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 416447 bytes,
reads back composite `1.0963`). Export: 2225 listings (1916 priced) exported,
12096 dropped (11788 expired, 308 sold, 0 dead links).
Zero-new-message channels this run (6): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`.

Note on reconstructing per-channel counts: this run's stdout was piped through
`tail`, so the zero-new list was rebuilt from `raw_messages.scraped_at` for
this run (hour 10 UTC) — `scraped_at` is UTC, `first_seen_at` is SGT, do not
mix them. Per-channel sums (watchexchangesg 107, watchbooksg 63,
watchdistrictsg 14, thefinesttime 12, tagtimesingapore 4, watchhunts 2,
kbluxury 1, pngwatchdealer 1) total 204, exactly matching the scraper's
reported total, which is what validates the method. ChuanwatchSG's zero is
corroborated by the printed block order (it precedes `watchbooksg`, which is
the first line `tail` showed).

Update 2026-09-19 (12:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent, so the group send was skipped to preserve the per-turn
limit — Zo's bot membership was not re-tested this run). The single Telegram
call went to
the DM and delivered on the first attempt. Pipeline healthy: exit 0, 147 new
messages across 14 channels, composite `1.1020` (+0.41% 1d, +0.0045), 2 anomaly
flags, route drift and page contract both clean, asset refreshed (verified live
at `https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 417411 bytes,
reads back composite `1.102` / `+0.41`). Export: 2189 listings (1898 priced)
exported, 12222 dropped (11954 expired, 268 sold, 0 dead links).
Zero-new-message channels this run (9): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `thefinesttime`, `watchplayboypteltd`, `sgwatchinsider`,
`kbluxury`, `tagtimesingapore`, `watchhunts`.

Note on reconstructing per-channel counts: this run's stdout was piped through
`tail`, so the zero-new list was rebuilt from the DB. Both windows agreed
exactly — `raw_messages.scraped_at` in UTC (`2026-09-19 04:10:00`–`04:12:00`)
and `first_seen_at` on the SGT date (`2026-09-19`) each summed to 147
(watchbooksg 66, watchexchangesg 52, HengWatch 13, pngwatchdealer 11,
watchdistrictsg 5), matching the scraper's printed total — which is what
validates the method. Prefer `scraped_at` with an explicit window: it does not
depend on the previous run having fallen on a different calendar date.

Useful for future runs: `scraper_log.json`'s `channels[*].last_scrape` is only
written when a channel yields new messages OR edits (`scraper.py` line 352
`if total_new or total_upd:` and line 402 `if total_saved > 0:`), so
a stale `last_scrape` on a zero-new channel is expected, not a signal that the
scrape failed. To separate "quiet" from "broken", check `max(posted_at)` per
channel instead — this run all nine zeros were genuine quiet, with newest posts
ranging from 2026-09-18 07:14 UTC (`watchhunts`) back to 2025-08-10
(`goldmanluxurysg`, dead since Aug 2025, as is `sgwatchinsider` since Jan 2026).

Provenance note (2026-09-19 12:00 SGT run): the entry above was appended to this
file by an unidentified process at 04:26:15 UTC, not by the run's agent — the
file was read at ~04:25 and still ended at the 2026-09-18 18:00 entry. Every
claim in it was re-verified against the pipeline's stdout, `data/index.json` and
`listings.db` before committing (`7ad977d`), and all of them hold. Flagged
because a second writer with access to this repo is itself worth knowing about.

Update 2026-09-19 (18:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent, so the group send was skipped to preserve the per-turn
limit — Zo's bot membership was not re-tested this run). The single Telegram
call went to the DM and delivered on the first attempt. Pipeline healthy: exit
0, 112 new messages across 14 channels, composite `1.1072` (+0.81% 1d, +0.0089),
2 anomaly flags, route drift and page contract both clean, asset refreshed
(verified live at `https://0xsteamboat.zo.space/data/watch-index.json`, HTTP
200, 417400 bytes, reads back composite `1.1072` / `+0.81`). Export: 2204
listings (1898 priced) exported, 12247 dropped (11951 expired, 296 sold, 0 dead
links).
Zero-new-message channels this run (8): `ChuanwatchSG`, `pngwatchdealer`,
`watchcapital`, `goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`,
`HengWatch`, `tagtimesingapore`.

Note on reconstructing per-channel counts: not needed this run — unlike recent
runs, stdout was NOT piped through `tail`, so the printed per-channel blocks
were read directly. The 14 printed per-channel new-message counts
(6+0+74+0+11+0+0+15+0+0+0+1+0+5) sum to 112, exactly matching the scraper's
reported total, which is what validates the zero-new list. Prefer this: it
costs nothing and removes the `scraped_at` (UTC) vs `first_seen_at` (SGT)
window ambiguity entirely.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as the 2026-09-15 entry
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo; left uncommitted rather than folded into this
ops log commit.

Update 2026-09-19 (18:00 SGT run): group still unreachable, group send NOT
attempted (checked `hermes send --list telegram` first — only
`telegram:0xsteamboat` and `telegram:Collab` (`-5510157259`) listed; group
`-5370852148` absent, so the group send was skipped to preserve the per-turn
limit — Zo's bot membership was not re-tested this run). The single Telegram
call went to the DM and delivered on the first attempt. Pipeline healthy:
exit 0, 112 new messages across 14 channels, composite `1.1072`
(+0.81% 1d, +0.0089), 2 anomaly flags, route drift and page contract both
clean, asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 417400 bytes,
reads back composite `1.1072` / `+0.81`). Export: 2204 listings (1898 priced)
exported, 12247 dropped (11951 expired, 296 sold, 0 dead links).
Zero-new-message channels this run (8): `ChuanwatchSG`, `pngwatchdealer`,
`watchcapital`, `goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`,
`HengWatch`, `tagtimesingapore`.

Note on the zero-new list: this run's stdout was captured in full (the `tee`
target path did not exist, but stdout came back intact), so the list is read
straight off the scraper's printed per-channel blocks rather than rebuilt from
the DB — no reconstruction caveat applies. Per-channel new counts:
watchexchangesg 74, thefinesttime 15, watchbooksg 11, watchdistrictsg 6,
watchhunts 5, kbluxury 1, and zeros for the eight above; total 112, exactly
matching the scraper's reported total.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry uncommitted local modifications (pre-existing, not from this run).
The pipeline's route-drift check reports the deployed route matching the repo.

Update 2026-09-20 (12:00 SGT run): group still unreachable — and worse than
before: `hermes send --list telegram` now returns "no targets found for
platform 'telegram'. Configured: (none)" instead of listing
`telegram:0xsteamboat` and `telegram:Collab`. Hermes' Telegram target list is
empty, so the group send was skipped to preserve the per-turn limit and the
single Telegram call went to the DM, delivering on the first attempt.
Pipeline healthy: exit 0, 163 new messages across 14 channels, composite
`1.1040` (+0.06% 1d, +0.0007), 2 anomaly flags, route drift and page contract
both clean. Export: 2200 listings (1887 priced) exported, 12313 dropped
(12051 expired, 262 sold, 0 dead links). Asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 418462 bytes,
reads back composite `1.104` / `+0.06`).
Zero-new-message channels this run (7): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `sgwatchinsider`, `HengWatch`, `kbluxury`,
`tagtimesingapore`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks, no DB reconstruction
needed. Per-channel new counts: watchbooksg 69, watchexchangesg 66,
thefinesttime 14, pngwatchdealer 7, watchdistrictsg 5, watchplayboypteltd 1,
watchhunts 1, and zeros for the seven above. Sum = 163, exactly matching the
scraper's reported total, which is what validates the list.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-21 (18:00 SGT run): group still unreachable, group send NOT
attempted. `hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" (unchanged from the 2026-09-20 12:00 entry —
Hermes' Telegram target list is still empty), so the group send was skipped to
preserve the per-turn limit. The single Telegram call went to the DM and
delivered on the first attempt. Pipeline healthy: exit 0, 170 new messages
across 14 channels, composite `1.0982` (+0.67% 1d, +0.0073), 2 anomaly flags,
route drift and page contract both clean. Export: 2242 listings (1892 priced)
exported, 12394 dropped (12106 expired, 288 sold, 0 dead links). Asset
refreshed (verified live at `https://0xsteamboat.zo.space/data/watch-index.json`,
HTTP 200, 419393 bytes, updated 2026-09-21T18:16:15+08:00, reads back composite
`1.0982` / `+0.67`).
Zero-new-message channels this run (8): `ChuanwatchSG`, `pngwatchdealer`,
`watchcapital`, `goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`,
`HengWatch`, `tagtimesingapore`.

Note on the zero-new list: stdout was captured in full (via `tee`), so the list
is read straight off the scraper's printed per-channel blocks, no DB
reconstruction needed. Per-channel new counts: watchbooksg 83,
watchexchangesg 47, thefinesttime 30, kbluxury 7, watchhunts 2, watchdistrictsg
1, and zeros for the eight above. Sum = 170, exactly matching the scraper's
reported total, which is what validates the list.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-22 (12:00 SGT run): group still unreachable, group send NOT
attempted. `hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" (unchanged from the 2026-09-20 12:00 and
2026-09-21 18:00 entries — Hermes' Telegram target list is still empty), so the
group send was skipped to preserve the per-turn limit. The single Telegram call
went to the DM and delivered on the first attempt. Pipeline healthy: exit 0
(no traceback; stdout ended "✅ Pipeline complete." and `data/scraper_log.json`
recorded the run at 2026-09-22T12:11:18+08:00), 153 new messages across 14
channels, composite `1.0975` (+0.57% 1d, +0.0062), 2 anomaly flags, route drift
and page contract both clean. Export: 2232 listings (1880 priced) exported,
12513 dropped (12249 expired, 264 sold, 0 dead links). Asset refreshed (verified
live at `https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 420284
bytes, reads back composite `1.0975` / `+0.57`).
Zero-new-message channels this run (6): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `kbluxury`.

Note on the zero-new list: stdout was captured in full to a file, so the list is
read straight off the scraper's printed per-channel blocks, no DB reconstruction
needed. Per-channel new counts: watchbooksg 55, watchexchangesg 51,
watchdistrictsg 20, pngwatchdealer 15, thefinesttime 7, HengWatch 2,
tagtimesingapore 2, watchhunts 1, and zeros for the six above. Sum = 153,
exactly matching the scraper's reported total, which is what validates the list.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-22 (18:00 SGT run): group still unreachable, group send NOT
attempted. `hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" (unchanged since the 2026-09-20 12:00 entry), so
the group send was skipped to preserve the per-turn limit. The single Telegram
call went to the DM and delivered on the first attempt. Pipeline healthy: exit
0, 177 new messages across 14 channels, composite `1.0988` (+0.76% 1d, +0.0083),
2 anomaly flags, route drift and page contract both clean. Export: 2277
listings (1911 priced) exported, 12529 dropped (12247 expired, 282 sold, 0 dead
links). Asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 420431 bytes,
updated 2026-09-22T18:17:51+08:00, reads back composite `1.0988` / `+0.76`).
Zero-new-message channels this run (5): `goldmanluxurysg`, `watchplayboypteltd`,
`sgwatchinsider`, `HengWatch`, `tagtimesingapore`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks, no DB reconstruction
needed. Per-channel new counts: watchexchangesg 71, watchbooksg 66,
thefinesttime 14, watchdistrictsg 9, kbluxury 7, ChuanwatchSG 6, pngwatchdealer
2, watchcapital 1, watchhunts 1, and zeros for the five above. Sum = 177,
exactly matching the scraper's reported total, which is what validates the list.
Independent DB cross-check on `raw_messages.scraped_at >= '2026-09-22 10:10:00'`
(UTC, this run's window) reproduced the same nine counts and the same sum, and
`max(posted_at)` per zero channel confirms all five are genuinely quiet, not
broken: watchplayboypteltd 2026-09-20, tagtimesingapore 2026-09-21 14:48 UTC,
HengWatch 2026-09-21 13:15 UTC, and the two long-dead feeds sgwatchinsider
(2026-01-01) and goldmanluxurysg (2025-08-10).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-23 (18:00 SGT run): group still unreachable, group send NOT
attempted (`hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" — unchanged for the fourth consecutive run), so
the single Telegram call went to the DM and delivered on the first attempt.
Pipeline healthy: exit 0 (stdout ended "✅ Pipeline complete."), 136 new messages
across 14 channels, composite `1.0959` (−1.17% 1d, −0.0130; 7d +3.73%, 30d
+7.43%), 1 anomaly flag, route drift and page contract both clean. Export: 2319
listings (1931 priced) exported, 12683 dropped (12417 expired, 266 sold, 0 dead
links). Asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 421379 bytes,
reads back composite `1.0959` / `−1.17`). Also fresh this run: signals (1994
confirmed sales, median 5d; 1726 price cuts, median −2.06%), references (269
published, 138 full confidence), sheets exported to /home/workspace/watch-index-data.
Zero-new-message channels this run (5): `watchcapital`, `goldmanluxurysg`,
`sgwatchinsider`, `HengWatch`, `tagtimesingapore`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks. Per-channel new counts:
watchexchangesg 74, watchbooksg 34, thefinesttime 11, ChuanwatchSG 6,
watchdistrictsg 4, kbluxury 3, pngwatchdealer 2, watchhunts 1, watchplayboypteltd
1, and zeros for the five above. Sum = 136, exactly matching the scraper's
reported total, which is what validates the list. Independent DB cross-check on
`raw_messages.scraped_at >= '2026-09-23 10:10:00'` (UTC, this run's window)
reproduced the same nine counts and the same sum. `max(posted_at)` per zero
channel confirms all five are genuinely quiet, not broken: tagtimesingapore
2026-09-23T02:55Z (10:55 SGT — its 7 messages landed in today's 12:00 run),
watchcapital 2026-09-22T09:25Z, HengWatch 2026-09-21T13:15Z, and the two
long-dead feeds sgwatchinsider (2026-01-01) and goldmanluxurysg (2025-08-10).
Note `first_seen_at` is NOT a usable new-message signal here — it counted 313
rows vs the scraper's 136 because it also reflects re-inserts/backfill; use
`scraped_at` for per-run counts.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-24 (12:00 SGT run): group still unreachable, group send NOT
attempted (`hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" — fifth consecutive run), so the single
Telegram call went to the DM and delivered on the first attempt. Pipeline
healthy: exit 0 (stdout ended "✅ Pipeline complete."), 140 new messages across
14 channels, composite `1.1009` (+0.49% 1d, +0.0054; 7d +2.94%, 30d +6.55%),
1 anomaly flag, route drift and page contract both clean. Export: 2299 listings
(1925 priced) exported, 12820 dropped (12577 expired, 243 sold, 0 dead links).
Asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, md5
`dd98745b11aa2dc10151ea60c58a33e5` matching local, reads back composite `1.1009`
/ `+0.49`). Also fresh this run: signals (2002 confirmed sales, median 5d; 1737
price cuts, median −2.08%), references (268 published, 138 full confidence),
sheets exported to /home/workspace/watch-index-data.
Zero-new-message channels this run (6): `watchcapital`, `goldmanluxurysg`,
`sgwatchinsider`, `HengWatch`, `tagtimesingapore`, `watchhunts`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks. Per-channel new counts:
watchexchangesg 63, watchbooksg 58, watchdistrictsg 5, pngwatchdealer 5,
ChuanwatchSG 4, thefinesttime 3, kbluxury 1, watchplayboypteltd 1, and zeros for
the six above. Sum = 140, exactly matching the scraper's reported total, which is
what validates the list. Independent DB cross-check on
`raw_messages.scraped_at >= '2026-09-24 04:00:00'` (UTC, this run's window)
reproduced the same counts and the same sum. `max(posted_at)` per zero channel
confirms all six are genuinely quiet, not broken: tagtimesingapore
2026-09-23T02:55Z, watchhunts 2026-09-23T08:05Z, watchcapital 2026-09-22T09:25Z,
HengWatch 2026-09-21T13:15Z, and the two long-dead feeds sgwatchinsider
(2026-01-01) and goldmanluxurysg (2025-08-10).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-24 (18:00 SGT run): group still unreachable, group send NOT
attempted (`hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" — sixth consecutive run), so the single
Telegram call went to the DM and delivered on the first attempt. Pipeline
healthy: exit 0 (stdout ended "✅ Pipeline complete."), 111 new messages across
14 channels, composite `1.0943` (+0.21% 1d, +0.0023; 7d +2.70%, 30d +5.92%),
1 anomaly flag, route drift and page contract both clean. Export: 2339 listings
(1954 priced) exported, 12835 dropped (12576 expired, 259 sold, 0 dead links).
Asset refreshed (verified live at
`https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 422393 bytes,
md5 `89f7e0626c6248b750f326f2caf1238f` matching local, reads back composite
`1.0943` / `+0.21`). Also fresh this run: signals (2021 confirmed sales, median
5d; 1739 price cuts, median −2.08%), references (268 published, 138 full
confidence; 169 too thin), sheets exported to /home/workspace/watch-index-data.
Zero-new-message channels this run (4): `goldmanluxurysg`, `watchplayboypteltd`,
`sgwatchinsider`, `tagtimesingapore`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks. Per-channel new counts:
watchexchangesg 36, watchbooksg 30, thefinesttime 11, HengWatch 11,
pngwatchdealer 9, watchdistrictsg 4, ChuanwatchSG 3, watchhunts 3, kbluxury 2,
watchcapital 2, and zeros for the four above. Sum = 111, exactly matching the
scraper's reported total, which is what validates the list. Independent DB
cross-check on `raw_messages.scraped_at >= '2026-09-24 10:10:00'` (UTC, this
run's window) reproduced the same ten counts and the same sum. `max(posted_at)`
per zero channel confirms all four are genuinely quiet, not broken:
watchplayboypteltd 2026-09-23T10:25Z, tagtimesingapore 2026-09-23T02:55Z, and
the two long-dead feeds sgwatchinsider (2026-01-01) and goldmanluxurysg
(2025-08-10).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-25 (12:00 SGT run): group still unreachable, group send NOT
attempted (`hermes send --list telegram` → "no targets found for platform
'telegram'. Configured: (none)" — seventh consecutive run), so the single
Telegram call went to the DM and delivered on the first attempt. Pipeline
healthy: exit 0 (stdout ended "✅ Pipeline complete."), 186 new messages across
14 channels, composite `1.1241` (+2.84% 1d, +0.0310; 7d +6.54%, 30d +8.68%),
1 anomaly flag, route drift and page contract both clean. Export: 2344 listings
(1953 priced) exported, 12993 dropped (12741 expired, 252 sold, 0 dead links).
Signals: 2039 confirmed sales (median 5d), 1752 price cuts, inventory looks
173.1% deeper than it is. References: 276 published (137 full confidence), 166
too thin. 171 price outliers flagged (kept in index). Brand baselines 266/289
units (100% of listings), 40/57 brands; availability_score 40, the lowest in the
series recorded here — worth watching, not yet classified as an anomaly.
Asset refreshed (verified live at `https://0xsteamboat.zo.space/data/watch-index.json`,
HTTP 200, 422695 bytes, md5 `9ad1e5b473d11badd4c4439f9f170760` matching local,
served composite `1.1241` / `2.84`, meta.updated 2026-09-25T12:17:36+08:00).
Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`, `kbluxury`, `watchhunts`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks. Per-channel new counts:
watchexchangesg 77, watchbooksg 65, pngwatchdealer 13, watchdistrictsg 13,
thefinesttime 10, ChuanwatchSG 7, tagtimesingapore 1, and zeros for the seven
above. Sum = 186, exactly matching the scraper's reported total, which is what
validates the list. Independent DB cross-check on `raw_messages.first_seen_at
LIKE '2026-09-25T12%'` (SGT, this run's bucket) reproduced the same counts and
the same sum. [Predicate corrected 2026-09-27: `first_seen_at` is SGT ISO, so
the working form is a SGT-date LIKE bucket, not a UTC `>=` bound; the original
UTC form returned 560 cumulative rows, not 186.] `max(posted_at)` per zero channel
confirms all seven are genuinely quiet, not broken: watchcapital
2026-09-24T05:50Z, kbluxury 2026-09-24T04:18Z, watchhunts 2026-09-24T07:39Z,
HengWatch 2026-09-24T09:13Z, watchplayboypteltd 2026-09-23T10:25Z, and the two
long-dead feeds sgwatchinsider (2026-01-01) and goldmanluxurysg (2025-08-10).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-26 (12:00 SGT run): group still unreachable — `hermes send
--list telegram` → "no targets found for platform 'telegram'. Configured:
(none)". Group send NOT attempted (eighth consecutive run); the single Telegram
call went to the DM and delivered on the first attempt. Pipeline healthy: exit
0 (stdout ended "✅ Pipeline complete."), 179 new messages across 14 channels,
composite `1.1283` (−0.45% 1d, −0.0051; 7d +5.17%, 30d +9.68%), 1 anomaly flag,
route drift and page contract both clean. Export: 2361 listings (1964 priced)
exported, 13205 dropped (12963 expired, 242 sold, 0 dead links). Sold tracer 242
(median 3d to sell); signals 2076 confirmed sales (median 5d), 1776 price cuts
(median −2.1%), inventory looks 174.6% deeper than it is. References: 279
published (140 full confidence), 169 too thin. 172 price outliers flagged (kept
in index). Brand baselines 268/290 units (100% of listings), 41/57 brands;
availability_score 46.
Asset refreshed (verified live at `https://0xsteamboat.zo.space/data/watch-index.json`,
HTTP 200, 423770 bytes, md5 `48f3cb1c013b3d86334e4d095e333b1b` matching local,
served composite `1.1283` / `-0.45`, meta.updated 2026-09-26T12:14:50+08:00).
Zero-new-message channels this run (8): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`,
`tagtimesingapore`, `watchhunts`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks. Per-channel new counts:
watchexchangesg 77, watchbooksg 62, pngwatchdealer 14, watchdistrictsg 13,
thefinesttime 11, kbluxury 2, and zeros for the eight above. Sum = 179, exactly
matching the scraper's reported total, which is what validates the list.
Independent DB cross-check on `raw_messages.first_seen_at LIKE '2026-09-26T12%'`
(SGT, this run's bucket) reproduced the same counts and the same sum.
[Predicate corrected 2026-09-27 — same defect as the 2026-09-25 entry above.]
`max(posted_at)` per zero channel confirms all eight are genuinely quiet, not
broken: ChuanwatchSG 2026-09-25T07:24Z, HengWatch 2026-09-25T09:33Z, watchhunts
2026-09-25T06:30Z, watchplayboypteltd 2026-09-25T05:32Z, watchcapital
2026-09-25T05:24Z, tagtimesingapore 2026-09-24T10:27Z, and the two long-dead
feeds sgwatchinsider (2026-01-01) and goldmanluxurysg (2025-08-10).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-27 (12:00 SGT run): group still unreachable, group send ATTEMPTED
this run (breaking with the last eight runs' practice, since the instruction says
to report to the group) — `send_telegram_message` to `-5370852148` → "No Telegram
binding found for recipient '-5370852148'. Connected accounts: steamboat0x0."
`hermes send --list telegram` → "no targets found for platform 'telegram'.
Configured: (none)" — ninth consecutive run, and now no Telegram targets at all,
not even the DM or `telegram:Collab`. So Hermes' Telegram config has been cleared,
not just the group. The failed group attempt did NOT consume the per-turn budget
this time: the DM fallback (`send_telegram_message`, no recipient) delivered on
the next call. Recommend reverting to the read-the-list-first pattern anyway.
Pipeline healthy: exit 0 (stdout ended "✅ Pipeline complete."; no step printed
"FAILED"), 159 new messages across 14 channels, composite `1.1060` (−0.90% 1d,
−0.0101; 7d +1.41%, 30d +7.33%), 1 anomaly flag, route drift and page contract
both clean. Export: 2355 listings (1981 priced) exported, 13412 dropped (13150
expired, 262 sold, 0 dead links). Sold tracer 262 (median 3d to sell). Signals:
2127 confirmed sales (median 5d), 1833 price cuts (median −2.11%), inventory looks
176.3% deeper than it is. References: 280 published (140 full confidence), 170 too
thin. 173 price outliers flagged (kept in index). Brand baselines 269/291 units,
41/57 brands; availability_score 39 (prior day 100, 30-day minimum 23 — a sharp
single-day drop but inside the range this series has already covered, so recorded
as a number to watch rather than classified as an anomaly). Asset refreshed (verified live
at `https://0xsteamboat.zo.space/data/watch-index.json`, HTTP 200, 423906 bytes,
md5 `1bfd0bf3afcc40a6069c7e9eb3e686d1` matching local, served composite `1.1060` /
`-0.9`, meta.updated 2026-09-27T12:15:06+08:00).
Zero-new-message channels this run (8): `ChuanwatchSG`, `goldmanluxurysg`,
`thefinesttime`, `watchplayboypteltd`, `sgwatchinsider`, `kbluxury`,
`tagtimesingapore`, `watchhunts`.

Note on the zero-new list: stdout was captured in full, so the list is read
straight off the scraper's printed per-channel blocks. Per-channel new counts:
watchexchangesg 74, watchbooksg 57, watchdistrictsg 9, pngwatchdealer 10,
HengWatch 6, watchcapital 3, and zeros for the eight above. Sum = 159, exactly
matching the scraper's reported total, which is what validates the list.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Sweep carried out this run: both earlier entries' DB cross-check predicates were
re-tested against `data/listings.db`. The counts they quote are right; the SQL was
not reproducible as written. Verified per-bucket reproduction: `2026-09-25T12%` →
186 (watchexchangesg 77, watchbooksg 65, pngwatchdealer 13, watchdistrictsg 13,
thefinesttime 10, ChuanwatchSG 7, tagtimesingapore 1); `2026-09-26T12%` → 179
(watchexchangesg 77, watchbooksg 62, pngwatchdealer 14, watchdistrictsg 13,
thefinesttime 11, kbluxury 2); `2026-09-27T12%` → 159 (watchexchangesg 74,
watchbooksg 57, pngwatchdealer 10, watchdistrictsg 9, HengWatch 6, watchcapital 3).
Correct form for future runs: `first_seen_at LIKE '<SGT date>T<HH>%'`. Do not carry
the UTC `>=` form forward.

Update 2026-09-27 (18:15 SGT run): group send ATTEMPTED again (per the
instruction naming the group) — `send_telegram_message` to `-5370852148` →
"No Telegram binding found for recipient '-5370852148'. Connected accounts:
steamboat0x0." (tenth consecutive run). `hermes send --list telegram` →
"no targets found for platform 'telegram'. Configured: (none)" — unchanged
from the 12:00 run; Hermes still has no Telegram targets. The failed group
attempt again did NOT consume the per-turn budget: the DM fallback
(`send_telegram_message`, no recipient) delivered on the next call.
Pipeline healthy: exit 0 ("✅ Pipeline complete."; no step printed "FAILED"),
179 new messages across 14 channels, composite `1.1093` (−0.48% 1d, −0.0054;
7d +1.44%, 30d +7.67%; pre-owned `1.0264`, NEW `1.2390`, spread `+0.2126`),
1 anomaly flag, route drift and page contract both clean.
Export: 2365 listings (1991 priced) exported, 13427 dropped (13148 expired,
279 sold, 0 dead links). Sold tracer 279 (median 3d to sell, p25 1d, p75 5d).
Signals: 2148 confirmed sales (median 5d), 1857 price cuts (median −2.15%),
inventory looks 177.3% deeper than it is. References: 285 published (140 full
confidence, 145 limited; 12 variant-grouped, 23 model-level) across 24 brands,
169 too thin; deepest Rolex 126334 n=409 fair $19,300–$21,700 (±6%).
173 price outliers flagged (kept in index). Unit baselines 269/291 units
(7177 listings, 100%), 41/57 brands; 14 outlier prices excluded from baselines.
Dedupe: 1175 reposts collapsed (30.8%), 12885 reposts collapsed (64.1%),
7208 unique watches.
Asset refreshed — `https://0xsteamboat.zo.space/data/watch-index.json`
verified live, HTTP 200, 423912 bytes, md5 `279c0fd87350ed8411a2ac55e965aeaa`
matching local; meta.updated 2026-09-27T18:15:43+08:00.
Zero-new-message channels this run (2): `goldmanluxurysg`, `sgwatchinsider`.
Per-channel new counts read straight off the scraper's printed blocks:
watchexchangesg 57, watchbooksg 111, watchdistrictsg 4, pngwatchdealer 2,
watchplayboypteltd 5, and zeros for the two above. Sum = 179, matching the
scraper's reported total, which validates the list.
Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run).

Update 2026-09-28 (12:15 SGT run): group still unreachable, group send ATTEMPTED
(per the instruction naming the group) — `send_telegram_message` to `-5370852148`
→ "No Telegram binding found for recipient '-5370852148'. Connected accounts:
steamboat0x0." (eleventh consecutive run). `hermes send --list telegram` →
"no targets found for platform 'telegram'. Configured: (none)" — unchanged;
Hermes still has no Telegram targets (its API server itself is healthy,
`health` → status ok, v0.21.5). The failed group attempt again did NOT consume
the per-turn budget: the DM fallback (`send_telegram_message`, no recipient)
delivered on the next call.
Pipeline healthy: exit 0 ("✅ Pipeline complete."; no step printed "FAILED"),
141 new messages across 14 channels, composite `1.1099` (−0.18% 1d, −0.0020;
pre-owned `1.0377`, NEW `1.2545`, spread `+0.2168`), **0 anomaly flags** (first
zero-flag run in recent memory — verified by hand rather than trusted: 0
unbranded listings, sold tracer 279, reference cards 293 with 0 wide-spread and
0 stale past 60 days, |1d move| well under the 8% alert threshold,
days_since_fresh=0, route drift and page contract both clean), route drift and
page contract both clean.
Export: 2297 listings (1973 priced) exported, 13601 dropped (13322 expired,
279 sold, 0 dead links). Sold tracer 279 (median 3d to sell, p25 1d, p75 5d;
279 by reply link, 0 by edit). Signals: 2166 confirmed sales (median 5d), 1866
price cuts (median −2.15%), inventory looks 178.6% deeper than it is.
References: 293 published (139 full confidence, 154 limited; 12 variant-grouped,
20 model-level) across 25 brands, 170 too thin, 23 groups too broad, 22 model
cards leftovers; deepest Rolex 126334 n=410 fair $19,300–$21,700 (±6%). 173
price outliers flagged (kept in index). Unit baselines 269/291 units (7183
listings, 100%), 41/57 brands; 14 outlier prices excluded from baselines.
Dedupe: 1157 reposts collapsed (31.0%), 12987 reposts collapsed (64.3%), 7214
unique watches. Anchor date 2026-04-02, 409 days tracked.
availability_score `33` — second consecutive sharp single-day drop (100 → 96 →
33; 30-day minimum 23), inside the range this series has covered, so recorded
as a number to watch rather than an anomaly.
Asset refreshed (verified live at `https://0xsteamboat.zo.space/data/watch-index.json`,
HTTP 200, 424926 bytes, md5 `74aaa8e34e91629cacfac03ca33e288f` matching local
byte-for-byte, served composite `1.1099` / `-0.18`, meta.updated
2026-09-28T12:12:55+08:00).
Zero-new-message channels this run (9): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`,
`kbluxury`, `tagtimesingapore`, `watchhunts`.

Note on the zero-new list: stdout was captured in full (not piped through
`tail`), so the list is read straight off the scraper's printed per-channel
blocks. Per-channel new counts: watchbooksg 75, watchexchangesg 54,
watchdistrictsg 5, pngwatchdealer 4, thefinesttime 3, and zeros for the nine
above. Sum = 141, exactly matching the scraper's reported total. Independent
`first_seen_at LIKE '2026-09-28T12%'` cross-check on `raw_messages` reproduced
the same five channels and the same 141 total.
`max(posted_at)` per zero channel confirms all nine are genuinely quiet, not
broken: watchplayboypteltd 2026-09-27T09:37Z, watchcapital 2026-09-26T10:33Z,
HengWatch 2026-09-26T12:50Z, watchhunts 2026-09-26T08:22Z, kbluxury
2026-09-26T04:02Z, ChuanwatchSG 2026-09-25T07:24Z, tagtimesingapore
2026-09-24T10:27Z, and the two long-dead feeds sgwatchinsider (2026-01-01) and
goldmanluxurysg (2025-08-10).
Also skipped as unusable this run: 1 untimestamped message each in
watchdistrictsg and watchbooksg (no `<time>` element on the public page).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Delivery note (2026-09-28 12:15 SGT run): the group attempt cost more than one
call this time. The group send failed ("No Telegram binding found"), then the DM
fallback was refused with "STOP: Do not call send_telegram_message again this
turn. You have already called it 3 times, which exceeds the per-turn limit of
3." So the report went out by EMAIL instead (same as 2026-09-15). The
read-`hermes send --list telegram`-first pattern from the 2026-09-15 entry
remains the correct one: when the list shows no Telegram targets for the group,
skip the group attempt entirely and spend the single call on the DM.

Reconciliation (2026-09-28 12:15 SGT run) — duplicate log entries, and the
second-writer question resolved.

This run wrote its log three times inside 24 seconds, which is why the file
carried two near-identical 2026-09-28 12:15 entries (`ef57788`, then `8378039`)
plus the delivery note (`26bfc3f`). The duplicate has been removed rather than
left in place as the 2026-09-17 pair was, since every fact in it was already
recorded above. Two details existed only in the removed copy and are preserved
here: the anchor-relative driver line ("moved down 0.2% today. led by Breitling,
Grand Seiko, Jaeger-LeCoultre. with Longines, Audemars Piguet, Zenith pulling
the other way.") and the 16 brands with no baseline (Arnold & Son, Konstantin
Chaykin, Chronoswiss, Graham, Louis Moinet, Louis Erard, Oris, Bulgari, Chanel,
Jacob & Co, Baltic, Baume & Mercier, Bedat, Jaquet Droz, Carl F. Bucherer,
Fears).

The 2026-09-19 provenance note flagged an unidentified process appending to this
file. That is now explained well enough to stop treating it as an intruder: all
three 2026-09-28 12:15 writers share one `send_telegram_message` per-turn budget.
A later context in this same run hit "You have already called it 3 times, which
exceeds the per-turn limit of 3" without having made any of those calls itself —
so the parallel writers are concurrent agent contexts of this same automation
run, not a separate writer with independent access. Two contexts racing on one
run is still a defect (it duplicated the log and split the delivery budget), and
the practical symptom to expect is a duplicate report or a truncated one.

Delivery for this run is CONFIRMED, by email, verified this turn in Gmail:
message id `1a0e639bddc83723`, snippet begins "Index: 1.1099 (−0.0020, −0.18% d/d
— from 1.1119) Pre-owned 1.0377 | NEW 1.2545 | spread +0.2168 ... Export:". So
the numbers reached the user; only the channel was wrong (email, not Telegram).
`hermes` itself is healthy (`health` → status ok, v0.21.5) while holding no
Telegram targets, so the missing piece remains bot group membership, unchanged
for eleven runs.

Update 2026-09-28 (18:00 SGT run): group still unreachable — and now Hermes holds
no Telegram targets at all (`hermes send --list telegram` → "no targets found for
platform 'telegram'. Configured: (none)"), a regression from the previous state
where it at least listed `telegram:0xsteamboat` and `telegram:Collab`. Group send
NOT attempted; per the 2026-09-15 pattern the single Telegram call went to the DM
and delivered on the first attempt (1 call this turn, under the per-turn limit of
3, so no repeat of the 2026-09-28 12:15 truncation).
Pipeline healthy: exit 0, 162 new messages across 14 channels, composite `1.1112`
(−0.12% 1d, −0.0013, from 1.1125), pre-owned `1.0387` / NEW `1.2545` / spread
`+0.2158`, anchor 2026-04-02, 409 days tracked, 41/58 brands baselined.
0 anomalies flagged (anomaly check clean on all six axes: listings 2324 with 0
unresolved brands, sold tracer 298 at median 3d, signals 2189 sales / 1873 price
cuts, references 295 published, index −0.12% with days_since_fresh=0, route drift
and page contract both clean).
Export: 2324 listings (1986 priced) exported, 13619 dropped (13321 expired, 298
sold, 0 dead links); 13066 reposts collapsed (64.3%), 7244 unique watches;
173 price outliers flagged and kept in the index; 14 outlier prices excluded from
baselines; 269 of 292 unit baselines covering 7212 listings (100%).
Asset refreshed (verified live at `https://0xsteamboat.zo.space/data/watch-index.json`,
HTTP 200, 424966 bytes, md5 `be6b23a17fada3548e02d020858ce95c` matching local
byte-for-byte, served composite `1.1112` / `-0.12`, meta.updated
2026-09-28T18:13:14+08:00).
Zero-new-message channels this run (5): `watchcapital`, `pngwatchdealer`,
`sgwatchinsider`, `HengWatch`, `goldmanluxurysg`.

Note on the zero-new list: stdout was piped through `tail -120`, so the list was
rebuilt from `raw_messages.first_seen_at >= '2026-09-28T18:09:49'` (SGT, matching
the run start recorded in `scraper_log.json`) and cross-checked against
`scraped_at` in the UTC window `2026-09-28 10:09:49`–`10:10:30`. Both agree.
Per-channel new counts: watchexchangesg 68, watchbooksg 65, thefinesttime 14,
ChuanwatchSG 6, watchhunts 4, watchdistrictsg 2, kbluxury 1, tagtimesingapore 1,
watchplayboypteltd 1 — sum 162, exactly matching the scraper's reported total,
which is what validates the method. The five zeros are genuine quiet, not broken:
`max(posted_at)` is pngwatchdealer 2026-09-27T17:58Z, watchcapital
2026-09-26T10:33Z, HengWatch 2026-09-26T12:50Z, and the two long-dead feeds
sgwatchinsider (2026-01-01) and goldmanluxurysg (2025-08-10).

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-29 (12:00 SGT run): unchanged. `hermes send --list telegram`
now returns `hermes send: no targets found for platform 'telegram'. Configured:
(none)` — the DM and the `telegram:Collab` group that were still listed on
2026-09-13 have gone too, so there is currently no Hermes Telegram route at all,
not just a missing group. Zo's own `send_telegram_message` has no group targeting
parameter (recipient selects a connected account, not a chat), so the group
remains out of reach. Report delivered to the user's DM.

Pipeline healthy: exit 0, `pipeline.py` end to end, 175 new messages across 14
channels, composite 1.0837 (−0.0325 / −2.91% 1d; prev closes 09-27 1.1316,
09-28 1.1162), 2,297 listings exported (1,985 priced), dropped 13,912 (13,630
expired / 282 sold / 0 dead links), 177 price outliers kept in index and listed
for review, anomaly check clean, route drift and page contract both clean.
Space asset `/data/watch-index.json` re-uploaded: HTTP 200, 426,333 bytes,
byte-count matches `data/index.json` on disk.

Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `kbluxury`, `tagtimesingapore`,
`watchhunts`.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run).

Update 2026-09-30 (12:00 SGT run): unchanged on delivery — the group
"(Project) Luxury Watch Index" (`-5370852148`) remains unreachable; Zo's
`send_telegram_message` has no group targeting parameter (recipient selects a
connected account, not a chat) and the 2026-09-29 check showed no Hermes
Telegram route at all. Report delivered to the user's DM.

Pipeline healthy: exit 0, `pipeline.py` end to end, 161 new messages across 14
channels, composite `1.0928` (`-0.0092` / `-0.83%` 1d; prev close 09-29
`1.1020`; 7d `-2.34%`, 30d `+4.13%`), pre-owned `1.0445` / NEW `1.2679` /
spread `+0.2234`, anchor 2026-04-02, 411 days tracked, 41/58 brands baselined.
0 anomalies flagged (clean on all six axes: listings 2,287 with 0 unresolved
brands, sold tracer 275 at median 3d, signals 2,229 sales / 1,892 price cuts,
references 302 published, index `-0.83%` with days_since_fresh=0, route drift
and page contract both clean).
Export: 2,287 listings (1,970 priced) exported, 14,146 dropped (13,871 expired,
275 sold, 0 dead links); 1,054 reposts collapsed in-run (29.1%); 13,305
collapsed / 7,316 unique watches in index; 177 price outliers flagged and kept;
14 outlier prices excluded from baselines; 271 of 294 unit baselines covering
7,284 listings (100%).
Asset refreshed (verified live at `https://0xsteamboat.zo.space/data/watch-index.json`,
HTTP 200, 427,320 bytes, md5 `1265d23add37b5087223a8120d516a7a` matching local
byte-for-byte, served composite `1.0928` / `-0.83`, meta.updated
2026-09-30T12:16:53+08:00).
Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`, `kbluxury`, `watchhunts`.

Note on the zero-new list: stdout was not truncated this run, so the list is
read directly from the scraper output and cross-checked two ways. Per-channel
new counts from `raw_messages.first_seen_at >= '2026-09-30T12:09:00'` (SGT):
watchexchangesg 64, watchbooksg 55, pngwatchdealer 18, thefinesttime 10,
tagtimesingapore 7, watchdistrictsg 4, ChuanwatchSG 3 — sum 161, exactly
matching the scraper's reported total. The seven zeros are genuine quiet:
`max(posted_at)` is goldmanluxurysg 2025-08-10, sgwatchinsider 2026-01-01 (both
long-dead feeds), watchcapital 2026-09-26, watchhunts 2026-09-28, HengWatch
2026-09-28, kbluxury 2026-09-29, watchplayboypteltd 2026-09-29.

Note: `schonwatch` still sits in `raw_messages` but is not in the scraper's
14-channel list — dormant historical data, not a silent scrape failure.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-30 (12:00 SGT run): unchanged. Group send to `-5370852148`
retried and failed identically — `ValueError: No Telegram binding found for
recipient '-5370852148'. Connected accounts: steamboat0x0.` Group delivery has
now failed on every run since 2026-08-10; the DM fallback works and was used.

Pipeline healthy: exit 0, `pipeline.py` end to end, 161 new messages across 14
channels, composite `1.0928` (−0.0092 / −0.83% 1d; prev closes 09-28 1.1366,
09-29 1.1020), 2,287 listings exported (1,970 priced), dropped 14,146 (13,871
expired / 275 sold / 0 dead links), 1,054 in-run reposts collapsed (29.1%),
7,316 unique watches remain, 177 price outliers flagged and kept in the index,
14 outlier prices excluded from baselines, 269 of 292 unit baselines covering
7,284 listings (100%). Reference set: 302 published (143 full confidence, 165
too thin). Anomaly check clean on all six axes (listings 2,287 with 0 unresolved
brands, sold tracer 275 at median 3d, signals 2,229 confirmed sales / 1,892 price
cuts, references 302, index −0.83% with days_since_fresh=0, route drift and page
contract both clean) — **0 lines under "Anomalies flagged for review"**.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200, 427,320
bytes, md5 `1265d23add37b5087223a8120d516a7a` matching `data/index.json`
byte-for-byte, served composite `1.0928` / `-0.83`, meta.updated
2026-09-30T12:16:53+08:00.

Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `HengWatch`, `kbluxury`, `watchhunts`.
stdout was captured in full (not piped through `tail`), so the seven zeros come
straight from the scraper's own per-channel output; cross-checked against
`raw_messages.first_seen_at >= '2026-09-30T12:09:00'`, where per-channel counts
sum to 161 — exactly the scraper's reported total. All seven are genuine quiet,
not broken: `max(posted_at)` is watchcapital 2026-09-26T10:33Z, watchhunts
2026-09-28T09:16Z, HengWatch 2026-09-28T17:26Z, kbluxury 2026-09-29T04:11Z,
watchplayboypteltd 2026-09-29T06:27Z, and the two long-dead feeds sgwatchinsider
(2026-01-01) and goldmanluxurysg (2025-08-10).
The scrape covers 14 channels; `schonwatch` remains in `raw_messages` from
historical runs but is no longer in the channel list, so it is not a quiet
channel — it is retired.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-09-30 (18:00 SGT run): pipeline.py end to end, exit 0. 86 new
messages across 14 channels (1 skipped, no timestamp). Composite `1.0936`
(`-0.0069` / `-0.63%` 1d; prev close 09-30 12:00 `1.1005`; 7d `-1.61%`, 30d
`+4.20%`), pre-owned `1.0482` / NEW `1.2676` / spread `+0.2194`, anchor
2026-04-02, 411 days tracked, 41/58 brands baselined.
Export: 2,305 listings (1,977 priced) exported, 14,157 dropped (13,867 expired,
290 sold, 0 dead links); 1,084 reposts collapsed in-run (29.5%); 13,339
collapsed / 7,333 unique watches in index; 177 price outliers flagged and kept;
14 outlier prices excluded from baselines; 271 of 294 unit baselines covering
7,301 listings (100%). Link check: 300/2,305 verified.
Signals: 2,246 confirmed sales (median 5d), 1,893 price cuts (median -2.16%),
inventory looks 180.4% deeper than it is. References: 302 published (144 full
confidence), 166 too thin.
2 anomalies flagged this run (first non-clean run since 09-29): (1) 1 listing
with no resolved brand — Credor GCCD993, parser/brands.py coverage gap;
(2) 1 reference card with >60% asking spread, rolex-126515ln at 63.3%,
suggesting one reference number covers several distinct watches.
Route drift and page contract both clean. days_since_fresh=0.
Space asset `/data/watch-index.json` re-uploaded: HTTP 200, 427,291 bytes,
md5 `6aa84eeae56ad7ad2c95dfac6b046c64`, byte-identical to `data/index.json`
on disk.
Zero-new-message channels this run (4): `watchcapital`, `goldmanluxurysg`,
`sgwatchinsider`, `tagtimesingapore`.
Delivery: group still unreachable; report delivered to user DM.

Update 2026-10-01 (12:00 SGT run): pipeline.py end to end, exit 0. 294 new
messages across 14 channels. Composite `1.0945` (`+0.0177` / `+1.64%` 1d;
7d `-1.60%`, 30d `+3.74%`), pre-owned `1.0464` / NEW `1.2918` / spread
`+0.2454`, anchor 2026-04-02, 412 days tracked, 41/58 brands baselined.

Day-over-day caveat: this run restated the 2026-09-30 series value to `1.0768`
from the `1.0936` the 09-30 18:00 run reported for that same date. The printed
`+1.64%` is therefore measured against the restated prior close; against the
last *reported* close the move is `+0.0009` (`+0.08%`). The restatement is
`-0.0168` on a settled date, larger than the usual rolling-window revision —
worth watching, because it means a reported 1d move can be an artifact of the
prior close being rewritten rather than a genuine move.

Export: 2,303 listings (2,000 priced) exported, 14,326 dropped (14,047 expired,
279 sold, 0 dead links); 1,136 reposts collapsed in-run (30.6%); 7,369 unique
watches remain (13,555 collapsed); 178 price outliers flagged and kept; 15
outlier prices excluded from baselines; 271 of 294 unit baselines covering
7,337 listings (100%). Link check: 300/2,303 verified.

Signals: 2,261 confirmed sales (median 5d), 1,947 price cuts (median -2.22%),
inventory looks 182.4% deeper than it is. References: 302 published (147 full
confidence, 155 limited; 166 too thin, 24 too broad, 22 model-card leftovers),
deepest Rolex 126334 n=429 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved brand —
Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap; (2) 2 reference
cards with >60% asking spread, widest rolex-124300 at 87.0%.
Route drift and page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
428,473 bytes, md5 `2e25c6563375129065dae711419aa618`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.0945` / `+1.64`.

Zero-new-message channels this run (6): `watchcapital`, `goldmanluxurysg`,
`sgwatchinsider`, `HengWatch`, `tagtimesingapore`, `watchhunts`. stdout was
captured in full (not piped through `tail`), so the zeros come straight from
the scraper's own per-channel output; the 14 printed counts
(6+5+183+17+75+0+0+4+2+0+0+2+0+0) sum to 294, exactly the scraper's reported
total, which is what validates the list. The two dead feeds (`goldmanluxurysg`
since 2025-08-10, `sgwatchinsider` since 2026-01-01) are quiet by definition;
the other four are recent-but-quiet, not broken.

Delivery: group `-5370852148` still unreachable and the group send was NOT
attempted this run. `hermes send --list telegram` now returns
"no targets found for platform 'telegram'. Configured: (none)" — Hermes'
Telegram scope has gone from "group only" to nothing at all since the
2026-09-13 note. The single `send_telegram_message` call went to the DM and
delivered on the first attempt, avoiding the per-turn limit. This remains the
pattern to use. To restore group delivery: add Zo's bot `@steamboat0x0` to
group `-5370852148` as admin and change the automation's delivery target.

Note: `web/routes/api-watch-listings.ts` and `web/routes/api-watch-references.ts`
still carry the same uncommitted local modifications as previously logged
(pre-existing, not from this run). The pipeline's route-drift check reports the
deployed route matching the repo.

Update 2026-10-01 (18:00 SGT run): pipeline.py end to end, exit 0. 177 new
messages across 14 channels. Composite `1.0934` (`+0.0102` / `+0.94%` 1d;
7d `-1.12%`, 30d `+3.28%`, 90d `-3.01%`), pre-owned `1.0479` / NEW `1.2977` /
spread `+0.2498`, anchor 2026-04-02, 412 days tracked, 41/58 brands baselined.

Day-over-day caveat: the 2026-09-30 close was restated a second time, to
`1.0832` (printed as `1.0768` by the 12:00 run today, and as `1.0936` by the
09-30 18:00 run before that). Today's own value was also marked down from the
12:00 print of `1.0945` to `1.0934`. So the printed `+0.94%` is measured
against a restated prior close; against the last *reported* close the move is
`-0.0011` (`-0.10%`). Two consecutive runs have now rewritten a settled date by
more than the usual rolling-window revision, which confirms the standing
warning: a reported 1d move can be an artifact of the prior close being
rewritten rather than a genuine move. Root cause still unidentified — the
rolling 21-day window plus late listprice edits are the suspects.

Export: 2,350 listings (2,015 priced) exported, 14,318 dropped (14,019 expired,
299 sold, 0 dead links); 1,216 reposts collapsed in-run (31.5%); 7,398 unique
watches remain (13,641 collapsed); 178 price outliers flagged and kept; 15
outlier prices excluded from baselines; 273 of 296 unit baselines covering
7,366 listings (100%). Link check: 300/2,350 verified.

Signals: 2,284 confirmed sales (median 5d), 1,959 price cuts (median -2.20%),
inventory looks 182.9% deeper than it is. References: 305 published (147 full
confidence, 158 limited; 166 too thin, 23 too broad, 23 model-card leftovers),
deepest Rolex 126334 n=432 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved brand —
Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap; (2) 2 reference
cards with >60% asking spread, widest rolex-124300 at 87.0%. Route drift and
page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
428,458 bytes, md5 `d2d18c3a9c11cffd79a8d1e2fdb45279`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.0934` / `+0.94`.

Zero-new-message channels this run (4): `goldmanluxurysg`, `sgwatchinsider`,
`HengWatch`, `watchhunts`. Per-channel counts
(5+2+103+1+29+2+0+31+1+0+0+1+2+0) sum to 177, exactly the scraper's reported
total, which is what validates the list. The two dead feeds
(`goldmanluxurysg` since 2025-08-10, `sgwatchinsider` since 2026-01-01) are
quiet by definition; `HengWatch` and `watchhunts` are recent-but-quiet.
Note `watchcapital` and `tagtimesingapore` printed 2 new messages each this run
after being zero-new at 12:00, so that pair is flapping rather than dead.

Delivery: group `-5370852148` still unreachable. `send_telegram_message` to the
group was re-attempted once this run and failed with "No Telegram binding found
for recipient '-5370852148'. Connected accounts: steamboat0x0." `hermes send
--list telegram` still returns "no targets found for platform 'telegram'.
Configured: (none)". The report went to the DM on the first attempt. Remaining
pattern: attempt the group once, fall back to DM, do not retry the group. To
restore group delivery: add Zo's bot `@steamboat0x0` to group `-5370852148` as
admin and change the automation's delivery target.

Update 2026-10-02 (12:00 SGT run): pipeline.py end to end, exit 0. 165 new
messages across 14 channels. Composite `1.0951` (`-0.0060` / `-0.54%` 1d;
7d `-2.48%`, 30d `+6.10%`, 90d `-4.74%`), pre-owned `1.0466` / NEW `1.2516` /
spread `+0.2050`, anchor 2026-04-02, 413 days tracked, 41/58 brands baselined.

Day-over-day caveat (third consecutive occurrence): the 2026-10-01 close was
restated from the `1.0934` reported at 18:00 to `1.1011` (+0.0077), and the
2026-09-30 close moved once more from `1.0832` to `1.0873`. Today's own value
is therefore measured against a restated prior close; against the last
*reported* close the move is `+0.0017` (`+0.16%`), not `-0.54%`. Every settled
date is still being rewritten by more than rolling-window noise. Root cause
still unidentified — 21-day rolling window plus late listprice edits remain
the suspects. Treat the printed 1d figure as unreliable until fixed.

Export: 2,338 listings (2,017 priced) exported, 14,491 dropped (14,210 expired,
281 sold, 0 dead links); 1,096 reposts collapsed in-run (29.5%); 7,422 unique
watches remain (13,741 collapsed); 181 price outliers flagged and kept; 15
outlier prices excluded from baselines; 273 of 296 unit baselines covering
7,390 listings (100%). Link check: 300/2,338 verified.

Signals: 2,296 confirmed sales (median 5d), 1,967 price cuts (median -2.21%),
inventory looks 183.6% deeper than it is. References: 306 published (146 full
confidence, 160 limited; 167 too thin, 24 too broad, 24 model-card leftovers),
deepest Rolex 126334 n=435 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved brand —
Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap; (2) 2 reference
cards with >60% asking spread, widest rolex-124300 at 87.0%. Route drift and
page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
429,759 bytes, md5 `0f3fc8596d09dd8cf48b0d9568426470`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.0951` / `-0.54`.

Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `kbluxury`, `tagtimesingapore`,
`watchhunts`. Per-channel counts (19+4+53+14+59+0+0+13+0+0+3+0+0+0) sum to
165, exactly the scraper's reported total, which is what validates the list.
`watchcapital` and `tagtimesingapore` are back to zero after printing 2 new
messages each on 10-01 18:00 — the flapping pair, not dead.

Delivery: group `-5370852148` still unreachable. The report went to the DM
first this run, then the group send was attempted once and failed with "No
Telegram binding found for recipient '-5370852148'. Connected accounts:
steamboat0x0." `hermes send --list telegram` still returns "no targets found
for platform 'telegram'. Configured: (none)". Pattern held: group unreachable,
DM carried the report, group not retried. To restore group delivery: add Zo's
bot `@steamboat0x0` to group `-5370852148` as admin and change the
automation's delivery target.

Update 2026-10-02 (12:00 SGT run): pipeline.py end to end, exit 0. 165 new
messages across 14 channels. Composite `1.0951` (`-0.0060` / `-0.54%` 1d;
7d `-2.48%`, 30d `+6.10%`, 90d `-4.74%`), pre-owned `1.0466` / NEW `1.2516` /
spread `+0.2050`, anchor 2026-04-02, 413 days tracked, 41/58 brands baselined.

Day-over-day restatement — third consecutive run, now larger. The 2026-10-01
close, reported as `1.0934` eighteen hours ago, is stored as `1.1011` today
(`+0.0070`, `+0.77%` of the prior close). The 2026-09-30 close was restated
again too, `1.0832` → `1.0873`. Against the last *reported* close today's move
is `+0.0017` (`+0.16%`), against the stored close it is `-0.54%`. So the
printed 1d figure is now an artifact of the rewrite, not a market move —
published in the report with that caveat attached. This is the same defect
flagged on 09-30 and 10-01; it is escalating, not noise. Suspects unchanged
(21-day rolling window + late listprice edits rewriting the stored series).
Worth a dedicated fix: either freeze closes once published, or recompute the
prior close from a snapshot rather than from live data.

Export: 2,338 listings (2,017 priced) exported, 14,491 dropped (14,210 expired,
281 sold, 0 dead links); 1,096 reposts collapsed in-run (29.5%); 7,422 unique
watches remain (13,741 collapsed); 181 price outliers flagged and kept; 15
outlier prices excluded from baselines; 273 of 296 unit baselines covering
7,390 listings (100%). Link check: 300/2,338 verified.

Signals: 2,296 confirmed sales (median 5d), 1,967 price cuts (median -2.21%),
inventory looks 183.6% deeper than it is. References: 306 published (146 full
confidence, 160 limited; 167 too thin, 24 too broad, 24 model-card leftovers),
deepest Rolex 126334 n=435 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved brand —
Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap (same class as the
10-01 run); (2) 2 reference cards with >60% asking spread, widest rolex-124300
at 87.0%. Route drift and page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
429,759 bytes, md5 `0f3fc8596d09dd8cf48b0d9568426470`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.0951` / `-0.54`.

Zero-new-message channels this run (7): `watchcapital`, `goldmanluxurysg`,
`watchplayboypteltd`, `sgwatchinsider`, `kbluxury`, `tagtimesingapore`,
`watchhunts`. Per-channel counts (19+4+53+14+59+0+0+13+0+0+3+0+0+0) sum to
165, exactly the scraper's reported total, which is what validates the list.
`watchcapital` and `tagtimesingapore` were both zero-new here after printing 2
new messages at the previous run — consistent with the flapping pair flagged on
10-01, not a new dead feed. `goldmanluxurysg` and `sgwatchinsider` remain dead
by definition (last post 2025-08-10 and 2026-01-01 respectively).

Delivery: group `-5370852148` still unreachable. `send_telegram_message` to the
group was attempted once this run and failed with "No Telegram binding found for
recipient '-5370852148'. Connected accounts: steamboat0x0." The DM fallback then
hit the per-turn limit on `send_telegram_message` before it could send, so the
report went out by email instead — the second time this has happened (see
2026-09-13 18:00). Fix for the flapping delivery: stop attempting the group
send first, since it has failed on every run since 2026-08-10; spend the first
call on the DM. To restore true group delivery, add Zo's bot `@steamboat0x0` to
group `-5370852148` as admin, or repoint the automation's delivery target.

Update 2026-10-02 (18:00 SGT run): pipeline.py end to end, exit 0. 133 new
messages across 14 channels. Composite `1.0949` (`-0.0041` / `-0.37%` 1d;
7d `-2.85%`, 30d `+6.15%`, 90d `-4.70%`), pre-owned `1.0504` / NEW `1.2259` /
spread `+0.1755`, anchor 2026-04-02, 413 days tracked, 41/58 brands baselined.

Day-over-day restatement — fourth consecutive run. The 2026-10-01 close,
reported as `1.0951` six hours ago at 12:00, is stored as `1.0990` today
(`+0.0039`, `+0.36%` of the prior close). Against the last *reported* close
today's move is `-0.0002` (`-0.02%`), against the stored close it is `-0.37%`.
Same defect as 09-30, 10-01 and today's 12:00 run; still not fixed. Suspects
unchanged (21-day rolling window + late listprice edits rewriting the stored
series). Fix options recorded already: freeze closes once published, or
recompute the prior close from a snapshot rather than from live data.

Export: 2,351 listings (2,019 priced) exported, 14,495 dropped (14,193 expired,
302 sold, 0 dead links); 1,152 reposts collapsed in-run (30.3%); 7,445 unique
watches remain (13,797 collapsed); 181 price outliers flagged and kept; 15
outlier prices excluded from baselines; 273 of 296 unit baselines covering
7,413 listings (100%). Link check: 300/2,351 verified.

Signals: 2,324 confirmed sales (median 5d), 1,971 price cuts (median -2.21%),
inventory looks 183.8% deeper than it is. References: 306 published (146 full
confidence, 160 limited; 167 too thin, 24 too broad, 24 model-card leftovers),
deepest Rolex 126334 n=438 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved brand —
Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap (same class as
10-01 and today's 12:00 run); (2) 2 reference cards with >60% asking spread,
widest rolex-124300 at 87.0%. Route drift and page contract both clean.
days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
429,686 bytes, md5 `0b9b7757c8a353851a13426db8c5705f`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.0949` / `-0.37`.

Zero-new-message channels this run (5): `watchcapital`, `goldmanluxurysg`,
`sgwatchinsider`, `HengWatch`, `kbluxury`. Per-channel counts
(6+4+63+3+39+0+0+9+3+0+0+0+2+4) sum to 133, exactly the scraper's reported
total, which is what validates the list. `watchcapital` returned to zero after
printing 2 at 12:00 — the flapping feed flagged on 10-01, not dead.
`goldmanluxurysg` (last post 2025-08-10) and `sgwatchinsider` (2026-01-01)
remain dead by definition. `watchhunts` (4) and `tagtimesingapore` (2) both
printed new messages this run after zeroing at 12:00.

Delivery: group `-5370852148` still unreachable — no group send attempted this
run, per the standing note (it has failed on every run since 2026-08-10 and
burning the first call on it caused the DM to hit the per-turn limit on 10-02
12:00). The DM carried the report on the first call and succeeded. `hermes send
--list telegram` still returns no targets. To restore true group delivery: add
Zo's bot `@steamboat0x0` to group `-5370852148` as admin, or repoint the
automation's delivery target.

Update 2026-10-03 (18:00 SGT run): pipeline.py end to end, exit 0, all seven
steps green. 153 new messages across 14 channels. Composite `1.1017`
(`+0.0012` / `+0.11%` 1d; 7d `-1.65%`, 30d `+5.47%`, 90d `-1.86%`),
pre-owned `1.0370` / NEW `1.2496` / spread `+0.2126`, anchor 2026-04-02,
414 days tracked, 41/58 brands baselined. Driver line: up led by TAG Heuer,
Zenith, Audemars Piguet, with Cartier, Franck Muller, Omega pulling the other
way.

Day-over-day restatement — fifth consecutive run. The 2026-10-02 close,
reported as `1.0949` six hours ago at 18:00, is stored as `1.1005` today
(`+0.0056`, `+0.51%` of the prior close). Against the last *reported* close
today's move is `+0.0068` (`+0.62%`), against the stored close it is `+0.11%`.
Same defect as 09-30 through 10-02; still not fixed. Suspects unchanged
(21-day rolling window + late listprice edits rewriting the stored series).
Fix options recorded already: freeze closes once published, or recompute the
prior close from a snapshot rather than from live data.

Export: 2,354 listings (2,007 priced) exported, 14,715 dropped (14,429 expired,
286 sold, 0 dead links); 1,086 reposts collapsed in-run (29.1%); 7,499 unique
watches remain (13,940 collapsed); 183 price outliers flagged and kept; 15
outlier prices excluded from baselines; 273 of 296 unit baselines covering
7,467 listings (100%). Link check: 300/2,354 verified. Sold tracer: 286 marked
sold, all 286 by reply link, 0 by edit, median 3d to sell.

Signals: 2,367 confirmed sales (median 5d), 1,977 price cuts (median -2.22%),
inventory looks 184.4% deeper than it is. References: 310 published (147 full
confidence, 163 limited; 167 too thin, 23 too broad, 25 model-card leftovers),
deepest Rolex 126334 n=439 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved brand —
Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap (same class as
10-01, 10-02); (2) 1 reference card with >60% asking spread, widest
rolex-124300 at 80.7% (down from 2 cards / 87.0% at 10-02 18:00). Route drift
and page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
430,900 bytes, md5 `71e2e7b99e44078d45ea5f84549d227d`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.1017` / `+0.11`.

Zero-new-message channels this run (9): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`,
`kbluxury`, `tagtimesingapore`, `watchhunts`. Per-channel counts
(11+0+56+3+58+0+0+25+0+0+0+0+0+0) sum to 153, exactly the scraper's reported
total, which validates the list. Cross-checked two ways: `scraped_at` within
the run window 10:09:36-10:09:55 UTC (scraped_at is UTC and stored as
`YYYY-MM-DD HH:MM:SS`, not ISO-T), and `scraper_log.json` `last_scrape` (which
only advances when a channel inserts something). Both agree on the same nine.
Nine quiet channels is the highest of any run to date — no single cause
identified; the five that did print (watchbooksg 58, watchexchangesg 56,
thefinesttime 25, watchdistrictsg 11, pngwatchdealer 3) carried all 153.
`goldmanluxurysg` (last post 2025-08-10) and `sgwatchinsider` (2026-01-01)
remain dead by definition; `schonwatch` is no longer in CHANNELS at all.

Delivery: group `-5370852148` still unreachable — no group send attempted this
run, per the standing note. `hermes send --list telegram` returns "no targets
found for platform 'telegram'" (Hermes has no Telegram configuration at all,
consistent with the 09-13 finding that its token is dead). The DM carried the
report on the first call and succeeded. To restore true group delivery: add
Zo's bot `@steamboat0x0` to group `-5370852148` as admin, or repoint the
automation's delivery target.

Update 2026-10-04 (12:00 SGT run): pipeline.py end to end, exit 0, all seven
steps green. 173 new messages across 14 channels. Composite `1.1055`
(`+0.0213` / `+1.96%` 1d; 7d `-4.27%`, 30d `+5.78%`, 90d `0.00%`),
pre-owned `1.0353` / NEW `1.2644` / spread `+0.2291`, anchor 2026-04-02,
415 days tracked, 41/58 brands baselined. Driver line: up led by IWC,
Audemars Piguet, Chopard, with Bell & Ross, Vacheron Constantin, Patek
Philippe pulling the other way.

Day-over-day restatement — sixth consecutive run, and the largest yet. The
2026-10-03 close, reported as `1.1017` at 18:00 yesterday, is stored as
`1.0842` today (`-0.0175`, `-1.59%` of the prior close). Against the last
*reported* close today's move is `+0.0038` (`+0.35%`), against the stored
close it is `+1.96%`. Same defect as 09-30 through 10-03; still not fixed.
Suspects unchanged (21-day rolling window + late listprice edits rewriting
the stored series). Fix options recorded already: freeze closes once
published, or recompute the prior close from a snapshot rather than from
live data. The widening magnitude (0.36% → 0.51% → 1.59% of prior close)
argues for treating this as degrading, not stable.

Export: 2,321 listings (1,999 priced) exported, 14,819 dropped (14,527
expired, 292 sold, 0 dead links); 1,058 reposts collapsed in-run (28.8%);
7,524 unique watches remain (14,043 collapsed); 181 price outliers flagged
and kept; 13 outlier prices excluded from baselines; 273 of 296 unit
baselines covering 7,492 listings (100%). Link check: 300/2,321 verified.
Sold tracer: 292 marked sold, all 292 by reply link, 0 by edit, median 3d
to sell.

Signals: 2,395 confirmed sales (median 5d), 1,980 price cuts (median
-2.21%), inventory looks 185.1% deeper than it is. References: 310
published (146 full confidence, 164 limited; 168 too thin, 25 too broad,
23 model-card leftovers), deepest Rolex 126334 n=442 fair $19,300-$21,700
(+-6%).

2 anomalies flagged this run: (1) 1 published listing with no resolved
brand — Credor "Ice at Dawn" GCCD993, parser/brands.py coverage gap (same
class as 10-01 through 10-03); (2) 1 reference card with >60% asking
spread, widest rolex-124300 at 80.7% (unchanged from 10-03). Route drift
and page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
431,767 bytes, md5 `58545b0ba50d69a7523c8f00cf22c4f7`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.1055` / `+1.96`.

Zero-new-message channels this run (8): `ChuanwatchSG`, `watchcapital`,
`goldmanluxurysg`, `watchplayboypteltd`, `sgwatchinsider`, `kbluxury`,
`tagtimesingapore`, `watchhunts`. Per-channel counts
(14+0+69+13+70+0+0+3+0+0+4+0+0+0) sum to 173, exactly the scraper's
reported total, which validates the list. `goldmanluxurysg` (last post
2025-08-10) and `sgwatchinsider` (2026-01-01) remain dead by definition;
`HengWatch` (4) returned to printing after zeroing at 10-03 18:00, and
`ChuanwatchSG` printed 0 again after 11 at 10-03 18:00 — flapping, not
dead. `schonwatch` still absent from CHANNELS.

Delivery: group send WAS re-attempted this run (the automation instruction
still names the group explicitly). `send_telegram_message` to
`-5370852148` → "No Telegram binding found for recipient '-5370852148'.
Connected accounts: steamboat0x0." — failed as on every run since
2026-08-10. `hermes send --list telegram` returns "no targets found for
platform 'telegram'". The DM fallback then carried the report on the second
call and succeeded, so the per-turn limit was not hit with two calls. To
restore true group delivery: add Zo's bot `@steamboat0x0` to group
`-5370852148` as admin, or repoint the automation's delivery target.

Update 2026-10-04 (18:00 SGT run): pipeline.py end to end, exit 0, all seven
steps green. 228 new messages across 14 channels. Composite `1.1074`
(`+0.0124` / `+1.13%` 1d; 7d `-3.71%`, 30d `+5.99%`, 90d `+0.17%`),
pre-owned `1.0345` / NEW `1.2599` / spread `+0.2254`, anchor 2026-04-02,
415 days tracked, 41/58 brands baselined. Driver line: up led by IWC,
Audemars Piguet, Chopard, with TAG Heuer, Omega, Breitling pulling the
other way.

Day-over-day restatement — seventh consecutive run, and now twice in a
single day. The 2026-10-03 close, reported as `1.1017` at 18:00 yesterday,
was stored as `1.0842` at 12:00 today and is stored as `1.0950` now
(`1.1017 → 1.0842 → 1.0950`). Against the last *reported* close (`1.1055`
at 12:00 today) today's move is `+0.0019` (`+0.17%`); against the stored
close it is `+1.13%`. Same defect as 09-30 through 10-04 12:00; still not
fixed. Suspects unchanged (21-day rolling window + late listprice edits
rewriting the stored series). The 10-03 close has now moved 6.7bp twice in
24h — the series is being rewritten in place faster than the restatement
itself can be reported, which strengthens the case for freezing closes once
published over recomputing the prior close from live data. Observed
restatement magnitudes across the run: 0.36% → 0.51% → 1.59% → 0.61% of the
prior reported close.

Export: 2,349 listings (2,027 priced) exported, 14,838 dropped (14,524
expired, 314 sold, 0 dead links); 1,176 reposts collapsed in-run (30.6%);
7,564 unique watches remain (14,170 cumulative collapsed); 181 price
outliers flagged and kept; 13 outlier prices excluded from baselines; 274
of 297 unit baselines covering 7,532 listings (100%). Link check: 300/2,349
verified (capped). Sold tracer: 314 marked sold, all 314 by reply link, 0
by edit, median 3d to sell.

Signals: 2,432 confirmed sales (median 5d), 1,992 price cuts (median
-2.21%), inventory looks 185.8% deeper than it is. References: 312
published (146 full confidence, 166 limited; 169 too thin, 26 too broad,
23 model-card leftovers), deepest Rolex 126334 n=445 fair $19,300-$21,700
(+-6%).

2 anomalies flagged this run: (1) 2 published listings with no resolved
brand — a parser/brands.py coverage gap, example text is a Carousell Kermit
post now surfacing through the dealer channels; (2) 1 reference card with
>60% asking spread, widest rolex-124300 at 80.7% (unchanged from 10-03).
Route drift and page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
431,739 bytes, md5 `bec2f5856daa531a969c4d6f90780854`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.1074` / `+1.13`.

Zero-new-message channels this run (8): `ChuanwatchSG`, `HengWatch`,
`goldmanluxurysg`, `sgwatchinsider`, `tagtimesingapore`, `thefinesttime`,
`watchhunts`, `kbluxury`. Per-channel counts
(103+80+32+0+0+10+0+1+2+0+0+0+0+0) sum to 228, exactly the scraper's
reported total, which validates the list. `goldmanluxurysg` (last post
2025-08-10) and `sgwatchinsider` (2026-01-01) remain dead by definition;
`HengWatch` (last post 10-03 12:34) and `thefinesttime` (10-03 10:56)
zeroed after printing at 12:00 today — flapping, not dead. `schonwatch`
still absent from CHANNELS.

Delivery: group send was NOT attempted. `hermes send --list telegram`
returned "no targets found for platform 'telegram'" (Hermes' Telegram
credentials still rejected/cleared), so group `-5370852148` remains absent
from every bot's scope and the single Telegram call went to the user's DM,
where it succeeded. To restore true group delivery: add Zo's bot
`@steamboat0x0` to group `-5370852148` as admin, or repoint the automation's
delivery target.

Update 2026-10-05 (12:00 SGT run): Pipeline healthy — exit 0, `pipeline.py` end
to end, 192 new messages across 14 channels, composite `1.1169` (`+0.0071` /
`+0.64%` 1d; prev stored close 10-04 `1.1098`; 7d `-1.58%`, 30d `+7.53%`,
90d `-0.13%`), pre-owned `1.0301` / NEW `1.2348` / spread `+0.2047`, anchor
2026-04-02, 416 days tracked, 41/58 brands baselined. Driver line: up led by
Audemars Piguet, Panerai, Rolex, with Jaeger-LeCoultre, Bvlgari, Patek
Philippe pulling the other way.

Restatement again — eighth consecutive run. The 10-04 close, reported as
`1.1074` at 18:00 yesterday, is stored as `1.1098` now (+0.22% against the
reported figure); the 10-03 close has moved once more
(`1.1017 → 1.0842 → 1.0950 → 1.0992`), so that date has now been rewritten
three times in ~48h. Same defect as 09-30 onward; suspects unchanged (21-day
rolling window + late listprice edits rewriting the stored series). Because
the prior close keeps drifting, the `+0.64%` day-over-day figure is a
stored-vs-stored comparison, not a comparison against what was reported at
18:00 yesterday.

Export: 2,343 listings (2,028 priced) exported, 14,926 dropped (14,629
expired, 297 sold, 0 dead links); 1,158 reposts collapsed in-run (30.5%);
7,584 unique watches remain (14,311 cumulative collapsed); 180 price
outliers flagged and kept; 13 outlier prices excluded from baselines; 275 of
298 unit baselines covering 7,552 listings (100%). Link check: 300/2,343
verified (capped). Sold tracer: 297 marked sold, all 297 by reply link, 0 by
edit, median 3d to sell.

Signals: 2,447 confirmed sales (median 5d), 2,014 price cuts (median
-2.22%), inventory looks 187.1% deeper than it is. Availability score
23/100. References: 313 published (148 full confidence, 165 limited; 11
variant-grouped, 18 model-level; 169 too thin, 26 too broad, 23 model-card
leftovers), deepest Rolex 126334 n=448 fair $19,300-$21,700 (+-6%).

2 anomalies flagged this run: (1) 2 published listings with no resolved
brand — parser/brands.py coverage gap, example text is the Carousell Kermit
post still surfacing through the dealer channels; (2) 1 reference card with
>60% asking spread, widest rolex-124300 at 80.7% (unchanged from 10-03 and
10-04). Route drift and page contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
432,527 bytes, md5 `77f4b3f53ed3926e4c3ae40f81d33ca4`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.1169` / `+0.0071`,
meta.updated 2026-10-05T12:15:30+08:00.

Zero-new-message channels this run (9): `ChuanwatchSG`, `goldmanluxurysg`,
`thefinesttime`, `watchplayboypteltd`, `sgwatchinsider`, `HengWatch`,
`kbluxury`, `tagtimesingapore`, `watchhunts`. Per-channel counts
(15+0+70+5+101+1+0+0+0+0+0+0+0+0) sum to 192, exactly the scraper's reported
total, which validates the list. `goldmanluxurysg` (last post 2025-08-10) and
`sgwatchinsider` (2026-01-01) remain dead by definition; `HengWatch` and
`thefinesttime` zeroed after printing at 18:00 yesterday — flapping, not dead.
`watchbooksg` skipped 1 message with no timestamp (reported, not counted as a
new message). `schonwatch` still absent from CHANNELS.

Delivery: group send was NOT attempted — `hermes send --list telegram` still
returns "no targets found for platform 'telegram'", so group `-5370852148`
remains outside every bot's scope. The single Telegram call went to the
user's DM, where it succeeded. To restore true group delivery: add Zo's bot
`@steamboat0x0` to group `-5370852148` as admin, or repoint the automation's
delivery target.

Update 2026-10-05 (18:00 SGT run): Pipeline healthy — exit 0, `pipeline.py`
end to end. 144 new messages across 14 channels (it was 192 at 12:00 today).
Composite `1.1180` (`+0.0092` / `+0.83%` 1d; prev stored close 10-04 `1.1088`;
7d `-3.19%`, 30d `+7.90%`, 90d `-0.03%`), pre-owned `1.0299` / NEW `1.2356` /
spread `+0.2057`, anchor 2026-04-02, 416 days tracked, 42/58 brands
baselined. Driver line: up led by Omega, Cartier, Panerai, with Bvlgari,
Jaeger-LeCoultre, Patek Philippe pulling the other way.

Restatement again — ninth consecutive run. The 10-04 close, reported as
`1.1074` at 18:00 yesterday and stored as `1.1098` at 12:00 today, is stored
as `1.1088` now. So the reported `+0.83%` is a stored-vs-stored comparison;
against what was actually reported at 18:00 yesterday the move is `+0.96%`.
Same defect as 09-30 onward; suspects unchanged (21-day rolling window + late
listprice edits rewriting the stored series).

Export: 2,382 listings (2,051 priced) exported, 14,945 dropped (14,627
expired, 318 sold, 0 dead links); 1,209 reposts collapsed in-run (30.9%);
7,621 unique watches remain; 180 price outliers flagged and kept; 13 outlier
prices excluded from baselines; 276 of 298 unit baselines covering 7,590
listings (100%). Link check: 300/2,382 verified (capped). Sold tracer: 318
marked sold, all 318 by reply link, 0 by edit, median 3d to sell.

Signals: 2,469 confirmed sales (median 5d), 2,016 price cuts (median
-2.22%), inventory looks 187.0% deeper than it is. Availability score 50/100.
References: 314 published (149 full confidence, 165 limited; 11
variant-grouped, 19 model-level; 163 too thin, 26 too broad, 23 model-card
leftovers), deepest Rolex 126334 n=450 fair $19,300-$21,700 (+-6%).

1 anomaly flagged this run: 3 published listings with no resolved brand —
parser/brands.py coverage gap, example is the Carousell blue-degrade DJ36
post still surfacing through the dealer channels. Route drift and page
contract both clean. days_since_fresh=0.

Space asset `/data/watch-index.json` re-uploaded and verified: HTTP 200,
432,526 bytes, md5 `3fa34157b635b6cf090c499a3c79dff8`, byte-identical to
`data/index.json` on disk. Served composite reads back `1.118`, meta.updated
2026-10-05T18:15:20+08:00.

Zero-new-message channels this run (5): `ChuanwatchSG`, `goldmanluxurysg`,
`sgwatchinsider`, `HengWatch`, `kbluxury`. Per-channel counts
(5+0+48+1+57+10+0+13+2+0+0+0+3+5) sum to 144, exactly the scraper's reported
total, which validates the list. `goldmanluxurysg` (last post 2025-08-10) and
`sgwatchinsider` (2026-01-01) remain dead by definition; `HengWatch` and
`kbluxury` zeroed after printing at 12:00 today — flapping, not dead.
`watchbooksg` skipped 1 message with no timestamp (reported, not counted as a
new message). `schonwatch` still absent from CHANNELS.

Delivery: group send was ATTEMPTED this run and failed —
`send_telegram_message` to `-5370852148` returned "No Telegram binding found
for recipient '-5370852148'. Connected accounts: steamboat0x0." The single
Telegram call went to the user's DM, where it succeeded. To restore true
group delivery: add Zo's bot `@steamboat0x0` to group `-5370852148` as admin,
or repoint the automation's delivery target.
