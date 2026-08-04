import type { Context } from "hono";

const DATA_PATH = "/home/workspace/projects/sg-luxury-watch-index/data/listings.json";
const INDEX_PATH = "/home/workspace/projects/sg-luxury-watch-index/data/index.json";

export default async (c: Context) => {
  try {
    const [listingsData, indexData] = await Promise.all([
      Bun.file(DATA_PATH).text(),
      Bun.file(INDEX_PATH).text(),
    ]);

    const listingsRaw: any[] = JSON.parse(listingsData);
    const indexDataObj: any = JSON.parse(indexData);

    // Build lookup from index for brand volumes
    const brandVolumes: Record<string, number> = indexDataObj?.brand_counts || {};

    // Filter to only clean listings (has brand, has price, not SOLD)
    const clean = [];
    const soldPattern = /\bSOLD\b/i;
    const seen = new Set<string>();

    for (const r of listingsRaw) {
      const text = r.t || "";
      if (!text || soldPattern.test(text)) continue;
      if (!r.p || !r.b) continue;
      if (r.p < 100) continue;

      // Deduplicate by date+brand+price
      const key = `${r.d}|${r.b}|${r.p}`;
      if (seen.has(key)) continue;
      seen.add(key);

      // Use pre-extracted model from listing
      const model = r.md || "";
      const title = cleanTitle(text);

      clean.push({
        id: r.i,
        date: r.d,
        brand: r.b,
        model: model,
        // The reference is what /watches/<slug> joins on. It used to be
        // withheld here, so the reference page fell back to searching for the
        // number inside a 120-character title — which missed 47 of 113 cards
        // and made the click-through to Telegram a dead end on most of them.
        ref: r.ref || null,
        title: title,
        price: r.p,
        condition: r.n || "u",
        channel: r.c,
        photos: r.f || 0,
        link: r.l || `https://t.me/s/${r.c}/${r.m}`,
      });
    }

    // Stats
    const brands = [...new Set(clean.map(l => l.brand))];
    const channelCounts: Record<string, number> = {};
    for (const l of clean) {
      channelCounts[l.channel] = (channelCounts[l.channel] || 0) + 1;
    }

    // Apply filters
    const params = c.req.query();
    let filtered = clean;
    if (params.brand) {
      filtered = filtered.filter(l => l.brand.toLowerCase() === params.brand.toLowerCase());
    }
    if (params.condition && params.condition !== "all") {
      filtered = filtered.filter(l => l.condition === params.condition);
    }
    if (params.model) {
      const q = params.model.toLowerCase();
      filtered = filtered.filter(l =>
        (l.model || "").toLowerCase().includes(q) ||
        l.title.toLowerCase().includes(q)
      );
    }
    if (params.hasPhotos === "true") {
      filtered = filtered.filter(l => l.photos > 0);
    }
    if (params.ref) {
      const want = params.ref.toUpperCase();
      filtered = filtered.filter(l => {
        const got = (l.ref || "").toUpperCase();
        if (!got) return false;
        // Exact, or a variant of a grouped reference (15510ST.OO.1320ST.06
        // belongs to the 15510ST card).
        return got === want || got.startsWith(want + ".");
      });
    }

    // Sort
    const sort = params.sort || "newest";
    switch (sort) {
      case "cheapest": filtered.sort((a, b) => a.price - b.price); break;
      case "expensive": filtered.sort((a, b) => b.price - a.price); break;
      default: filtered.sort((a, b) => (b.date || "").localeCompare(a.date || "")); break;
    }

    const limit = parseInt(params.limit || "200");
    const page = filtered.slice(0, limit);

    // Helper: compute 1d change from a brand series
    const computeBrand1dChange = (series: any[]) => {
      if (!series || series.length < 2) return null;
      const last = series[series.length - 1];
      const prev = series[series.length - 2];
      if (last?.value == null || prev?.value == null) return null;
      return ((last.value - prev.value) / prev.value * 100);
    };

    // Build brand subindex data with 1d changes
    const brandSubindices: Record<string, any> = {};
    if (indexDataObj?.brand_subindices) {
      for (const [brand, data] of Object.entries(indexDataObj.brand_subindices) as any) {
        brandSubindices[brand] = {
          current: data.current,
          change_1d_pct: data.series ? computeBrand1dChange(data.series) : null,
        };
      }
    }

    return c.json({
      total: clean.length,
      filtered: filtered.length,
      brands: brands.sort(),
      channels: Object.entries(channelCounts).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count),
      listings: page,
      brandVolumes,
      index: indexDataObj ? {
        composite: indexDataObj.composite?.current,
        change_1d: indexDataObj.composite?.change_1d,
        change_1d_pct: indexDataObj.composite?.change_1d_pct,
        change_7d: indexDataObj.composite?.change_7d,
        change_7d_pct: indexDataObj.composite?.change_7d_pct,
        change_30d: indexDataObj.composite?.change_30d,
        change_30d_pct: indexDataObj.composite?.change_30d_pct,
        change_90d: indexDataObj.composite?.change_90d,
        change_90d_pct: indexDataObj.composite?.change_90d_pct,
        brandSub: brandSubindices,
        brandsTracked: indexDataObj.meta?.tracked_brands,
        anchorDate: indexDataObj.meta?.anchor_date,
        // The engine computes these and the page needs them to tell the truth.
        // They were being dropped here, so a carried-forward value rendered
        // identically to a freshly computed one.
        stale: indexDataObj.composite?.stale ?? null,
        daysSinceFresh: indexDataObj.composite?.days_since_fresh ?? null,
        // The date the series ACTUALLY begins. anchor_date is when the data
        // first met the inclusion criteria, which is earlier and is not when
        // the index started — the page was presenting it as "Since ...".
        firstComputedDate: indexDataObj.meta?.first_computed?.date ?? null,
        methodologyVersion: indexDataObj.meta?.version ?? null,
        methodology: indexDataObj.meta?.methodology ?? "",
        insight: indexDataObj.insights?.composite || "",
        brandContribs: (indexDataObj.brand_contributions || []).slice(0, 5),
      } : null,
    });
  } catch (e: any) {
    return c.json({ error: e.message }, 500);
  }
};

// NOTE: a copy of filter.py's model-extraction regexes used to live here and
// was never called — the pipeline supplies the model as `md`. It has been
// removed rather than left to drift silently out of sync with the parser.

function cleanTitle(text: string): string {
  if (!text) return "";
  const lines = text.trim().split("\n");
  for (const line of lines) {
    const clean = line.trim();
    if (!clean || clean.length < 5) continue;
    if (/^[📢🕘⏰🔄✅💰🔥🎉]/.test(clean)) continue;
    if (/t\.me\/|bit\.ly\/|https?:\/\//.test(clean)) continue;
    if (/^(Join|Follow|Subscribe|DM|PM|WhatsApp|Telegram|Contact)\b/i.test(clean)) continue;
    return clean.slice(0, 120);
  }
  return lines[0]?.trim().slice(0, 120) || "";
}
