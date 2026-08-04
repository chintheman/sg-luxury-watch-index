# How www.0xsteamboat.me/watches actually works

Read this before changing anything in this repo. The page is served by a
different repo than the one you are probably looking at, and there is a
retired copy of it that looks live but is not.

## The chain

```
  visitor
    │
    ▼
  https://www.0xsteamboat.me/watches          ← reference grid + search
  https://www.0xsteamboat.me/watches/<slug>   ← one reference, e.g. rolex-126334
    │   Vite + Bun app — repo: chintheman/0xsteamboat-me (PRIVATE)
    │   on this box at /home/workspace/0xsteamboat-me
    │   page source: src/pages/watches.tsx, src/pages/watch-ref.tsx
    │                src/components/watch.tsx   (shared card pieces)
    │   runs as a Zo service (see zosite.json)
    ▼
  GET /api/watch-references     ← THE PRODUCT
  GET /api/watch-listings       ← secondary; the page survives without it
    │   proxied by 0xsteamboat-me/server.ts (~line 293)
    │   query params ARE forwarded on the references proxy: /watches/<slug>
    │   resolves via ?slug= on a cold load
    ▼
  https://0xsteamboat.zo.space/api/watch-{references,listings}
    │   Zo space routes — source of truth: web/routes/*.ts (THIS REPO)
    │   deployed by hand; Zo has no deploy API
    ▼
  /home/workspace/projects/sg-luxury-watch-index/data/
    ├── references.json ← written by index/references.py     (price cards)
    ├── index.json      ← written by index/index_engine.py   (the composite)
    └── listings.json   ← written by index/export_pipeline.py (14-day live feed)
        all refreshed by pipeline.py, twice daily (see ops/cron.md)
```

**What the page is.** It answers "what's it worth / am I being ripped off" for
one reference, not "is the market moving". The composite index still computes
and still ships, but it is one context line — it blends a $13,500 Datejust
with a $62,000 Daytona, so it describes no watch anyone is actually buying.

**Where history lives.** `listings.json` is a 14-day live snapshot
(`max_age_days=14` in `export_pipeline.py`). Anything historical must read
`data/listings.db` directly, as `index/signals.py` and `index/references.py`
do. Both share one corpus parse via `signals.load_rows` / `parse_listings` so
the definition of "a listing" cannot drift between them.

## Traps

**The Zo space route `/watches` no longer exists.** It was a retired earlier
version of the page, kept private so it 302'd to a login screen, and it still
contained plausible-looking code — claims about "15 channels", brand cards
with volume counts, an `insight` useMemo. None of it was live, and it cost a
full audit pass before that was noticed. Deleted 2026-08-03. The real page is
`0xsteamboat-me/src/pages/watches.tsx` and always was.

**The Zo space route `/api/watch-listings` is LIVE and load-bearing.** Its
source of truth is `web/routes/api-watch-listings.ts` in this repo. Zo exposes
no API to read or write route source, so the two can silently fork — and
already did once: the copy in `0xsteamboat-me-docs/zo-space/routes/` is a
stale 2026-07-24 reconstruction missing `brandSubindices` and
`computeBrand1dChange` entirely. Do not trust that directory.

**A reference is identified by brand AND number.** Slugs are brand-prefixed
(`rolex-126334`) because bare references collide — 9 reference tokens in this
corpus are claimed by more than one brand. `check_contract.ts` asserts slug
uniqueness for exactly this reason.

**The pages have no fallback.** `watches.tsx` does
`.catch(e => setError(e.message))` on the references fetch. Any field that API
stops returning becomes an error state for real visitors. (The listings fetch
is caught silently — it is secondary.) There is no cached copy and no degraded
mode.

## The two guards

Both run automatically inside `pipeline.py`'s anomaly step, twice daily, and
surface through the Telegram report.

| Check | Question it answers | Fails when |
|---|---|---|
| `web/check_drift.ts` | Does the deployed Zo route still match this repo? | Someone edited the route in the Zo UI |
| `web/check_contract.ts` | Does the API still give the page every field it reads? | A pipeline change dropped or renamed a field |

`check_drift` compares behaviour, not text — it runs the repo's handler
in-process and diffs its JSON against the live endpoint across four query
shapes. Both read the same files on this box, so any difference is a code
difference. It retries once before reporting, because a pipeline run writing
`listings.json` between the two reads produces a real-looking but spurious diff.

`check_contract` fetches the **full public chain**
(`www.0xsteamboat.me/api/watch-listings`) rather than calling the handler
directly, so a break anywhere — proxy, Zo route, data files — is caught. The
contract it enforces is derived from what `watches.tsx` actually reads. If you
change the page's field usage, change `check_contract.ts` to match.

Run them by hand any time:

```bash
bun web/check_drift.ts --verbose
bun web/check_contract.ts
```

## Redeploying the API route

There is no deploy command. After editing `web/routes/api-watch-listings.ts`:

1. Write the file's contents to the Zo space route at path
   `/api/watch-listings` (MCP tool `write_space_route`, or paste it in the Zo
   Space UI).
2. Run `bun web/check_drift.ts` to confirm the deploy landed.
3. Run `bun web/check_contract.ts` to confirm the page still renders.

## Fields the live page depends on

Changing the shape of any of these breaks the page. `check_contract.ts`
enforces the full list.

- top level: `listings`, `index`, `total`, `brandVolumes`
- `index`: `composite`, `anchorDate`, `insight`, `brandsTracked`, `brandSub`,
  and `change_{1d,7d,30d,90d}_pct` (these four may be `null` — the page
  renders `--` — but must never be a non-numeric non-null)
- each listing: `id`, `date`, `brand`, `title`, `price`, `condition`,
  `channel`, `photos`, `link` (`model` may be null)
