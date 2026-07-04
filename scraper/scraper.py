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
    UNIQUE(channel_handle, message_id)
);
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

        # Text
        text_div = msg_div.select_one(".tgme_widget_message_text")
        text = text_div.get_text("\n", strip=True) if text_div else None

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
    saved = 0
    cur = conn.cursor()
    for m in messages:
        try:
            cur.execute(
                """INSERT OR IGNORE INTO raw_messages
                   (channel_handle, message_id, posted_at, message_text,
                    photos_count, views)
                   VALUES (?,?,?,?,?,?)""",
                (m["channel_handle"], m["message_id"], m["posted_at"],
                 m["message_text"], m["photos_count"], m["views"]),
            )
            if cur.rowcount > 0:
                saved += 1
        except Exception as e:
            print(f"  ✗ DB error: {e}")
    conn.commit()
    return saved


# --- Main Scrape Loop ----------------------------------------------------

def scrape_channel(conn, ch, full=False, log_state=None):
    handle = ch["handle"]
    ch_state = (log_state or {}).get("channels", {}).get(handle, {})

    if not full and ch_state.get("latest_id"):
        # Incremental: start from latest known, go forward
        latest_known = ch_state["latest_id"]
        # Get newest page to find messages > latest_known
        html = fetch_page(handle)
        if not html:
            return 0
        messages = parse_page(html, handle)
        new_msgs = [m for m in messages if m["message_id"] > latest_known]
        saved = save_messages(conn, new_msgs)
        if saved:
            newest = max(m["message_id"] for m in new_msgs)
            log_state["channels"][handle] = {
                "latest_id": newest,
                "last_scrape": datetime.now(SGT).isoformat(),
                "total_scraped": ch_state.get("total_scraped", 0) + saved,
            }
        return saved

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

        saved = save_messages(conn, new_msgs)
        total_saved += saved

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
