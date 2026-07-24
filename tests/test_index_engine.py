"""Regression tests for index/index_engine.py's outlier flag."""
import sqlite3
from datetime import datetime, timedelta, timezone
from statistics import median

import index.index_engine as ie
from index.index_engine import find_price_outliers, extract_brand, PRESTIGE, fill_series, MIN_PER_BRAND

SGT = timezone(timedelta(hours=8))


def test_flags_price_far_below_brand_baseline():
    daily_by_brand = {"2026-07-01": {"Rolex": [16000, 16500, 500]}}
    baseline_median = {"Rolex": 16200}

    outliers = find_price_outliers(daily_by_brand, baseline_median)

    assert len(outliers) == 1
    assert outliers[0] == {"date": "2026-07-01", "brand": "Rolex", "price": 500, "baseline": 16200}


def test_flags_price_far_above_brand_baseline():
    daily_by_brand = {"2026-07-01": {"Omega": [5000, 5100, 500000]}}
    baseline_median = {"Omega": 5100}

    outliers = find_price_outliers(daily_by_brand, baseline_median)

    assert len(outliers) == 1
    assert outliers[0]["price"] == 500000


def test_does_not_flag_normal_price_spread():
    daily_by_brand = {"2026-07-01": {"Rolex": [15800, 16200, 16700, 17000]}}
    baseline_median = {"Rolex": 16200}

    assert find_price_outliers(daily_by_brand, baseline_median) == []


def test_never_drops_anything_only_flags():
    # The point of the fix: outliers are surfaced for review, the median
    # itself is computed over the full, un-filtered price list.
    prices = [16000, 16500, 500]
    daily_by_brand = {"2026-07-01": {"Rolex": prices}}
    baseline_median = {"Rolex": 16200}

    outliers = find_price_outliers(daily_by_brand, baseline_median)

    assert len(outliers) == 1
    assert median(prices) == 16000  # unaffected by the flag


def test_skips_brands_with_no_baseline():
    daily_by_brand = {"2026-07-01": {"NewBrand": [100]}}
    assert find_price_outliers(daily_by_brand, {}) == []


def test_newly_added_brands_resolve_and_have_prestige_weights():
    # Brands added to close the "brand: null" gap found in the audit must be
    # both matchable and present in PRESTIGE (missing entries default to a
    # placeholder weight of 3 rather than erroring, but should be curated).
    for text, brand in [
        ("Roger Dubuis Excalibur 42mm", "Roger Dubuis"),
        ("Louis Moinet Memoris", "Louis Moinet"),
        ("Glashutte Original Senator", "Glashutte Original"),
        ("Chanel J12 Automatic", "Chanel"),
    ]:
        assert extract_brand(text) == brand
        assert brand in PRESTIGE


# ── MIN_PER_BRAND / fill_series staleness ───────────────────────────────
# A single listing determining a whole brand-day was the mechanism behind
# confirmed ±100% single-brand-day swings (see the comment above
# MIN_PER_BRAND in index_engine.py for the full trade-off analysis).

def test_min_per_brand_requires_at_least_three_samples():
    assert MIN_PER_BRAND == 3


def test_fill_series_marks_carried_forward_points_as_stale():
    series = [
        {"date": "2026-07-01", "value": 1.10},
        {"date": "2026-07-02", "value": None},
        {"date": "2026-07-03", "value": None},
        {"date": "2026-07-04", "value": 1.15},
    ]

    filled = fill_series(series)

    assert [pt["value"] for pt in filled] == [1.10, 1.10, 1.10, 1.15]
    assert [pt["stale"] for pt in filled] == [False, True, True, False]


def test_fill_series_leading_gap_is_not_marked_stale():
    # No prior value exists yet to carry forward — this is "no data", not
    # a carried-forward repeat, so it shouldn't be flagged stale.
    series = [{"date": "2026-07-01", "value": None}, {"date": "2026-07-02", "value": 1.0}]

    filled = fill_series(series)

    assert filled[0]["value"] is None
    assert filled[0]["stale"] is False
    assert filled[1]["stale"] is False


