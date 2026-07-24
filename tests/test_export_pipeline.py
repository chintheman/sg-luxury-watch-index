"""Regression tests for index/export_pipeline.py's link-check scoping.

Link-checking is a real HTTP request per listing. Checking every listing on
every run would cost minutes of runtime and hammer Telegram's public web
view twice a day. These tests verify the cost-mitigation without making any
real network calls: check_link() is monkeypatched out entirely.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import index.export_pipeline as ep

SGT = timezone(timedelta(hours=8))

LISTING_TEXT = "Rolex Submariner 126610LN Price: SGD $16,800 BNIB full set"


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


def _run(tmp_path, rows, monkeypatch, checked_urls, dead_urls=frozenset()):
    db_path = _make_db(tmp_path, rows)
    monkeypatch.setattr(ep, "DB", db_path)
    monkeypatch.setattr(ep, "LISTINGS_OUT", tmp_path / "listings.json")
    monkeypatch.setattr(ep, "INDEX_OUT", tmp_path / "index.json")
    monkeypatch.setattr(ep, "REMOVED_IN", tmp_path / "removed.json")
    monkeypatch.setattr(ep.time, "sleep", lambda *_: None)

    def fake_check_link(url):
        checked_urls.append(url)
        return url not in dead_urls

    monkeypatch.setattr(ep, "check_link", fake_check_link)
    return ep.export_listings(link_check=True, sold_trace=False)


def test_listings_newer_than_min_age_are_never_checked(tmp_path, monkeypatch):
    rows = [
        ("dealerx", 1, _iso(0), LISTING_TEXT),   # today — too new
        ("dealerx", 2, _iso(1), LISTING_TEXT),   # 1 day — too new
    ]
    checked = []
    listings = _run(tmp_path, rows, monkeypatch, checked)

    assert checked == []
    assert len(listings) == 2  # both kept, untouched


def test_listings_at_or_past_min_age_are_checked(tmp_path, monkeypatch):
    rows = [("dealerx", 1, _iso(3), LISTING_TEXT)]  # 3 days — eligible
    checked = []
    listings = _run(tmp_path, rows, monkeypatch, checked)

    assert len(checked) == 1
    assert len(listings) == 1


def test_dead_link_is_dropped(tmp_path, monkeypatch):
    rows = [("dealerx", 1, _iso(5), LISTING_TEXT)]
    checked = []
    listings = _run(tmp_path, rows, monkeypatch, checked, dead_urls={
        "https://t.me/s/dealerx/1"
    })

    assert len(checked) == 1
    assert listings == []


def test_per_run_cap_prioritizes_oldest_eligible_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "LINK_CHECK_MAX_PER_RUN", 2)
    rows = [
        ("dealerx", 1, _iso(10), LISTING_TEXT),  # oldest — must be checked
        ("dealerx", 2, _iso(8), LISTING_TEXT),   # 2nd oldest — must be checked
        ("dealerx", 3, _iso(5), LISTING_TEXT),   # newer eligible — should be skipped this run
    ]
    checked = []
    listings = _run(tmp_path, rows, monkeypatch, checked)

    assert len(checked) == 2
    assert "https://t.me/s/dealerx/1" in checked
    assert "https://t.me/s/dealerx/2" in checked
    assert "https://t.me/s/dealerx/3" not in checked
    assert len(listings) == 3  # the skipped one is kept, not dropped
