"""Sold detection and derived signals.

The old tracer matched SOLD messages to listings by brand, model and price
and found nothing, ever — 6,782 SOLD messages, 0 removals. Sold posts are
bare "SOLD!" replies with no brand and no price, so there was nothing to
match on. These tests pin the replacement: dealer-authored reply links, and
edits to the listing itself.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))

import sold_tracer as st  # noqa: E402

SCHEMA = """
CREATE TABLE raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_handle TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    message_text TEXT,
    photos_count INTEGER DEFAULT 0,
    views INTEGER,
    scraped_at TEXT,
    reply_to_message_id INTEGER,
    first_seen_at TEXT,
    text_updated_at TEXT,
    edit_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(channel_handle, message_id)
);
"""

LISTING = "Rolex Submariner 126610LN Price: SGD $17,700 BNIB full set"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setattr(st, "REMOVED_OUT", tmp_path / "removed.json")
    return path


def _insert(db, rows):
    conn = sqlite3.connect(str(db))
    conn.executemany(
        "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text, "
        "reply_to_message_id, edit_count, text_updated_at, first_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _listing_dict(mid):
    return {"c": "dealer", "m": mid, "b": "Rolex", "p": 17700, "d": "2026-07-01"}


# ── Reply links ────────────────────────────────────────────────────────────

def test_a_sold_reply_marks_its_listing_sold(db):
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("dealer", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 100, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 1
    assert out["strategies"]["reply_link"] == 1


def test_time_to_sell_is_measured(db):
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("dealer", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 100, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["time_to_sell"]["median_days"] == 4


def test_a_chain_of_sold_replies_is_followed_to_the_listing(db):
    """Dealers reply SOLD to their own previous SOLD — 2,597 of 2,713 links."""
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("dealer", 150, "2026-07-03T10:00:00+08:00", "SOLD!", 100, 0, None, None),
        ("dealer", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 150, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 1


def test_a_chain_that_never_reaches_a_listing_removes_nothing(db):
    _insert(db, [
        ("dealer", 150, "2026-07-03T10:00:00+08:00", "SOLD!", None, 0, None, None),
        ("dealer", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 150, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(150)])
    assert out["total_removed"] == 0


def test_a_reply_to_another_dealers_listing_is_not_matched(db):
    """Message ids are only unique within a channel."""
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("other", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 100, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 0


def test_the_old_brand_and_price_heuristics_are_gone():
    src = (ROOT / "sold_tracer.py").read_text()
    assert "extract_brand" not in src
    assert "abs(s_price - c_price)" not in src


# ── Edits ──────────────────────────────────────────────────────────────────

def test_a_listing_edited_to_say_sold_is_caught(db):
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING + " SOLD", None, 1,
         "2026-09-01T10:00:00+08:00", "2026-07-01T10:00:00+08:00"),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 1
    assert out["strategies"]["edited_to_sold"] == 1


def test_migration_era_edits_are_ignored(db):
    """The first post-migration scrape corrected reply text on 2,235 rows.
    Those corrections look exactly like dealer edits and must not be trusted."""
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING + " SOLD", None, 1,
         "2026-08-03T15:20:00+08:00", "2026-07-01T10:00:00+08:00"),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 0, "a migration artefact must not read as a sale"


def test_an_unedited_listing_is_not_marked_sold(db):
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 0


# ── Properties carried over from the previous tracer's tests ───────────────
# The item-number strategy those tests covered is gone by design; these three
# behaviours still matter and are re-asserted against the new implementation.

def test_scraped_and_sold_in_the_same_run_is_still_caught(db):
    """The tracer must read this run's in-memory candidates, not the previous
    run's listings.json, or a listing scraped and sold between runs is missed."""
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("dealer", 200, "2026-07-01T18:00:00+08:00", "SOLD!", 100, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    assert out["total_removed"] == 1


def test_a_sale_outside_the_published_set_is_not_reported_as_removed(db):
    """Only listings about to be published can be removed from it."""
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("dealer", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 100, 0, None, None),
    ])
    out = st.trace_sold_messages(db_path=db, listings=[_listing_dict(999)])
    assert out["total_removed"] == 0
    assert out["removed_ids"] == []


def test_removed_json_is_written_to_disk(db, tmp_path):
    _insert(db, [
        ("dealer", 100, "2026-07-01T10:00:00+08:00", LISTING, None, 0, None, None),
        ("dealer", 200, "2026-07-05T10:00:00+08:00", "SOLD!", 100, 0, None, None),
    ])
    st.trace_sold_messages(db_path=db, listings=[_listing_dict(100)])
    written = json.loads((tmp_path / "removed.json").read_text())
    assert written["total_removed"] == 1
    assert "time_to_sell" in written


# ── Signals ────────────────────────────────────────────────────────────────

SIGNALS = ROOT / "data" / "signals.json"


@pytest.mark.skipif(not SIGNALS.exists(), reason="signals not built")
def test_signals_carry_their_own_caveat():
    """These numbers are a sample of confirmed sales, not a sell-through rate."""
    sig = json.loads(SIGNALS.read_text())
    assert "caveat" in sig and len(sig["caveat"]) > 50


@pytest.mark.skipif(not SIGNALS.exists(), reason="signals not built")
def test_attention_is_indexed_not_raw_views():
    """Raw view counts measure channel size, not interest in the watch."""
    sig = json.loads(SIGNALS.read_text())
    rel = sig["attention"]["relative_attention_by_brand"]
    assert rel, "expected per-channel-indexed attention"
    assert all(0.05 < v < 20 for v in rel.values()), (
        f"values look like raw views rather than an index: {rel}"
    )


@pytest.mark.skipif(not SIGNALS.exists(), reason="signals not built")
def test_inventory_inflation_is_reported(sig=None):
    sig = json.loads(SIGNALS.read_text())
    inv = sig["inventory"]
    assert inv["unique_watches"] <= inv["raw_listings"]
    assert inv["apparent_inflation_pct"] >= 0
