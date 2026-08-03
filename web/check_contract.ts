/**
 * Contract check — will www.0xsteamboat.me/watches still render?
 *
 * This is NOT the drift check. Drift asks "does the deployed route match the
 * repo?". This asks a different and more important question: "does the API
 * still give the live page every field it reads?"
 *
 * It matters because the page has no fallback. src/pages/watches.tsx does
 *     .catch(e => setError(e.message))
 * so any missing or malformed field renders an error state to real visitors.
 * The upcoming pipeline work (schema changes in listings.json, index.json
 * v3 math, dedup, new extracted fields) can all silently break a field the
 * page depends on. This catches that before a visitor does.
 *
 * It deliberately fetches the FULL public chain —
 *     www.0xsteamboat.me/api/watch-listings
 *       -> 0xsteamboat-me/server.ts proxy
 *         -> Zo space route /api/watch-listings
 *           -> data/index.json + data/listings.json
 * — rather than calling the handler in-process, so a break anywhere along
 * that chain is caught, not just a break in this repo.
 *
 * The contract below is derived from what watches.tsx actually reads. If you
 * change the page's field usage, change this too.
 *
 * Usage:  bun web/check_contract.ts        # exits 1 if the page would break
 */

const PUBLIC_API = "https://www.0xsteamboat.me/api/watch-listings";

type Check = { path: string; ok: boolean; detail: string; breaks: string };
const results: Check[] = [];

function record(path: string, ok: boolean, detail: string, breaks: string) {
  results.push({ path, ok, detail, breaks });
}

function isNum(v: unknown): boolean {
  return typeof v === "number" && Number.isFinite(v);
}

let payload: any;
try {
  const res = await fetch(PUBLIC_API, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    console.error(`✗ FATAL: public API returned HTTP ${res.status}`);
    console.error("  The page would show its error state to every visitor.");
    process.exit(1);
  }
  payload = await res.json();
} catch (e: any) {
  console.error(`✗ FATAL: could not reach ${PUBLIC_API} — ${e.message}`);
  process.exit(1);
}

// ── Top level: read in the page's fetch .then() ──
record("listings", Array.isArray(payload.listings),
  `${Array.isArray(payload.listings) ? payload.listings.length + " items" : typeof payload.listings}`,
  "the listing feed renders empty");
record("index", payload.index != null && typeof payload.index === "object",
  typeof payload.index, "the entire index hero renders as '—'");
record("total", isNum(payload.total), String(payload.total),
  "the '{total} listings' counters render NaN");
record("brandVolumes", payload.brandVolumes != null && typeof payload.brandVolumes === "object",
  `${Object.keys(payload.brandVolumes ?? {}).length} brands`,
  "the brand filter chips disappear");

// ── index.*: read in the hero, methodology note and footer ──
const idx = payload.index ?? {};
record("index.composite", isNum(idx.composite), String(idx.composite),
  "the headline index number renders '—'");
record("index.anchorDate", typeof idx.anchorDate === "string" && idx.anchorDate.length > 0,
  String(idx.anchorDate), "the footer 'Since ...' and methodology note lose their date");
record("index.insight", typeof idx.insight === "string", typeof idx.insight,
  "the 'Latest insight' banner disappears");
record("index.brandsTracked", isNum(idx.brandsTracked), String(idx.brandsTracked),
  "the brand count falls back to a hardcoded 30");
record("index.brandSub", idx.brandSub != null && typeof idx.brandSub === "object",
  `${Object.keys(idx.brandSub ?? {}).length} brands`, "per-brand sub-index values render '--'");

// change_* may legitimately be null (the page renders '--'), but must never
// be a non-numeric non-null — that would print garbage into the tiles.
for (const k of ["change_1d_pct", "change_7d_pct", "change_30d_pct", "change_90d_pct"]) {
  const v = idx[k];
  record(`index.${k}`, v === null || v === undefined || isNum(v), String(v),
    `the ${k.replace("change_", "").replace("_pct", "").toUpperCase()} tile prints a non-number`);
}

// ── Honesty fields (added in Phase 7) ──
// These exist so the page can disclose when a value is carried forward and
// where the series really starts. They were computed by the engine and
// silently dropped by this API for months; the contract now holds them.
record("index.stale", idx.stale === null || typeof idx.stale === "boolean",
  String(idx.stale), "the page cannot tell a carried-forward value from a fresh one");
record("index.daysSinceFresh", idx.daysSinceFresh === null || isNum(idx.daysSinceFresh),
  String(idx.daysSinceFresh), "the staleness marker cannot say how old the reading is");
record("index.firstComputedDate",
  idx.firstComputedDate === null || typeof idx.firstComputedDate === "string",
  String(idx.firstComputedDate), "the footer falls back to implying history that does not exist");
record("index.methodology", typeof idx.methodology === "string" && idx.methodology.length > 40,
  `${(idx.methodology || "").length} chars`,
  "the methodology note empties out, or drifts from the maths again");
record("index.methodologyVersion",
  idx.methodologyVersion === null || typeof idx.methodologyVersion === "string",
  String(idx.methodologyVersion), "the page cannot state which methodology produced the number");

// ── Per-listing fields: every one is read in the listing row ──
const REQUIRED_LISTING = ["id", "date", "brand", "title", "price", "condition", "channel", "photos", "link"];
const sample = (payload.listings ?? []).slice(0, 50);
if (sample.length === 0) {
  record("listings[]", false, "no listings returned", "the page shows 'No listings match your filters'");
} else {
  for (const f of REQUIRED_LISTING) {
    const missing = sample.filter((l: any) => l[f] === undefined || l[f] === null);
    record(`listings[].${f}`, missing.length === 0,
      missing.length ? `${missing.length}/${sample.length} missing` : `present on all ${sample.length}`,
      `listing rows render a blank ${f}`);
  }
  record("listings[].price is numeric", sample.every((l: any) => isNum(l.price)),
    "checked " + sample.length, "prices render as NaN in the SGD formatter");
}

// ── Sanity: a technically-valid but empty payload still kills the page ──
record("sanity: total > 0", isNum(payload.total) && payload.total > 0, String(payload.total),
  "the page renders with no inventory at all");

// ── Report ──
const failed = results.filter(r => !r.ok);
for (const r of results) {
  console.log(`${r.ok ? "✓" : "✗"} ${r.path.padEnd(32)} ${r.detail}`);
}
if (failed.length) {
  console.error(`\n${failed.length} contract violation(s) — www.0xsteamboat.me/watches WILL break:`);
  for (const r of failed) console.error(`  • ${r.path}: ${r.detail}  →  ${r.breaks}`);
  console.error("\nThe page has no fallback: watches.tsx does .catch(e => setError(e.message)),");
  console.error("so visitors see an error state. Fix before deploying.");
  process.exit(1);
}
console.log(`\nContract OK — all ${results.length} fields the live page reads are present and usable.`);
