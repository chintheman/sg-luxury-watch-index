# How www.0xsteamboat.me/watches actually works

Read this before changing anything in this repo. The page is served by a
different repo than the one you are probably looking at, and there is a
retired copy of it that looks live but is not.

## The chain

```
  visitor
    │
    ▼
  https://www.0xsteamboat.me/watches
    │   Vite + Bun app — repo: chintheman/0xsteamboat-me (PRIVATE)
    │   on this box at /home/workspace/0xsteamboat-me
    │   page source: src/pages/watches.tsx     ← THE REAL PAGE
    │   runs as a Zo service (see zosite.json)
    ▼
  GET /api/watch-listings
    │   proxied by 0xsteamboat-me/server.ts (line ~293)
    ▼
  https://0xsteamboat.zo.space/api/watch-listings
    │   Zo space route — source of truth: web/routes/api-watch-listings.ts (THIS REPO)
    │   deployed by hand; Zo has no deploy API
    ▼
  /home/workspace/projects/sg-luxury-watch-index/data/
    ├── index.json      ← written by index/index_engine.py
    └── listings.json   ← written by index/export_pipeline.py
        both refreshed by pipeline.py, twice daily (see ops/cron.md)
```

## Traps

**The Zo space route `/watches` is DEAD.** `0xsteamboat.zo.computer/watches`
returns 302. It is a retired earlier version of the page and still contains
plausible-looking code — claims about "15 channels", brand cards showing
volume counts, a `insight` useMemo. **None of it is live.** Editing it does
nothing. The real page is `0xsteamboat-me/src/pages/watches.tsx`.

**The Zo space route `/api/watch-listings` is LIVE and load-bearing.** Its
source of truth is `web/routes/api-watch-listings.ts` in this repo. Zo exposes
no API to read or write route source, so the two can silently fork — and
already did once: the copy in `0xsteamboat-me-docs/zo-space/routes/` is a
stale 2026-07-24 reconstruction missing `brandSubindices` and
`computeBrand1dChange` entirely. Do not trust that directory.

**The page has no fallback.** `watches.tsx` does
`.catch(e => setError(e.message))`. Any field the API stops returning becomes
an error state for real visitors. There is no cached copy and no degraded
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
