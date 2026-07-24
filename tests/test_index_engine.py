"""Regression tests for index/index_engine.py's outlier flag."""
from statistics import median

from index.index_engine import find_price_outliers, extract_brand, PRESTIGE


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
