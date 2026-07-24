"""Regression tests for sold_tracer.py, targeting the bug found in the audit:
trace_sold_messages() matched candidates against a stale on-disk snapshot
(previous run's listings.json) instead of the listings actually about to be
published, so genuine sold-item matches were silently discarded and a
listing scraped-and-sold within the same run was never caught at all.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from sold_tracer import trace_sold_messages

SGT = timezone(timedelta(hours=8))


def _make_db(tmp_path, rows):
    """rows: list of (channel_handle, message_id, posted_at, message_text)"""
    db_path = tmp_path / "listings.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE raw_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_handle TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            posted_at TEXT NOT NULL,
            message_text TEXT,
            photos_count INTEGER DEFAULT 0,
            views INTEGER,
            scraped_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(channel_handle, message_id)
        )"""
    )
    conn.executemany(
        "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


def _iso(days_ago):
    return (datetime.now(SGT) - timedelta(days=days_ago)).isoformat()


def test_item_number_match_removes_the_correct_listing(tmp_path):
    listing_text = "Rolex Submariner 126610LN\nItem no: GML3589\nPrice: $16,800"
    sold_text = "SOLD - Item GML3589 thanks all!"

    db_path = _make_db(
        tmp_path,
        [
            ("watchexchangesg", 100, _iso(5), listing_text),
            ("watchexchangesg", 101, _iso(2), sold_text),
        ],
    )
    candidates = [
        {"c": "watchexchangesg", "m": 100, "b": "Rolex", "p": 16800, "d": _iso(5)[:10]},
    ]

    result = trace_sold_messages(str(db_path), listings=candidates)

    assert result["total_removed"] == 1
    assert result["removed_ids"] == ["watchexchangesg-100"]
    assert result["strategies"]["item_number"] == 1


def test_scraped_and_sold_in_the_same_run_is_still_caught(tmp_path):
    # Regression case for the original bug: previously trace_sold_messages()
    # only checked the previous run's on-disk listings.json, so a listing
    # that's brand new *this* run (never yet written to disk) could never be
    # matched against its own same-run SOLD post. Passing `listings=` (the
    # in-memory candidate set for this run) must close that gap.
    listing_text = "Omega Speedmaster\nItem no: GML9001\nPrice: $9,200"
    sold_text = "SOLD - Item GML9001"

    db_path = _make_db(
        tmp_path,
        [
            ("sgdealer", 200, _iso(1), listing_text),
            ("sgdealer", 201, _iso(0), sold_text),
        ],
    )
    candidates = [
        {"c": "sgdealer", "m": 200, "b": "Omega", "p": 9200, "d": _iso(1)[:10]},
    ]

    result = trace_sold_messages(str(db_path), listings=candidates)

    assert result["total_removed"] == 1
    assert "sgdealer-200" in result["removed_ids"]


def test_matches_outside_the_published_candidate_set_are_not_counted_as_removed(tmp_path):
    # A brand+price match against a message that ISN'T one of this run's
    # published candidates (e.g. it already expired) must not be reported as
    # removed — this is the scoping fix: the match pool is restricted to
    # `listings`, not every non-SOLD message in the lookback window.
    old_listing_text = "Cartier Santos\nPrice: $8,000"
    sold_text = "SOLD Cartier Santos $8,000 thank you"

    db_path = _make_db(
        tmp_path,
        [
            ("olddealer", 300, _iso(40), old_listing_text),
            ("olddealer", 301, _iso(35), sold_text),
        ],
    )
    # This run's candidates do NOT include olddealer-300 (e.g. it expired).
    candidates = []

    result = trace_sold_messages(str(db_path), listings=candidates)

    assert result["total_removed"] == 0
    assert result["removed_ids"] == []


def test_removed_json_written_to_disk(tmp_path, monkeypatch):
    import sold_tracer

    out_path = tmp_path / "removed.json"
    monkeypatch.setattr(sold_tracer, "REMOVED_OUT", out_path)

    listing_text = "Tudor Black Bay\nItem no: GML5000\nPrice: $4,500"
    sold_text = "SOLD - Item GML5000"
    db_path = _make_db(
        tmp_path,
        [
            ("dealerx", 400, _iso(3), listing_text),
            ("dealerx", 401, _iso(1), sold_text),
        ],
    )
    candidates = [{"c": "dealerx", "m": 400, "b": "Tudor", "p": 4500, "d": _iso(3)[:10]}]

    trace_sold_messages(str(db_path), listings=candidates)

    assert out_path.exists()
