#!/usr/bin/env python3
"""
SG Luxury Watch Index — Telegram Channel Scraper (Layer 1)
==========================================================

Scrapes public Telegram channels via t.me/s/ for pre-owned watch listings.
Pure HTTP + BeautifulSoup — no API key, no login, no Telethon.

Usage:
    python scraper.py                  # Incremental (new messages only)
    python scraper.py --full           # Full history (ignores state)
    python scraper.py --channel <h>    # Single channel only
    python scraper.py --list           # Print DB stats, no scraping
"""

import requests, sqlite3, json, sys, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "listings.db"
LOG_PATH = DATA_DIR / "scraper_log.json"
SGT = timezone(timedelta(hours=8))

CHANNELS = [
    {"handle": "watchdistrictsg",     "name": "Watch District SG",      "subs": 23000},
    {"handle": "ChuanwatchSG",        "name": "Chuan Watch SG",        "subs": 10000},
    {"handle": "watchexchangesg",     "name": "Watch Exchange SG",     "subs": 15000},
    {"handle": "pngwatchdealer",      "name": "PNG Watch Dealer",      "subs": 3000},
    {"handle": "watchbooksg",         "name": "Watch Book SG",         "subs": 4000},
    {"handle": "schonwatch",          "name": "Schon Watch",           "subs": 4000},
    {"handle": "watchcapital",        "name": "Watch Capital",         "subs": 1500},
    {"handle": "goldmanluxurysg",     "name": "Goldman Luxury SG",     "subs": 1000},
    {"handle": "thefinesttime",       "name": "The Finest Time",       "subs": 8561},
    {"handle": "watchplayboypteltd",  "name": "Watch Playboy",         "subs": 6649},
    {"handle": "sgwatchinsider",      "name": "SG Watch Insider",      "subs": 6529},
    {"handle": "HengWatch",           "name": "Heng Watch",            "subs": 4585},
    {"handle": "kbluxury",            "name": "KB Luxury",             "subs": 1968},
    {"handle": "tagtimesingapore",    "name": "Tag Time Singapore",    "subs": 625},
    {"handle": "watchhunts",          "name": "Watch Hunts",           "subs": 438},
]

DELAY = 1.0
MAX_PAGES = 100

# Incremental runs used to fetch exactly ONE page and keep only messages
# newer than latest_id. Any channel posting more than a page-worth between
# runs silently lost everything in between, permanently — which is why
# message-id coverage sits at 42% for a busy channel like watchexchangesg
# but 95% for a quiet one like ChuanwatchSG. Now we page backwards until we
# reach known territory, bounded so a long outage can't run away.
INCREMENTAL_MAX_PAGES = 25

# Always re-read the newest few pages even when nothing is new, so edits to
# recent posts (a price cut, or a listing edited to say SOLD) are noticed.
# Older posts are rarely edited, so this stays cheap.
EDIT_RECHECK_PAGES = 3

