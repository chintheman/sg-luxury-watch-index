import type { Context } from "hono";

// Per-reference price cards — the "what's it worth" layer.
//
// Source of truth is this file in chintheman/sg-luxury-watch-index; the copy
// deployed as a Zo space route is a deployment, not an original. Do NOT edit
// the route in the Zo UI — pipeline.py's check_drift.ts will flag it.
//
// The whole file is ~190KB raw and ~14KB gzipped, so it ships as one payload
// rather than a per-reference endpoint. The page needs the full set anyway to
// render the grid and to resolve a slug client-side.
const REFS_PATH = "/home/workspace/projects/sg-luxury-watch-index/data/references.json";

export default async (c: Context) => {
  try {
    const raw = await Bun.file(REFS_PATH).text();
    const data: any = JSON.parse(raw);
    const all: any[] = data.references || [];

    const params = c.req.query();

    // Single card by slug — used by /watches/:slug on a cold load.
    if (params.slug) {
      const card = all.find((r) => r.slug === params.slug);
      if (!card) return c.json({ error: "unknown reference", slug: params.slug }, 404);
      return c.json({
        generated: data.generated,
        windowDays: data.window_days,
        caveat: data.caveat,
        thresholds: data.thresholds,
        reference: card,
      });
    }

    let refs = all;
    if (params.brand) {
      const b = params.brand.toLowerCase();
      refs = refs.filter((r) => (r.brand || "").toLowerCase() === b);
    }
    if (params.q) {
      const q = params.q.toLowerCase();
      refs = refs.filter(
        (r) =>
          (r.ref || "").toLowerCase().includes(q) ||
          (r.model || "").toLowerCase().includes(q) ||
          (r.brand || "").toLowerCase().includes(q),
      );
    }
    // Cards with fewer than 20 recent listings are indicative, not
    // authoritative. They ship by default but can be excluded.
    if (params.confidence === "full") {
      refs = refs.filter((r) => r.confidence === "full");
    }

    const brands = [...new Set(all.map((r) => r.brand))].sort();

    return c.json({
      generated: data.generated,
      windowDays: data.window_days,
      caveat: data.caveat,
      thresholds: data.thresholds,
      coverage: data.coverage,
      brands,
      total: all.length,
      filtered: refs.length,
      references: refs,
    });
  } catch (e: any) {
    return c.json({ error: e.message }, 500);
  }
};
