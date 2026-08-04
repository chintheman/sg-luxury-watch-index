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


# ── No retail price table ───────────────────────────────────────────────
# The hand-entered RETAIL_PRICES dict and its lookup helpers were deleted in
# v3. Nothing they fed was ever rendered, and the fallback path silently
# compared a watch to the median of every price recorded for its brand.

def test_retail_price_table_is_gone():
    for name in ("RETAIL_PRICES", "get_retail_price", "get_retail_price_smart"):
        assert not hasattr(ie, name), f"{name} is back in index_engine"


# ── Baseline outlier exclusion ──────────────────────────────────────────
# A baseline is computed once from a brand's first ~90 days and every later
# day is measured against it forever, unlike the daily flag which is
# log-only. A single bad scrape in that window used to be permanently
# baked into the baseline with no filtering at all.
from index.index_engine import compute_baseline_median


def test_compute_baseline_median_excludes_outlier():
    # Median of all 5 (with the $500 outlier) is 16000; median of the 4
    # real prices alone is 16050 — different, proving exclusion happened.
    prices = [16000, 16100, 15900, 16200, 500]

    value, excluded = compute_baseline_median(prices)

    assert excluded == 1
    assert value == 16050


def test_compute_baseline_median_no_outliers_unaffected():
    prices = [16000, 16100, 15900, 16200]

    value, excluded = compute_baseline_median(prices)

    assert excluded == 0
    assert value == median(prices)


def test_compute_baseline_median_falls_back_when_filtering_leaves_too_few():
    # Only 3 samples, one is an outlier — excluding it would drop below
    # MIN_BASELINE_SAMPLES, so fall back to the raw (unfiltered) median
    # rather than refusing to baseline the brand at all.
    prices = [16000, 16100, 500]

    value, excluded = compute_baseline_median(prices, min_samples=3)

    assert excluded == 0
    assert value == median(prices)


def test_compute_baseline_median_returns_none_below_min_samples():
    assert compute_baseline_median([16000, 16100], min_samples=3) is None


# ── NEW/Pre-Owned condition sub-index fragility (originally-flagged issue) ─
# Only ~14% of listings are Brand New, so a same-day-only pool (what the
# code used before) meant a single listing could set — or wildly swing —
# the day's value. AGENTS.md documented "14-day window + min 2 per brand"
# as the fix path but it was never implemented until now.

def test_new_subindex_uses_wide_window_not_single_day(tmp_path, monkeypatch):
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
    next_id = _seed_baseline(conn, "Rolex", 16000, next_id, n=6, start_days_ago=60)
    next_id = _seed_baseline(conn, "Omega", 5000, next_id, n=6, start_days_ago=60)
    next_id = _seed_baseline(conn, "Cartier", 8000, next_id, n=6, start_days_ago=60)

    # Two Brand New Rolexes spread across different days, and two Brand New
    # Omegas on different days again — all within the same 14-day span, but
    # never 2+ of the same brand on the SAME day. Under the old same-day-only
    # logic this would never produce a value at all (MIN_COND_PER_BRAND=2
    # could never be met in a single day); pooled over 14 days it should.
    new_rows = [
        ("dealerx", next_id, _iso(12), "Rolex Model BNIB Price: SGD $17000"),
        ("dealerx", next_id + 1, _iso(9), "Rolex Model BNIB Price: SGD $17100"),
        ("dealerx", next_id + 2, _iso(7), "Omega Model BNIB Price: SGD $5500"),
        ("dealerx", next_id + 3, _iso(3), "Omega Model BNIB Price: SGD $5600"),
    ]
    conn.executemany(
        "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text) VALUES (?, ?, ?, ?)",
        new_rows,
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ie, "DB", db_path)
    monkeypatch.setattr(ie, "OUT", out_path)
    ie.build_indices()

    import json
    output = json.loads(out_path.read_text())
    new_series = output["condition_indices"]["new"]["series"]
    computed = [pt for pt in new_series if pt["value"] is not None and not pt.get("stale")]
    assert len(computed) >= 1


def test_new_subindex_requires_min_cond_brands():
    assert ie.MIN_COND_BRANDS >= 2
    assert ie.COND_WINDOW_DAYS >= 7


# ── Availability score: rolling ceiling, not a fixed all-time max ──────────
# The channel roster isn't constant over the history — some channels went
# dormant, others came online partway through. A fixed all-time max ceiling
# mechanically deflates every era except whichever one happened to have the
# most channels scraping, and silently re-inflates every time coverage
# grows. A trailing rolling max instead measures "vs. the recent norm."

def test_availability_uses_rolling_not_alltime_max(tmp_path, monkeypatch):
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
    # A big burst of listings 100 days ago (a one-off historical peak, well
    # outside AVAILABILITY_ROLLING_DAYS=60), then a much smaller but
    # consistent trickle in the recent past.
    burst_rows = [
        ("dealerx", next_id + i, _iso(100), f"Rolex Model{i} Price: SGD ${16000+i}")
        for i in range(20)
    ]
    conn.executemany(
        "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text) VALUES (?, ?, ?, ?)",
        burst_rows,
    )
    next_id += 20
    next_id = _seed_baseline(conn, "Rolex", 16000, next_id, n=3, start_days_ago=10)
    next_id = _seed_baseline(conn, "Omega", 5000, next_id, n=3, start_days_ago=10)
    next_id = _seed_baseline(conn, "Cartier", 8000, next_id, n=3, start_days_ago=10)
    conn.commit()
    conn.close()

    monkeypatch.setattr(ie, "DB", db_path)
    monkeypatch.setattr(ie, "OUT", out_path)
    ie.build_indices()

    import json
    output = json.loads(out_path.read_text())
    avail = output["availability"]["series"]
    recent = [pt for pt in avail if pt["date"] >= (datetime.now(SGT) - timedelta(days=10)).strftime("%Y-%m-%d")]
    assert recent
    # With a fixed all-time max (20-listing burst day), recent days with
    # only 1-3 listings would round to ~5-15/100. With a rolling ceiling
    # that's aged out the burst, recent days should score much higher.
    assert any(pt["value"] >= 50 for pt in recent)