# --- Database ------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_handle TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    message_text TEXT,
    photos_count INTEGER DEFAULT 0,
    views INTEGER,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now')),
    reply_to_message_id INTEGER,
    first_seen_at TEXT,
    text_updated_at TEXT,
    edit_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(channel_handle, message_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_reply_to ON raw_messages(channel_handle, reply_to_message_id);
CREATE INDEX IF NOT EXISTS idx_raw_channel ON raw_messages(channel_handle);
CREATE INDEX IF NOT EXISTS idx_raw_posted ON raw_messages(posted_at);
"""

def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text())
    return {"runs": [], "channels": {}}

def save_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2, default=str))

# --- HTTP ----------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}

def fetch_page(handle, before_id=None):
    url = f"https://t.me/s/{handle}"
    if before_id:
        url += f"?before={before_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        print(f"  ⚠ {handle} (before={before_id}): {e}")
        return None

# --- Parsing -------------------------------------------------------------

def parse_page(html, channel_handle):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        msg_div = wrap.select_one(".tgme_widget_message")
        if not msg_div:
            continue
        data_post = msg_div.get("data-post", "")
        if not data_post:
            continue

        parts = data_post.split("/")
        if len(parts) != 2:
            continue
        msg_id = int(parts[1])

        # Timestamp
        time_el = msg_div.select_one("time")
        posted_at = time_el.get("datetime") if time_el else None

        # Reply link. Telegram renders the quoted parent as
        #   <a class="tgme_widget_message_reply" href="https://t.me/<ch>/<id>">
        # This is the only reliable tie between a bare "SOLD!" post and the
        # listing it refers to — 87% of SOLD messages carry one.
        reply_a = msg_div.select_one("a.tgme_widget_message_reply")
        reply_to = None
        if reply_a and reply_a.get("href"):
            m = re.search(r"/(\d+)\s*$", reply_a["href"].rstrip("/"))
            if m:
                reply_to = int(m.group(1))

        # Text. The quoted-parent preview inside that reply anchor ALSO carries
        # the .tgme_widget_message_text class and appears first in document
        # order, so the previous select_one() stored the PARENT's text as if it
        # were this message's — silently, for every reply ever scraped. Skip
        # the preview (it is marked js-message_reply_text) and take the
        # message's own text.
        text = None
        for t in msg_div.select(".tgme_widget_message_text"):
            if "js-message_reply_text" in (t.get("class") or []):
                continue
            text = t.get_text("\n", strip=True)
            break

        # Views
        views_el = msg_div.select_one(".tgme_widget_message_views")
        views = None
        if views_el:
            vtxt = views_el.get_text(strip=True).replace("K", "000").replace(".", "").replace(" ", "")
            try:
                views = int(vtxt)
            except ValueError:
                views = None

        # Photo count
        photos = len(msg_div.select(".tgme_widget_message_photo_wrap"))

        results.append({
            "channel_handle": channel_handle,
            "message_id": msg_id,
            "posted_at": posted_at,
            "message_text": text,
            "photos_count": photos,
            "views": views,
            "reply_to_message_id": reply_to,
        })

    return results


def get_next_before(html):
    """Extract the next `before` ID from the 'Load more' / prev link."""
    m = re.search(r'data-before="(\d+)"', html)
    if m:
        return int(m.group(1))
    # Fallback: link rel=prev
    m = re.search(r'<link rel="prev" href="/s/[^/]+/\?before=(\d+)"', html)
    return int(m.group(1)) if m else None


# --- Storage -------------------------------------------------------------

def save_messages(conn, messages):
    """Insert new messages; update ones we have already seen.

    Previously INSERT OR IGNORE: a message was captured once and never looked
    at again, so a dealer editing a post to say SOLD, or cutting the price,
    was invisible forever. Now an existing row is updated in place, and a
    change to its text bumps edit_count and stamps text_updated_at, turning
    edits into a usable signal.

    Note for whoever reads edit_count next: the first scrape after migration
    001 also CORRECTS text on reply messages (they previously stored the
    quoted parent's text by mistake). Those corrections look exactly like
    genuine edits at the row level, so treat edits stamped around the
    migration date as suspect rather than as real dealer activity.

    Returns (inserted, updated).
    """
    inserted = updated = skipped = 0
    now = datetime.now(SGT).isoformat()
    cur = conn.cursor()

    for m in messages:
        # Telegram serves a handful of posts with no <time> element. posted_at
        # is NOT NULL and every consumer date-filters on it, so these can never
        # be used. INSERT OR IGNORE used to swallow them silently; skip them
        # deliberately and report a count instead of emitting one exception per
        # message into the cron's Telegram report.
        if not m.get("posted_at"):
            skipped += 1
            continue
        try:
            row = cur.execute(
                "SELECT message_text, views, photos_count, reply_to_message_id "
                "FROM raw_messages WHERE channel_handle=? AND message_id=?",
                (m["channel_handle"], m["message_id"]),
            ).fetchone()

            if row is None:
                cur.execute(
                    """INSERT INTO raw_messages
                       (channel_handle, message_id, posted_at, message_text,
                        photos_count, views, reply_to_message_id, first_seen_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (m["channel_handle"], m["message_id"], m["posted_at"],
                     m["message_text"], m["photos_count"], m["views"],
                     m.get("reply_to_message_id"), now),
                )
                inserted += 1
                continue

            old_text, old_views, old_photos, old_reply = row
            new_reply = m.get("reply_to_message_id")
            text_changed = old_text != m["message_text"]
            # A re-read that lost the reply markup must never erase a link we
            # already captured, so only ever fill this in, never clear it.
            reply_gained = new_reply is not None and old_reply is None

            if not (text_changed or reply_gained
                    or old_views != m["views"] or old_photos != m["photos_count"]):
                continue

            cur.execute(
                """UPDATE raw_messages
                      SET message_text        = ?,
                          photos_count        = ?,
                          views               = ?,
                          reply_to_message_id = COALESCE(?, reply_to_message_id),
                          text_updated_at     = CASE WHEN ? THEN ? ELSE text_updated_at END,
                          edit_count          = edit_count + CASE WHEN ? THEN 1 ELSE 0 END
                    WHERE channel_handle = ? AND message_id = ?""",
                (m["message_text"], m["photos_count"], m["views"], new_reply,
                 1 if text_changed else 0, now,
                 1 if text_changed else 0,
                 m["channel_handle"], m["message_id"]),
            )
            updated += 1
        except Exception as e:
            print(f"  \u2717 DB error: {e}")

    conn.commit()
    if skipped:
        print(f"  \u2139 skipped {skipped} message(s) with no timestamp (unusable: every consumer date-filters)")
    return inserted, updated


# --- Main Scrape Loop ----------------------------------------------------

def scrape_channel(conn, ch, full=False, log_state=None):
    handle = ch["handle"]
    ch_state = (log_state or {}).get("channels", {}).get(handle, {})

    if not full and ch_state.get("latest_id"):
        # Incremental. This used to fetch exactly one page and keep only
        # messages newer than latest_id, so anything a channel posted beyond
        # a single page between runs was lost permanently. Page backwards
        # until we reach known territory instead, and always re-read the
        # newest EDIT_RECHECK_PAGES so edits to recent posts are caught.
        latest_known = ch_state["latest_id"]
        total_new = total_upd = 0
        pages = 0
        before = None
        newest_seen = latest_known

        while pages < INCREMENTAL_MAX_PAGES:
            html = fetch_page(handle, before)
            if not html:
                break
            messages = parse_page(html, handle)
            if not messages:
                break

            page_min = min(m["message_id"] for m in messages)
            page_max = max(m["message_id"] for m in messages)
            newest_seen = max(newest_seen, page_max)

            # On the first few pages save everything, so already-known rows
            # get re-read and edits surface. Deeper pages only carry genuinely
            # new messages, since we are just closing a gap there.
            to_save = messages if pages < EDIT_RECHECK_PAGES else [
                m for m in messages if m["message_id"] > latest_known
            ]
            ins, upd = save_messages(conn, to_save)
            total_new += ins
            total_upd += upd
            pages += 1

            # Reached messages we already had: the gap is closed.
            if page_min <= latest_known:
                break

            before = get_next_before(html)
            if not before:
                break
            time.sleep(DELAY)

        if pages >= INCREMENTAL_MAX_PAGES:
            print(f"  \u26a0 {handle}: hit INCREMENTAL_MAX_PAGES ({INCREMENTAL_MAX_PAGES}) "
                  f"without reaching known messages — a gap may remain, run --full")

        if total_new or total_upd:
            log_state["channels"][handle] = {
                **ch_state,
                "latest_id": newest_seen,
                "last_scrape": datetime.now(SGT).isoformat(),
                "total_scraped": ch_state.get("total_scraped", 0) + total_new,
            }
        if total_upd:
            print(f"  \u21bb {total_upd} existing message(s) updated (edits/views)")
        return total_new

    # Full / first run: paginate backwards
    html = fetch_page(handle)
    if not html:
        return 0

    total_saved = 0
    pages = 0
    seen = set()
    before_id = None

    while html and pages < MAX_PAGES:
        messages = parse_page(html, handle)
        new_msgs = [m for m in messages if m["message_id"] not in seen]
        for m in new_msgs:
            seen.add(m["message_id"])

        ins, upd = save_messages(conn, new_msgs)
        saved = ins
        total_saved += ins

        if not new_msgs:
            break

        # Track oldest ID for pagination
        oldest_id = min(m["message_id"] for m in new_msgs)
        before_id = get_next_before(html)
        pages += 1

        if saved > 0:
            datestr = new_msgs[0]["posted_at"][:10] if new_msgs[0].get("posted_at") else "?"
            print(f"  p{pages:2d}  {oldest_id:6d}  saved={saved:3d}  [{datestr}]")

        if not before_id:
            break

        time.sleep(DELAY)
        html = fetch_page(handle, before_id)

    # Update state
    if total_saved > 0:
        latest = max(seen)
        oldest_seen = min(seen)
        log_state["channels"][handle] = {
            "latest_id": latest,
            "oldest_id": oldest_seen,
            "last_scrape": datetime.now(SGT).isoformat(),
            "total_scraped": ch_state.get("total_scraped", 0) + total_saved,
        }

    return total_saved


# --- Stats ---------------------------------------------------------------

def print_stats(conn):
    cur = conn.execute("""
        SELECT channel_handle,
               COUNT(*) AS total,
               MIN(posted_at) AS earliest,
               MAX(posted_at) AS latest
        FROM raw_messages
        GROUP BY channel_handle
        ORDER BY total DESC
    """)
    rows = cur.fetchall()
    if not rows:
        print("No messages in DB yet.")
        return
    print(f"{'Channel':<22} {'Msgs':>6}  {'Earliest':<12}  {'Latest':<12}")
    print("-" * 62)
    for handle, total, earliest, latest in rows:
        e = earliest[:10] if earliest else "?"
        l = latest[:10] if latest else "?"
        print(f"{handle:<22} {total:>6}  {e:<12}  {l:<12}")


# --- CLI -----------------------------------------------------------------

def main():
    full = "--full" in sys.argv
    single = None
    if "--channel" in sys.argv:
        idx = sys.argv.index("--channel")
        if idx + 1 < len(sys.argv):
            single = sys.argv[idx + 1]

    if "--list" in sys.argv:
        conn = get_db()
        print_stats(conn)
        conn.close()
        return

    channels = CHANNELS
    if single:
        channels = [c for c in CHANNELS if c["handle"] == single]
        if not channels:
            print(f"Unknown channel: {single}")
            print(f"Known: {', '.join(c['handle'] for c in CHANNELS)}")
            sys.exit(1)

    conn = get_db()
    log = load_log()

    run_start = datetime.now(SGT)
    print(f"\n🔄 Scraper run — {run_start.strftime('%Y-%m-%d %H:%M SGT')}")
    print(f"   Mode: {'FULL' if full else 'incremental'}")
    print(f"   Channels: {len(channels)}\n")

    grand_total = 0
    for ch in channels:
        handle = ch["handle"]
        name = ch["name"]
        print(f"📡 {name} (@{handle})")
        saved = scrape_channel(conn, ch, full=full, log_state=log)
        print(f"   → {saved} new messages saved\n")
        grand_total += saved
        time.sleep(DELAY)

    # Log this run
    run_duration = (datetime.now(SGT) - run_start).total_seconds()
    log["runs"].append({
        "started": run_start.isoformat(),
        "duration_s": run_duration,
        "mode": "full" if full else "incremental",
        "channels": len(channels),
        "total_saved": grand_total,
    })
    save_log(log)

    conn.close()
    print(f"✅ Done. {grand_total} total new messages across {len(channels)} channels.")

if __name__ == "__main__":
    main()
