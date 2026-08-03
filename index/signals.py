#!/usr/bin/env python3
"""Derived market signals — the things that are not visible in a price index.

These exist because of the ingestion work in Phase 2 and the deduplication in
Phase 4, not because of anything in the index maths. Reply links tell us when
a listing sold; repost groups tell us how a price moved while it sat.

Computed over the full corpus rather than the 14-day publishing window, since
a watch that sold last month is exactly the evidence we want.

Output: data/signals.json
"""
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))

from filter import extract_model, extract_price, is_watch_listing  # noqa: E402
from brands import match_brand  # noqa: E402
from attributes import extract_attributes  # noqa: E402
from dedupe import build_groups, summarise  # noqa: E402

SGT = timezone(timedelta(hours=8))
DB = ROOT / "data" / "listings.db"
OUT = ROOT / "data" / "signals.json"
SOLD_RE = re.compile(r"\bSOLD\b", re.I)
MAX_CHAIN_HOPS = 6

# A listing needs a plausible sale span to count. Same-day is legitimate (a
# watch can sell within hours); beyond a year is almost certainly a mismatched
# reply rather than a genuinely year-old sale.
MAX_SELL_DAYS = 365

# A brand median needs enough sales behind it to mean anything. At n=3 the
# published figures were "Panerai sells in 68 days" and "Tudor in 25" — those
# are three watches, not a market. Below this the brand is withheld rather
# than shown with a caveat nobody reads.
MIN_BRAND_SALES = 8


def _days(a, b):
    try:
        return (datetime.fromisoformat((b or "").replace("Z", "+00:00"))
                - datetime.fromisoformat((a or "").replace("Z", "+00:00"))).days
    except (ValueError, TypeError):
        return None


