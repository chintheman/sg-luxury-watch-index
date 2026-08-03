#!/usr/bin/env python3
"""
Export + Index recalculation pipeline v2.
- Integrated sold tracing (cross-references SOLD messages against active listings)
- Time-based expiry (drop listings older than N days)
- Optional link checking (verify t.me links still resolve) — used by
  pipeline.py on the regular schedule; scoped to listings at least
  LINK_CHECK_MIN_AGE_DAYS old and capped at LINK_CHECK_MAX_PER_RUN per run
  (oldest first) so it stays cheap enough to run every time rather than
  needing a separate manual pass.

Usage:
  python index/export_pipeline.py                     # Default: 14d expiry, sold trace, no link check
  python index/export_pipeline.py --max-age-days 7     # 7-day expiry
  python index/export_pipeline.py --link-check          # Enable link verification (age-filtered, capped)
  python index/export_pipeline.py --no-sold-trace       # Skip sold tracing
"""

import sys, json, argparse, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))

from filter import is_watch_listing, extract_price as filt_extract_price, extract_condition, extract_model
from attributes import extract_attributes
from dedupe import dedupe
from batch import is_batch_listing_post, split_batch_items, listing_key
from index.index_engine import extract_brand, build_indices

import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

SGT = timezone(timedelta(hours=8))
DB = ROOT / "data" / "listings.db"
LISTINGS_OUT = ROOT / "data" / "listings.json"
INDEX_OUT = ROOT / "data" / "index.json"
REMOVED_IN = ROOT / "data" / "removed.json"


# Link-checking is a real HTTP request per listing (~0.3s rate-limited) — on
# the full listing set that's minutes of runtime and load against Telegram's
# public web view every run. Two things keep it cheap enough to run on the
# regular schedule instead of needing a manual --link-check invocation:
# skip listings too new to plausibly be dead yet, and cap how many get
# checked in a single run (oldest first, since staleness risk rises with
# age) so coverage rotates across runs instead of one run doing everything.
LINK_CHECK_MIN_AGE_DAYS = 2
LINK_CHECK_MAX_PER_RUN = 300


