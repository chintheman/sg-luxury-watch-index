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
        retailComposite: indexDataObj.retail_composite ? {
          current: indexDataObj.retail_composite.current,
          change_1d: indexDataObj.retail_composite.change_1d,
          change_1d_pct: indexDataObj.retail_composite.change_1d_pct,
        } : null,
        brandSub: brandSubindices,
        brandsTracked: indexDataObj.meta?.tracked_brands,
        anchorDate: indexDataObj.meta?.anchor_date,
        insight: indexDataObj.insights?.composite || "",
        brandContribs: (indexDataObj.brand_contributions || []).slice(0, 5),
      } : null,
    });
  } catch (e: any) {
    return c.json({ error: e.message }, 500);
  }
};

// Inline model extraction (mirrors filter.py)
const MODEL_NAMES = [
  /Submariner|GMT-Master|Daytona|Datejust|Explorer|Yacht-Master|Day-Date|Sea-Dweller|Sky-Dweller|Air-King|Milgauss|OP/i,
  /Speedmaster|Seamaster|Planet Ocean|Aqua Terra|Constellation|De Ville|Globemaster/i,
  /Santos|Tank|Panthère|Ballon Bleu|Ronde|Tortue|Calibre|Drive/i,
  /Black Bay|Pelagos|Royal|1926|North Flag|Fastrider|Heritage/i,
  /Royal Oak|Millenary|Code 11|Jules Audemars/i,
  /Nautilus|Aquanaut|Calatrava|Grand Complications|Twenty~4/i,
  /Portofino|Pilot|Ingenieur|Aquatimer|Da Vinci|Portugieser/i,
  /Luminor|Radiomir|Submersible|Mare Nostrum/i,
  /Big Bang|Classic Fusion|Spirit|King Power|Square Bang/i,
  /Carrera|Monaco|Aquaracer|Formula 1|Link|Autavia/i,
  /Overseas|Patrimony|Traditionnelle|Malte|Fiftysix|Historiques/i,
  /Prospex|Presage|Astron|5 Sports|Coutura/i,
  /Classique|Marine|Type XX|Tradition|Héritage|Reine de Naples/i,
  /Lange 1|Zeitwerk|Saxonia|Odysseus|1815|Richard Lange/i,
];
const REF_RE = /\b(\d{3,6}(?:\.\d{2,4}){0,4}[A-Z]{0,4})\b/;

function extractModel(text: string, _brand: string): string | null {
  if (!text) return null;
  for (const pat of MODEL_NAMES) {
    const m = text.match(pat);
    if (m) {
      const model = m[0];
      const ref = text.match(REF_RE)?.[1];
      return ref ? `${model} ${ref}` : model;
    }
  }
  const ref = text.match(REF_RE)?.[1];
  return ref || null;
}

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