def build_signals():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT channel_handle, message_id, posted_at, message_text, views, "
        "       reply_to_message_id FROM raw_messages"
    ))
    conn.close()
    by_id = {(r["channel_handle"], r["message_id"]): r for r in rows}

    # ── Parse the listing universe once ──
    listings = {}
    for r in rows:
        t = r["message_text"] or ""
        if not is_watch_listing(t):
            continue
        brand = match_brand(t)
        price = extract_price(t)
        if not brand or not price or not (500 <= price <= 500000):
            continue
        model, ref = extract_model(t, brand)
        listings[(r["channel_handle"], r["message_id"])] = {
            "id": f"{r['channel_handle']}-{r['message_id']}",
            "channel": r["channel_handle"], "brand": brand, "price": price,
            "date": (r["posted_at"] or "")[:10], "posted_at": r["posted_at"],
            "ref": ref, "model": model, "views": r["views"],
            "stock_code": extract_attributes(t).get("stock_code"),
        }

    # ── Time to sell, from dealer-authored reply links ──
    sold = []
    for r in rows:
        if not r["reply_to_message_id"] or not SOLD_RE.search(r["message_text"] or ""):
            continue
        target = (r["channel_handle"], r["reply_to_message_id"])
        for _ in range(MAX_CHAIN_HOPS):          # dealers reply SOLD to SOLD
            parent = by_id.get(target)
            if parent is None:
                target = None
                break
            if not SOLD_RE.search(parent["message_text"] or ""):
                break
            if not parent["reply_to_message_id"]:
                target = None
                break
            target = (parent["channel_handle"], parent["reply_to_message_id"])
        else:
            target = None
        if not target or target not in listings:
            continue
        L = listings[target]
        d = _days(L["posted_at"], r["posted_at"])
        if d is None or not (0 <= d <= MAX_SELL_DAYS):
            continue
        sold.append({**L, "days_to_sell": d})

    def _dist(vals):
        if not vals:
            return None
        vals = sorted(vals)
        return {
            "n": len(vals), "median": vals[len(vals) // 2],
            "p25": vals[len(vals) // 4], "p75": vals[3 * len(vals) // 4],
        }

    by_brand_speed = {}
    grouped = defaultdict(list)
    for s in sold:
        grouped[s["brand"]].append(s["days_to_sell"])
    withheld = {}
    for b, v in grouped.items():
        if len(v) >= MIN_BRAND_SALES:
            by_brand_speed[b] = _dist(v)
        else:
            withheld[b] = len(v)

    # ── Price movement while listed, from repost groups ──
    recs = list(listings.values())
    for i, r in enumerate(recs):
        r.setdefault("id", i)
    groups = build_groups(recs)
    cuts, rises, spans = [], [], []
    biggest = None
    for g in groups:
        if len(g) < 2:
            continue
        s = summarise(g)
        spans.append(s["days_listed"])
        ch = s["price_change_pct"]
        if ch is None:
            continue
        (cuts if ch < 0 else rises).append(ch)
        if ch < 0 and (biggest is None or ch < biggest["price_change_pct"]):
            biggest = {**s, "brand": g[-1]["brand"], "model": g[-1].get("model"),
                       "ref": g[-1].get("ref")}

    # ── Attention, from view counts ──
    # Raw views are a function of channel size, not demand: a 23,000-subscriber
    # channel out-views a 438-subscriber one on every listing. Comparing brands
    # on raw views produced nonsense (Hermes 124,000 vs Omega 14,000 purely
    # because of where they were posted). Express each listing's views relative
    # to the median for ITS channel, so 1.0 means "typical attention here".
    viewed = [L for L in listings.values() if L.get("views")]
    chan_median = {}
    cg = defaultdict(list)
    for L in viewed:
        cg[L["channel"]].append(L["views"])
    for ch, v in cg.items():
        chan_median[ch] = median(v) or 1
    for L in viewed:
        base = chan_median.get(L["channel"]) or 1
        L["view_index"] = L["views"] / base

    view_by_brand = {}
    vg = defaultdict(list)
    for L in viewed:
        vg[L["brand"]].append(L["view_index"])
    for b, v in vg.items():
        if len(v) >= 10:
            view_by_brand[b] = round(median(v), 2)

    out = {
        "generated": datetime.now(SGT).isoformat(),
        "caveat": (
            "Time to sell is measured from dealer-authored SOLD replies, which "
            "only some channels post. It is a sample of confirmed sales, not a "
            "sell-through rate: listings that never sell are invisible here, so "
            "these figures skew fast and describe only the dealers who post "
            "sold notices at all. Price movement is measured on watches "
            "reposted by the same dealer. Attention is indexed to each "
            "channel's own median, because raw view counts mostly measure "
            "channel size rather than interest in the watch."
        ),
        "time_to_sell": {
            "overall": _dist([s["days_to_sell"] for s in sold]),
            # How much of the market this actually describes. A confirmed sale
            # requires the dealer to post a SOLD reply, and most do not, so
            # this is a small and self-selected slice — state it in the data
            # rather than only in prose.
            "coverage": {
                "watches_with_confirmed_sale": len(sold),
                "unique_watches_total": None,        # filled in below
                "pct_of_watches": None,
                "channels_posting_sold_replies": sorted(
                    {s["channel"] for s in sold}
                ),
            },
            "by_brand": by_brand_speed,
            "by_brand_withheld_too_few_sales": withheld,
            "min_sales_to_publish_a_brand": MIN_BRAND_SALES,
            "fastest": sorted(sold, key=lambda s: s["days_to_sell"])[:5] and [
                {"brand": s["brand"], "model": s["model"], "price": s["price"],
                 "days": s["days_to_sell"]}
                for s in sorted(sold, key=lambda s: s["days_to_sell"])[:5]
            ],
        },
        "price_movement": {
            "watches_reposted": sum(1 for g in groups if len(g) > 1),
            "price_cuts": len(cuts),
            "price_rises": len(rises),
            "median_cut_pct": round(median(cuts), 2) if cuts else None,
            "median_days_listed": int(median(spans)) if spans else None,
            "biggest_cut": biggest,
        },
        "inventory": {
            "raw_listings": len(recs),
            "unique_watches": len(groups),
            "apparent_inflation_pct": round(100 * (len(recs) / len(groups) - 1), 1) if groups else 0,
        },
        "attention": {
            "listings_with_views": len(viewed),
            "median_views": int(median([L["views"] for L in viewed])) if viewed else None,
            # 1.0 = typical attention for the channel it was posted on.
            "relative_attention_by_brand": dict(sorted(view_by_brand.items(),
                                                       key=lambda kv: -kv[1])[:10]),
        },
    }
    cov = out["time_to_sell"]["coverage"]
    cov["unique_watches_total"] = out["inventory"]["unique_watches"]
    cov["pct_of_watches"] = round(
        100 * len(sold) / out["inventory"]["unique_watches"], 1
    ) if out["inventory"]["unique_watches"] else 0.0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    tts = out["time_to_sell"]["overall"]
    pm = out["price_movement"]
    print(f"Signals: {tts['n'] if tts else 0} confirmed sales, "
          f"median {tts['median'] if tts else '-'}d to sell | "
          f"{pm['price_cuts']} price cuts (median {pm['median_cut_pct']}%) | "
          f"inventory looks {out['inventory']['apparent_inflation_pct']}% deeper than it is")
    return out


if __name__ == "__main__":
    build_signals()