def export_listings(max_age_days=14, link_check=False, sold_trace=True):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Time cutoff
    now = datetime.now(SGT)
    cutoff_date = (now - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    db_cutoff = (now - timedelta(days=90)).isoformat()

    rows = conn.execute(
        "SELECT id, channel_handle, message_id, posted_at, message_text, photos_count, views "
        "FROM raw_messages WHERE posted_at >= ? ORDER BY posted_at DESC",
        (db_cutoff,)
    ).fetchall()

    # ── Phase 1: classify + age-filter. Sold-removal is applied in Phase 2,
    # AFTER sold-tracing, so the tracer can match against this run's own
    # freshly-classified set instead of yesterday's on-disk listings.json —
    # otherwise most genuine sold-matches never line up with what's actually
    # about to be published, and a listing scraped-then-sold in the same run
    # is never caught at all. ──
    candidates = []
    expired_count = 0

    def _classify(text):
        """Returns a candidate dict (minus i/c/m/l/d) or None. Shared by both
        single-item posts and each sub-item of a split batch post so both go
        through identical brand/price/accessory/noise checks."""
        brand = extract_brand(text)
        price = filt_extract_price(text)
        if not (brand or price) or not is_watch_listing(text):
            return None
        cond = extract_condition(text)
        model_name, ref = extract_model(text, brand)
        # `md` is a model NAME ("Submariner"); `ref` is the reference number
        # ("126610LN"). Only the reference is specific enough to identify a
        # watch — deduping on the model name would merge every Submariner one
        # dealer holds within the price tolerance.
        rec = {"t": text[:200], "p": price, "b": brand, "n": cond,
               "md": model_name, "ref": ref}
        # Structured attributes: stored now, displayed later. Only non-null
        # values are carried so listings.json does not bloat with nulls.
        rec.update({k: v for k, v in extract_attributes(text).items() if v is not None})
        return rec

    for r in rows:
        text = r["message_text"] or ""
        listing_date = r["posted_at"][:10] if r["posted_at"] else None
        link = f"https://t.me/s/{r['channel_handle']}/{r['message_id']}"

        if is_batch_listing_post(text):
            # One raw message, many watches — only items marked available in
            # the post's own status marker become candidates; sold ones are
            # simply not published (see parser/batch.py for why this exists).
            for item in split_batch_items(text):
                if not item["available"]:
                    continue
                fields = _classify(item["body"])
                if fields is None:
                    continue
                if listing_date and listing_date < cutoff_date:
                    expired_count += 1
                    continue
                candidates.append({
                    "i": r["id"],
                    "c": r["channel_handle"],
                    "m": r["message_id"],
                    "si": item["item_number"],
                    "d": listing_date,
                    "f": r["photos_count"] or 0,
                    "v": r["views"],
                    "l": link,
                    **fields,
                })
            continue

        fields = _classify(text)
        if fields is None:
            continue

        # ── Time-based expiry ──
        if listing_date and listing_date < cutoff_date:
            expired_count += 1
            continue

        candidates.append({
            "i": r["id"],
            "c": r["channel_handle"],
            "m": r["message_id"],
            "d": listing_date,
            "f": r["photos_count"] or 0,
            "v": r["views"],
            "l": link,
            **fields,
        })

    # ── Phase 1b: collapse reposts of the same physical watch ──
    # 35% of listings are the same watch posted again. Dedupe before anything
    # downstream counts them, and keep the newest sighting so the published
    # price is the current asking price.
    for cd in candidates:
        cd["_ddid"] = listing_key(cd)
    deduped, dstats = dedupe([
        {"id": cd["_ddid"], "channel": cd.get("c"), "brand": cd.get("b"),
         "price": cd.get("p"), "date": cd.get("d"), "ref": cd.get("ref"),
         "stock_code": cd.get("stock_code"), "_orig": cd}
        for cd in candidates
    ])
    keep_ids = {d["id"] for d in deduped}
    dup_by_id = {d["id"]: d.get("dup") for d in deduped if d.get("dup")}
    candidates = [cd for cd in candidates if cd["_ddid"] in keep_ids]
    for cd in candidates:
        if cd["_ddid"] in dup_by_id:
            cd["dup"] = dup_by_id[cd["_ddid"]]
        cd.pop("_ddid", None)
    print(f"Dedupe: {dstats['removed']} repost(s) collapsed "
          f"({dstats['removed_pct']}%), {dstats['groups_with_repeats']} watch(es) "
          f"listed more than once")

    # ── Phase 2: sold-trace against this run's own candidates, then filter ──
    removed_ids = set()
    removed_reasons = {}
    if sold_trace:
        try:
            from sold_tracer import trace_sold_messages
            trace_result = trace_sold_messages(str(DB), listings=candidates)
            removed_ids = set(trace_result.get("removed_ids", []))
            removed_reasons = trace_result.get("reasons", {})
            print(f"Sold tracer: marked {len(removed_ids)} listings for removal")
        except ImportError as e:
            print(f"Sold tracer unavailable: {e}")

    # Carry over any removals from previous runs the fresh trace didn't re-derive
    if REMOVED_IN.exists():
        prev = json.loads(REMOVED_IN.read_text())
        for rid in prev.get("removed_ids", []):
            removed_ids.add(rid)
            if rid not in removed_reasons and rid in prev.get("reasons", {}):
                removed_reasons[rid] = prev["reasons"][rid]

    listings = []
    sold_removed_count = 0
    for c in candidates:
        listing_id = listing_key(c)
        if listing_id in removed_ids:
            sold_removed_count += 1
            continue
        listings.append(c)

    # ── Link checking ──
    link_dead_count = 0
    if link_check:
        min_age_date = (now - timedelta(days=LINK_CHECK_MIN_AGE_DAYS)).strftime("%Y-%m-%d")
        eligible = sorted(
            (l for l in listings if l.get("d") and l["d"] < min_age_date),
            key=lambda l: l["d"],
        )[:LINK_CHECK_MAX_PER_RUN]
        eligible_ids = {listing_key(l) for l in eligible}
        print(f"Verifying {len(eligible)}/{len(listings)} listing links "
              f"(skipping listings <{LINK_CHECK_MIN_AGE_DAYS}d old, capped at {LINK_CHECK_MAX_PER_RUN}/run)...")
        verified = []
        for l in listings:
            if listing_key(l) not in eligible_ids:
                verified.append(l)
                continue
            try:
                ok = check_link(l["l"])
                if ok:
                    verified.append(l)
                else:
                    link_dead_count += 1
            except Exception as e:
                # Network error — keep the listing (assume transient)
                verified.append(l)
            time.sleep(0.3)  # rate limit
        listings = verified

    conn.close()

    LISTINGS_OUT.parent.mkdir(parents=True, exist_ok=True)
    LISTINGS_OUT.write_text(json.dumps(listings))
    total_dropped = expired_count + sold_removed_count + link_dead_count
    print(f"Exported {len(listings)} listings ({sum(1 for l in listings if l['p'])} priced)")
    print(f"Dropped {total_dropped}: {expired_count} expired, {sold_removed_count} sold, {link_dead_count} dead links")
    return listings


def check_link(url):
    """Verify a t.me/s/ link still resolves to a valid message.
    Returns True if the link works, False if it's dead."""
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; WatchIndexBot/2.0)",
            "Accept": "text/html",
        })
        resp = urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", errors="replace")

        # Dead messages on t.me/s/ redirect to the channel page without the message
        # Signs of a dead link:
        # 1. Page is too short (just channel header, no message)
        # 2. Contains specific error markers
        if len(html) < 5000:
            return False
        if "If you have" in html and "Telegram" in html and "tgme_widget_message" not in html:
            return False
        if "not found" in html.lower() and "tgme_widget_message" not in html:
            return False

        return "tgme_widget_message" in html
    except HTTPError as e:
        return False
    except URLError:
        raise  # transient network error — caller should retry
    except Exception:
        return True  # assume valid on unexpected errors


def recalc_index():
    """Recalculate the full SG-LWIX index and write index.json."""
    build_indices()
    print(f"Index recalculated -> {INDEX_OUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export watch listings + recalculate index")
    parser.add_argument("--max-age-days", type=int, default=14,
                        help="Drop listings older than N days (default: 14)")
    parser.add_argument("--link-check", action="store_true",
                        help="Verify each t.me link still resolves")
    parser.add_argument("--no-sold-trace", action="store_true",
                        help="Skip sold tracer cross-referencing")
    args = parser.parse_args()

    export_listings(max_age_days=args.max_age_days, link_check=args.link_check,
                    sold_trace=not args.no_sold_trace)
    recalc_index()
