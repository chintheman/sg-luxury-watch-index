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
 *     www.0xsteamboat.me/api/watch-{listings,references}
 *       -> 0xsteamboat-me/server.ts proxy
 *         -> Zo space route
 *           -> data/index.json + data/listings.json + data/references.json
 * — rather than calling the handler in-process, so a break anywhere along
 * that chain is caught, not just a break in this repo.
 *
 * Two APIs are covered because the page was rebuilt around per-reference price
 * cards. /api/watch-references is now the PRODUCT: if it breaks, the page has
 * nothing on it. /api/watch-listings became secondary — watches.tsx catches its
 * failure silently and still renders — so its fields are checked but a missing
 * one is less severe than it used to be. The index hero it fed is now a single
 * context line.
 *
 * The contract below is derived from what watches.tsx and watch-ref.tsx
 * actually read. If you change the pages' field usage, change this too.
 *
 * Usage:  bun web/check_contract.ts        # exits 1 if the page would break
 */

const PUBLIC_API = "https://www.0xsteamboat.me/api/watch-listings";
const REFS_API = "https://www.0xsteamboat.me/api/watch-references";

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
// change_* may legitimately be null (the page renders '--'), but must never
// be a non-numeric non-null — that would print garbage into the tiles.
for (const k of ["change_1d_pct", "change_30d_pct"]) {
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

// ══ /api/watch-references — the product ══
let refs: any;
try {
  const res = await fetch(REFS_API, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    console.error(`✗ FATAL: references API returned HTTP ${res.status}`);
    console.error("  The page would show its error state to every visitor.");
    process.exit(1);
  }
  refs = await res.json();
} catch (e: any) {
  console.error(`✗ FATAL: could not reach ${REFS_API} — ${e.message}`);
  process.exit(1);
}

record("refs.references", Array.isArray(refs.references) && refs.references.length > 0,
  `${Array.isArray(refs.references) ? refs.references.length + " cards" : typeof refs.references}`,
  "the page has no product on it at all");
record("refs.coverage", refs.coverage != null && isNum(refs.coverage.references_published),
  String(refs.coverage?.references_published),
  "the coverage statement disappears, so the Rolex concentration goes unstated");
record("refs.caveat", typeof refs.caveat === "string" && refs.caveat.length > 80,
  `${(refs.caveat || "").length} chars`,
  "the 'asking prices, not sales' explanation empties out");
record("refs.windowDays", isNum(refs.windowDays), String(refs.windowDays),
  "the page cannot say what period the fair range covers");

// Every field a card renders. A card makes a direct claim to a buyer, so a
// missing field here is worse than a blank tile — it is a wrong number.
const REQUIRED_REF = [
  "slug", "brand", "ref", "confidence", "n_recent", "n_total", "window_days",
  "median", "fair_low", "fair_high", "low", "high", "days_since_last_seen",
  "channels", "monthly", "by_year", "specs", "sales_observed", "wide_spread",
];
const cards = (refs.references ?? []).slice(0, 50);
if (cards.length === 0) {
  record("references[]", false, "no cards returned", "the grid renders empty");
} else {
  for (const f of REQUIRED_REF) {
    const missing = cards.filter((c: any) => c[f] === undefined || c[f] === null);
    record(`references[].${f}`, missing.length === 0,
      missing.length ? `${missing.length}/${cards.length} missing` : `present on all ${cards.length}`,
      `reference cards render a broken ${f}`);
  }
  // The fair range is the claim. If it is incoherent the page actively misleads.
  const incoherent = cards.filter(
    (c: any) => !(c.low <= c.fair_low && c.fair_low <= c.median && c.median <= c.fair_high && c.fair_high <= c.high));
  record("references[] fair range is coherent", incoherent.length === 0,
    incoherent.length ? `${incoherent.length} broken, e.g. ${incoherent[0].slug}` : `checked ${cards.length}`,
    "the page quotes a fair range that does not contain its own median");
  // Slugs are the URLs. A duplicate means two watches share one page.
  const slugs = cards.map((c: any) => c.slug);
  record("references[] slugs are unique", new Set(slugs).size === slugs.length,
    `${new Set(slugs).size}/${slugs.length} unique`,
    "two references resolve to the same /watches/<slug> page");
  // Sample size must always accompany the claim.
  record("references[] state their sample size", cards.every((c: any) => isNum(c.n_recent) && c.n_recent >= 10),
    `min ${Math.min(...cards.map((c: any) => c.n_recent))}`,
    "a fair range renders with no evidence attached");
}

// A single-reference lookup is how /watches/:slug loads cold.
try {
  const one = await fetch(`${REFS_API}?slug=${encodeURIComponent(cards[0]?.slug ?? "")}`,
    { headers: { Accept: "application/json" } }).then((r) => r.json());
  record("refs?slug= returns one card", one?.reference?.slug === cards[0]?.slug,
    String(one?.reference?.slug), "every /watches/<slug> deep link renders an error state");
} catch (e: any) {
  record("refs?slug= returns one card", false, e.message,
    "every /watches/<slug> deep link renders an error state");
}

// ── Report ──
const failed = results.filter(r => !r.ok);
for (const r of results) {
  console.log(`${r.ok ? "✓" : "✗"} ${r.path.padEnd(32)} ${r.detail}`);
}
if (failed.length) {
  console.error(`\n${failed.length} contract violation(s) — www.0xsteamboat.me/watches WILL break:`);
  for (const r of failed) console.error(`  • ${r.path}: ${r.detail}  →  ${r.breaks}`);
  console.error("\nThe pages have no fallback: they do .catch(e => setError(e.message)),");
  console.error("so visitors see an error state. Fix before deploying.");
  process.exit(1);
}
console.log(`\nContract OK — all ${results.length} fields the live page reads are present and usable.`);
