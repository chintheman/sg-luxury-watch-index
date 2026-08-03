/**
 * Drift check — does the DEPLOYED Zo space route still match this repo?
 *
 * Zo exposes no REST API for reading or writing space-route source, so we
 * cannot diff the code directly. What we can do is diff BEHAVIOUR: run the
 * repo's handler in-process and compare its JSON against the live endpoint.
 * Both read the same data files on this box, so any difference in output is
 * a difference in code.
 *
 * This is the guard that makes "repo is SSOT" real. Without it, someone
 * editing the route in the Zo UI silently forks production from the repo —
 * which is exactly what already happened once (the copy in
 * 0xsteamboat-me-docs/zo-space/routes/ is a stale 2026-07-24 reconstruction
 * missing brandSubindices and computeBrand1dChange entirely).
 *
 * Usage:  bun web/check_drift.ts            # exits 1 on drift
 *         bun web/check_drift.ts --verbose  # show the first differing paths
 */

import handler from "./routes/api-watch-listings.ts";

const LIVE_URL = "https://0xsteamboat.zo.space/api/watch-listings";
const VERBOSE = process.argv.includes("--verbose");

// Minimal Hono-Context stand-in: the handler only uses req.query() and json().
function fakeContext(query: Record<string, string> = {}) {
  return {
    req: { query: () => query },
    json: (body: unknown, status?: number) => ({ body, status: status ?? 200 }),
  } as any;
}

// Field-by-field structural diff, returning dotted paths that differ.
function diff(a: any, b: any, path = "", out: string[] = []): string[] {
  if (out.length > 40) return out;
  if (a === b) return out;
  if (a === null || b === null || typeof a !== typeof b) {
    out.push(`${path || "<root>"}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
    return out;
  }
  if (typeof a !== "object") {
    if (a !== b) out.push(`${path}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
    return out;
  }
  if (Array.isArray(a) !== Array.isArray(b)) {
    out.push(`${path}: array/object mismatch`);
    return out;
  }
  if (Array.isArray(a)) {
    if (a.length !== b.length) out.push(`${path}.length: ${a.length} != ${b.length}`);
    for (let i = 0; i < Math.min(a.length, b.length); i++) diff(a[i], b[i], `${path}[${i}]`, out);
    return out;
  }
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    diff(a[k], b[k], path ? `${path}.${k}` : k, out);
  }
  return out;
}

const CASES: Array<[string, Record<string, string>]> = [
  ["default", {}],
  ["brand filter", { brand: "Rolex" }],
  ["condition + sort", { condition: "p", sort: "cheapest", limit: "50" }],
  ["photos only", { hasPhotos: "true", limit: "25" }],
];

// One comparison pass. Returns differing paths, or null if the run itself
// failed (which is not the same thing as drift and must not be reported as it).
async function compare(query: Record<string, string>): Promise<string[] | null> {
  let local: any;
  try {
    local = (await handler(fakeContext(query))).body;
  } catch (e: any) {
    console.error(`    local handler threw: ${e?.message ?? e}`);
    return null;
  }

  const qs = new URLSearchParams(query).toString();
  let live: any;
  try {
    const res = await fetch(qs ? `${LIVE_URL}?${qs}` : LIVE_URL, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      console.error(`    live endpoint returned HTTP ${res.status}`);
      return null;
    }
    live = await res.json();
  } catch (e: any) {
    console.error(`    could not reach live endpoint: ${e?.message ?? e}`);
    return null;
  }

  return diff(local, live);
}

let failed = false;

for (const [name, query] of CASES) {
  let d = await compare(query);

  // The local read and the live fetch happen at different instants against
  // the same files. A pipeline run writing listings.json in between produces
  // a real-looking diff that is not drift. Confirm once before believing it.
  if (d !== null && d.length > 0) {
    await new Promise(r => setTimeout(r, 2000));
    const again = await compare(query);
    if (again === null) { d = null; }
    else if (again.length === 0) {
      console.log(`✓ ${name}: matched on retry (first pass raced a data write)`);
      continue;
    } else { d = again; }
  }

  if (d === null) {
    failed = true;
    console.error(`✗ ${name}: check could not complete (see above) — not treated as a match`);
  } else if (d.length === 0) {
    console.log(`✓ ${name}: deployed route matches repo`);
  } else {
    failed = true;
    console.error(`✗ ${name}: DRIFT — ${d.length} differing path(s)`);
    for (const line of d.slice(0, VERBOSE ? 40 : 5)) console.error(`    ${line}`);
    if (!VERBOSE && d.length > 5) console.error(`    ... re-run with --verbose for the rest`);
  }
}

if (failed) {
  console.error(
    "\nThe deployed Zo route has diverged from web/routes/api-watch-listings.ts.\n" +
    "Zo has no deploy API — redeploy by writing the repo file's contents to the\n" +
    "space route (MCP: write_space_route, path=/api/watch-listings), then re-run.",
  );
  process.exit(1);
}
console.log("\nNo drift: the deployed route and the repo agree on all cases.");