# ── Batch-post splitting wired into build_indices() itself ─────────────────
# The audit found that export_pipeline.py splitting batch "[WATCH DEALS...]"
# posts into per-item listings didn't help the index: index_engine.py parses
# raw_messages independently and never imported parser/batch.py, so the
# index and the published listings.json ran on divergently-filtered data.

def _iso(days_ago):
    return (datetime.now(SGT) - timedelta(days=days_ago)).isoformat()


def _seed_baseline(conn, brand, price, next_id, n=4, start_days_ago=60):
    """Insert enough same-brand listings, spread across distinct days, to
    satisfy MIN_BASELINE_SAMPLES/MIN_PER_BRAND for one brand."""
    rows = []
    for i in range(n):
        rows.append((
            "dealerx", next_id + i, _iso(start_days_ago - i),
            f"{brand} Model Ref{i} Price: SGD ${price + i}",
        ))
    conn.executemany(
        "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text) VALUES (?, ?, ?, ?)",
        rows,
    )
    return next_id + n


def test_build_indices_splits_batch_posts(tmp_path, monkeypatch):
    db_path = tmp_path / "listings.db"
    out_path = tmp_path / "index.json"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE raw_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_handle TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            posted_at TEXT NOT NULL,
            message_text TEXT,
            UNIQUE(channel_handle, message_id)
        )"""
    )

    next_id = 1
    next_id = _seed_baseline(conn, "Rolex", 16000, next_id)
    next_id = _seed_baseline(conn, "Omega", 5000, next_id)
    next_id = _seed_baseline(conn, "Cartier", 8000, next_id)

    batch_text = (
        "[WATCH DEALS 01/01]\n"
        "✅\n(AVAILABLE)\n✅\n(1) Rolex Datejust\nRef123\nPrice: SGD $16,500\n"
        "✅\n(AVAILABLE)\n✅\n(2) Rolex Explorer\nRef456\nPrice: SGD $16,700\n"
        "❌\nSOLD\n❌\n(3) Omega Speedmaster\nRef789\nPrice: SGD $5,200\n"
    )
    conn.execute(
        "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text) VALUES (?, ?, ?, ?)",
        ("sgwatchinsider", next_id, _iso(30), batch_text),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ie, "DB", db_path)
    monkeypatch.setattr(ie, "OUT", out_path)
    ie.build_indices()

    import json
    output = json.loads(out_path.read_text())
    # 4+4+4 baseline listings + 2 AVAILABLE batch sub-items = 14, NOT 15
    # (whole message as one record) and NOT 12 (batch dropped entirely).
    assert output["meta"]["total_records"] == 14


def test_first_computed_differs_from_anchor_date_when_undersubscribed(tmp_path, monkeypatch):
    # meta.first_computed must reflect the real first composite value, not
    # just restate anchor_date as if a value existed there.
    db_path = tmp_path / "listings.db"
    out_path = tmp_path / "index.json"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE raw_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_handle TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            posted_at TEXT NOT NULL,
            message_text TEXT,
            UNIQUE(channel_handle, message_id)
        )"""
    )
    next_id = 1
    next_id = _seed_baseline(conn, "Rolex", 16000, next_id)
    next_id = _seed_baseline(conn, "Omega", 5000, next_id)
    next_id = _seed_baseline(conn, "Cartier", 8000, next_id)
    conn.commit()
    conn.close()

    monkeypatch.setattr(ie, "DB", db_path)
    monkeypatch.setattr(ie, "OUT", out_path)
    ie.build_indices()

    import json
    output = json.loads(out_path.read_text())
    fc = output["meta"]["first_computed"]
    assert fc is not None
    assert fc["value"] is not None
    assert fc["brands_tracked"] >= 3
