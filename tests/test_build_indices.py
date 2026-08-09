"""Behavioural tests for index_engine.build_indices() — the function that
computes the published index.

Why a dedicated file: build_indices() is ~570 lines and, before these tests,
was exercised only incidentally. A mutation run over index/index_engine.py
scored 0.46, and 719 of the 728 surviving mutants were inside this one
function — its arithmetic and its thresholds were almost entirely unpinned.
These tests target that arithmetic directly, with hand-computable expected
values rather than smoke assertions.

Nothing here depends on a built index or a scraped database. Every test
constructs its own sqlite corpus, so none of them skip.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import index.index_engine as ie

SGT = timezone(timedelta(hours=8))

SCHEMA = """CREATE TABLE raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_handle TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    message_text TEXT,
    UNIQUE(channel_handle, message_id)
)"""


def _iso(days_ago):
    return (datetime.now(SGT) - timedelta(days=days_ago)).isoformat()


class Corpus:
    """Builds a raw_messages database one listing at a time.

    `listing()` text is deliberately of the form "<Brand> Model Ref<n>", which
    parser.filter.extract_model resolves to (None, None). That keeps every
    record on the brand-level matching tier, so a test that is about weighting
    or thresholds is not silently also testing reference grouping. Tests that
    DO care about tiering pass their own text.
    """

    def __init__(self):
        self.rows = []

    def listing(self, brand, price, days_ago, *, text=None, channel="dealerx", suffix=""):
        body = text if text is not None else f"{brand} Model Ref{len(self.rows)}{suffix} Price: SGD ${price}"
        self.rows.append((channel, len(self.rows) + 1, _iso(days_ago), body))
        return self

    def raw(self, text, days_ago, channel="dealerx"):
        self.rows.append((channel, len(self.rows) + 1, _iso(days_ago), text))
        return self

    def at(self, posted_at, text, channel="dealerx"):
        self.rows.append((channel, len(self.rows) + 1, posted_at, text))
        return self

    def spread(self, brand, prices, days_ago_start, *, step=1):
        """One listing per day, walking forwards in time from days_ago_start."""
        for i, p in enumerate(prices):
            self.listing(brand, p, days_ago_start - i * step)
        return self

    def build(self, tmp_path, monkeypatch, name="c"):
        db = tmp_path / f"{name}.db"
        out = tmp_path / f"{name}.json"
        conn = sqlite3.connect(str(db))
        conn.execute(SCHEMA)
        conn.executemany(
            "INSERT INTO raw_messages (channel_handle, message_id, posted_at, message_text)"
            " VALUES (?, ?, ?, ?)",
            self.rows,
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(ie, "DB", db)
        monkeypatch.setattr(ie, "OUT", out)
        return out


def run(corpus, tmp_path, monkeypatch, name="c"):
    out = corpus.build(tmp_path, monkeypatch, name)
    ie.build_indices()
    return json.loads(out.read_text())


def three_brands_at_baseline(days=(9, 8, 7, 6)):
    """Three brands, four listings each, all inside one WINDOW_DAYS pool.

    Because every unit's full price history fits in both the baseline sample
    and the final window, each ratio is exactly 1.0 and so is the composite.
    """
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i, d in enumerate(days):
            c.listing(brand, base + i, d)
    return c


# ── The crash ─────────────────────────────────────────────────────────────
# brand_contribs is empty whenever there is only one date, or when the last
# two dates share no qualifying brand. The else-branch that handles that case
# referenced `prev_day_idx`, a name that exists nowhere in the module, so the
# whole build died with NameError instead of publishing an index.

def test_single_date_corpus_still_produces_an_index(tmp_path, monkeypatch):
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 5)

    output = run(c, tmp_path, monkeypatch)

    assert output["composite"]["current"] is not None
    assert output["brand_contributions"] == []
    # One date means there is no previous day, so the move is zero rather than
    # an artefact of comparing the series against itself.
    assert output["composite"]["change_1d"] == 0
    assert output["composite"]["change_1d_pct"] == 0


def test_single_date_corpus_still_writes_a_composite_insight(tmp_path, monkeypatch):
    # The final print reads insights["composite"] unconditionally, so a build
    # that produces no insight crashes on the way out even after the index is
    # computed.
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 5)

    output = run(c, tmp_path, monkeypatch)

    assert "composite" in output["insights"]


# ── Price admission window: 500 <= price <= 500000 ────────────────────────

@pytest.mark.parametrize("price,admitted", [
    (499, False),
    (500, True),
    (500000, True),
    (500001, False),
])
def test_price_admission_boundaries(price, admitted, tmp_path, monkeypatch):
    c = three_brands_at_baseline()
    before = len(c.rows)
    c.listing("Tudor", price, 5)

    output = run(c, tmp_path, monkeypatch)

    expected = before + (1 if admitted else 0)
    assert output["meta"]["total_records"] == expected


# ── Date floor: listings before 2025-01-01 are dropped ────────────────────

def test_listings_dated_before_2025_are_excluded(tmp_path, monkeypatch):
    c = three_brands_at_baseline()
    before = len(c.rows)
    c.at("2024-12-31T10:00:00+08:00", "Tudor Model RefA Price: SGD $4000")

    output = run(c, tmp_path, monkeypatch)

    assert output["meta"]["total_records"] == before


def test_listings_dated_on_the_2025_boundary_are_included(tmp_path, monkeypatch):
    c = three_brands_at_baseline()
    before = len(c.rows)
    c.at("2025-01-01T10:00:00+08:00", "Tudor Model RefA Price: SGD $4000")

    output = run(c, tmp_path, monkeypatch)

    assert output["meta"]["total_records"] == before + 1


# ── Brand weighting: sqrt of volume share, renormalised ───────────────────

def test_brand_weights_are_normalised_sqrt_of_volume_share(tmp_path, monkeypatch):
    # Volumes 9 / 4 / 1 are chosen so the arithmetic lands on exact decimals:
    # sqrt of shares 9/14, 4/14, 1/14 are in the ratio 3 : 2 : 1, so after
    # renormalisation the weights are exactly 0.5, 1/3 and 1/6. Any change to
    # the exponent, either denominator, or the renormalisation moves these.
    c = Corpus()
    for i in range(9):
        c.listing("Rolex", 16000 + i, 9)
    for i in range(4):
        c.listing("Omega", 5000 + i, 9)
    c.listing("Cartier", 8000, 9)

    output = run(c, tmp_path, monkeypatch)

    assert output["brand_weights"] == {"Rolex": 0.5, "Omega": 0.3333, "Cartier": 0.1667}


def test_brand_weights_sum_to_one(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert sum(output["brand_weights"].values()) == pytest.approx(1.0, abs=5e-4)


def test_brand_counts_report_deduplicated_volume(tmp_path, monkeypatch):
    c = Corpus()
    for i in range(5):
        c.listing("Rolex", 16000 + i, 9)
    for i in range(4):
        c.listing("Omega", 5000 + i, 9)
    for i in range(3):
        c.listing("Cartier", 8000 + i, 9)

    output = run(c, tmp_path, monkeypatch)

    assert output["brand_counts"] == {"Rolex": 5, "Omega": 4, "Cartier": 3}


# ── The composite itself ──────────────────────────────────────────────────

def test_composite_is_exactly_one_when_every_unit_sits_at_its_baseline(tmp_path, monkeypatch):
    # Each unit's window at the final date is its entire price history, and so
    # is its baseline sample, so every ratio is 1.0 by construction. This is
    # the single strongest constraint on the composite's arithmetic: any
    # perturbation of the median, the ratio, the weighting or the division
    # moves the answer off 1.0.
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert output["composite"]["current"] == 1.0


def test_composite_rises_by_the_ratio_when_recent_prices_exceed_the_baseline(tmp_path, monkeypatch):
    # 30 distinct dates. The first 10 supply exactly BASELINE_SAMPLE_TARGET
    # listings per brand (3 per day), so the baseline is the cheap era alone.
    # WINDOW_DAYS pools the last 21 *dates*, which is the expensive era plus
    # one cheap day — enough that the pooled median is the expensive price.
    # Ratio 20000/16000 = 1.25 for every brand, so the composite is 1.25.
    c = Corpus()
    cheap = [15990, 16000, 16010]
    dear = [19990, 20000, 20010]
    for day_index in range(30):
        days_ago = 40 - day_index
        prices = cheap if day_index < 10 else dear
        for brand, delta in (("Rolex", 0), ("Omega", 0), ("Cartier", 0)):
            for p in prices:
                c.listing(brand, p + delta, days_ago)

    output = run(c, tmp_path, monkeypatch)

    assert output["composite"]["current"] == 1.25


def test_composite_is_withheld_below_min_brands_per_composite(tmp_path, monkeypatch):
    # Two qualifying brands is one short of MIN_BRANDS_PER_COMPOSITE.
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000)):
        for i in range(4):
            c.listing(brand, base + i, 9 - i)

    output = run(c, tmp_path, monkeypatch)

    fresh = [pt for pt in output["composite"]["series"] if not pt["stale"] and pt["value"] is not None]
    assert fresh == []


def test_composite_qualifies_at_exactly_min_brands_per_composite(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    fresh = [pt for pt in output["composite"]["series"] if not pt["stale"] and pt["value"] is not None]
    assert fresh != []
    assert all(pt["brands_tracked"] >= ie.MIN_BRANDS_PER_COMPOSITE for pt in fresh)


def test_a_unit_below_min_per_brand_listings_does_not_qualify(tmp_path, monkeypatch):
    # Tudor gets two listings — below MIN_PER_BRAND — so it must not appear in
    # brands_tracked even though it has enough samples to be in the corpus.
    c = three_brands_at_baseline()
    c.listing("Tudor", 4000, 9)
    c.listing("Tudor", 4001, 8)

    output = run(c, tmp_path, monkeypatch)

    last = output["composite"]["series"][-1]
    assert last["brands_tracked"] == 3


# ── Availability ──────────────────────────────────────────────────────────

def test_availability_is_the_days_share_of_the_rolling_ceiling(tmp_path, monkeypatch):
    # 8 listings on the first day, 4 on the second: the ceiling is 8 and the
    # second day scores 50. Both days are inside AVAILABILITY_ROLLING_DAYS.
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(3):
            c.listing(brand, base + i, 9)
    for i in range(2):
        c.listing("Rolex", 16100 + i, 8)
    for i in range(2):
        c.listing("Omega", 5100 + i, 8)

    output = run(c, tmp_path, monkeypatch)
    series = {pt["date"]: pt["value"] for pt in output["availability"]["series"]}
    dates = sorted(series)

    assert series[dates[0]] == 100        # 9 of a ceiling of 9
    assert series[dates[1]] == 44         # round(4 / 9 * 100)


def test_availability_ceiling_is_trailing_not_all_time(tmp_path, monkeypatch):
    # A 20-listing burst well outside AVAILABILITY_ROLLING_DAYS must not hold
    # the ceiling down for the recent era.
    c = Corpus()
    for i in range(20):
        c.listing("Rolex", 16000 + i, 200)
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(3):
            c.listing(brand, base + 100 + i, 5)

    output = run(c, tmp_path, monkeypatch)

    assert output["availability"]["current"] == 100


# ── Change reconciliation (C3: contradictions) ────────────────────────────

def test_contributions_plus_composition_reconcile_with_the_actual_move(tmp_path, monkeypatch):
    # The documented invariant: per-brand terms account for brands present on
    # both days, and everything else — set membership and the shifting weight
    # denominator — lands in composition_effect. Together they must equal the
    # move the series actually printed.
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
        for i in range(4):
            c.listing(brand, base + 500 + i, 8)

    output = run(c, tmp_path, monkeypatch)

    reconciled = output["contributions_total"] + output["composition_effect"]
    assert reconciled == pytest.approx(output["composite"]["change_1d"], abs=1e-3)


def test_contributions_are_ordered_by_absolute_size(tmp_path, monkeypatch):
    c = Corpus()
    for brand, base, bump in (("Rolex", 16000, 3000), ("Omega", 5000, 100), ("Cartier", 8000, 40)):
        for i in range(4):
            c.listing(brand, base + i, 9)
        for i in range(4):
            c.listing(brand, base + bump + i, 8)

    output = run(c, tmp_path, monkeypatch)
    sizes = [abs(entry["contribution"]) for entry in output["brand_contributions"]]

    assert sizes == sorted(sizes, reverse=True)


# ── Outliers are flagged, never dropped ───────────────────────────────────

def test_outlier_listing_is_flagged_and_still_counted(tmp_path, monkeypatch):
    c = three_brands_at_baseline()
    c.listing("Rolex", 700, 6)   # far below Rolex's ~16000 baseline

    output = run(c, tmp_path, monkeypatch)

    assert output["price_outlier_count"] >= 1
    assert any(o["brand"] == "Rolex" and o["price"] == 700 for o in output["price_outliers"])
    assert output["meta"]["total_records"] == 13    # kept, not dropped


def test_a_corpus_with_no_outliers_reports_none(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert output["price_outlier_count"] == 0
    assert output["price_outliers"] == []


# ── Matching tiers ────────────────────────────────────────────────────────

def test_tier_thresholds_stay_where_the_methodology_says(tmp_path, monkeypatch):
    # These two numbers decide whether a listing is matched by reference, by
    # model, or only by brand — the whole point of v3's matched-model design.
    assert ie.UNIT_REF_MIN_LISTINGS == 8
    assert ie.UNIT_MODEL_MIN_LISTINGS == 3


def test_units_aggregate_into_their_brand(tmp_path, monkeypatch):
    # Two references of the same brand, each at UNIT_REF_MIN_LISTINGS, must
    # count as ONE brand in brands_tracked — not two.
    #
    # Each listing goes on its own channel. dedupe clusters by
    # (channel, brand, reference) within a 10% price band, so eight same-priced
    # Submariners from one dealer are correctly treated as one repeatedly
    # posted watch; eight dealers each holding one is the case we want here.
    c = Corpus()
    for i in range(8):
        c.raw(f"Rolex Submariner 116610LN Price: SGD ${16000 + i}", 9, channel=f"dealer{i}")
    for i in range(8):
        c.raw(f"Rolex Explorer 214270 Price: SGD ${9000 + i}", 9, channel=f"dealer{i}")
    for brand, base in (("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)

    output = run(c, tmp_path, monkeypatch)

    assert output["composite"]["series"][-1]["brands_tracked"] == 3


def test_same_dealer_reposting_one_reference_collapses_to_a_single_watch(tmp_path, monkeypatch):
    # The counterpart to the test above, and the reason it needs distinct
    # channels: volume drives brand weight, so counting one watch eight times
    # would bake the error into that brand's baseline.
    c = three_brands_at_baseline()
    for i in range(8):
        c.raw(f"Tudor Black Bay 79230N Price: SGD ${4000 + i}", 9, channel="dealerx")

    output = run(c, tmp_path, monkeypatch)

    assert output["brand_counts"]["Tudor"] == 1


# ── Condition sub-indices ─────────────────────────────────────────────────

def test_condition_spread_is_new_minus_preowned(tmp_path, monkeypatch):
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
        for i in range(2):
            c.raw(f"{brand} Model BNIB Price: SGD ${base + 1000 + i}", 8)
        for i in range(2):
            c.raw(f"{brand} Model Preowned Price: SGD ${base - 500 + i}", 8)

    output = run(c, tmp_path, monkeypatch)
    new = output["condition_indices"]["new"]["current"]
    pre = output["condition_indices"]["preowned"]["current"]

    assert new is not None and pre is not None
    assert output["condition_indices"]["spread"] == pytest.approx(round(new - pre, 4))
    assert new > pre        # unworn pieces ask more than pre-owned here


# ── Degenerate corpora ────────────────────────────────────────────────────

def test_a_corpus_with_no_priced_records_writes_nothing(tmp_path, monkeypatch):
    c = Corpus()
    c.raw("just some chatter, no watch and no price", 5)
    out = c.build(tmp_path, monkeypatch)

    ie.build_indices()

    assert not out.exists()


def test_records_below_the_price_floor_alone_write_nothing(tmp_path, monkeypatch):
    c = Corpus()
    for i in range(4):
        c.listing("Rolex", 100 + i, 5)
    out = c.build(tmp_path, monkeypatch)

    ie.build_indices()

    assert not out.exists()


# ── Series shape and metadata ─────────────────────────────────────────────

def test_every_listing_date_appears_exactly_once_in_the_series(tmp_path, monkeypatch):
    c = three_brands_at_baseline(days=(9, 8, 7, 6))

    output = run(c, tmp_path, monkeypatch)
    dates = [pt["date"] for pt in output["composite"]["series"]]

    assert dates == sorted(set(dates))
    assert len(dates) == 4


def test_meta_reports_the_deduplicated_record_count_and_brand_total(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert output["meta"]["total_records"] == 12
    assert output["meta"]["tracked_brands"] == 3
    assert output["meta"]["version"] == ie.INDEX_VERSION
    assert output["meta"]["base_value"] == ie.ANCHOR_VALUE


def test_days_since_fresh_counts_trailing_carried_forward_points(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    series = output["composite"]["series"]
    trailing = 0
    for pt in reversed(series):
        if not pt["stale"]:
            break
        trailing += 1
    assert output["composite"]["days_since_fresh"] == trailing


def test_anchor_date_is_the_first_date_half_the_baselined_brands_have_appeared(tmp_path, monkeypatch):
    # Rolex and Omega both appear on the first date; Cartier arrives later.
    # Two of three baselined brands is already over half, so the anchor is the
    # first date, not Cartier's.
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
    for i in range(4):
        c.listing("Cartier", 8000 + i, 7)

    output = run(c, tmp_path, monkeypatch)
    first_date = output["composite"]["series"][0]["date"]

    assert output["meta"]["anchor_date"] == first_date


# ── Change horizons (val_at_date) ─────────────────────────────────────────

def flat_market_over(days_ago_list):
    """Three brands, three listings per date, every price cycling around the
    same median. Every unit's window median equals its baseline on every date,
    so the composite is 1.0 throughout and every horizon change is zero."""
    c = Corpus()
    for d in days_ago_list:
        for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
            for delta in (-10, 0, 10):
                c.listing(brand, base + delta, d)
    return c


def test_a_flat_market_reports_zero_change_over_every_horizon(tmp_path, monkeypatch):
    # 16 dates spanning 120 days, so the 7-, 30- and 90-day lookbacks all
    # resolve to a real earlier point rather than falling off the series.
    c = flat_market_over(list(range(120, -1, -8)))

    output = run(c, tmp_path, monkeypatch)
    comp = output["composite"]

    assert comp["current"] == 1.0
    for horizon in ("change_1d", "change_7d", "change_30d", "change_90d"):
        assert comp[horizon] == 0, f"{horizon} should be flat"
    for horizon in ("change_1d_pct", "change_7d_pct", "change_30d_pct", "change_90d_pct"):
        assert comp[horizon] == 0, f"{horizon} should be flat"


def test_horizons_beyond_the_series_report_none(tmp_path, monkeypatch):
    # Every point is inside the last week, so even the 7-day lookback has no
    # earlier point to land on and must report None rather than reusing the
    # first value it can find.
    c = flat_market_over([5, 4, 3, 2])

    output = run(c, tmp_path, monkeypatch)
    comp = output["composite"]

    assert comp["change_7d"] is None
    assert comp["change_30d"] is None
    assert comp["change_90d"] is None


def test_days_since_fresh_is_zero_when_the_final_day_computed(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert output["composite"]["stale"] is False
    assert output["composite"]["days_since_fresh"] == 0


# ── Brand sub-indices ─────────────────────────────────────────────────────

def test_brand_subindices_sit_at_one_when_each_brand_is_at_its_baseline(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)
    subs = output["brand_subindices"]

    assert set(subs) == {"Rolex", "Omega", "Cartier"}
    for brand, sub in subs.items():
        assert sub["current"] == 1.0, brand


def test_brand_subindices_are_capped_at_the_top_five_by_volume(tmp_path, monkeypatch):
    # Seven brands, descending volume. Only the five largest get a sub-index.
    c = Corpus()
    volumes = [("Rolex", 16000, 10), ("Omega", 5000, 9), ("Cartier", 8000, 8),
               ("Tudor", 4000, 7), ("Breitling", 6000, 6), ("Panerai", 7000, 5),
               ("Hublot", 12000, 4)]
    for brand, base, n in volumes:
        for i in range(n):
            c.listing(brand, base + i, 9)

    output = run(c, tmp_path, monkeypatch)

    assert set(output["brand_subindices"]) == {"Rolex", "Omega", "Cartier", "Tudor", "Breitling"}


def test_brand_subindices_skip_a_brand_with_no_baseline(tmp_path, monkeypatch):
    # Tudor has two listings — below MIN_BASELINE_SAMPLES — so it never gets a
    # baseline, and a sub-index measured against nothing must not be published
    # even though its volume puts it inside the top five.
    c = three_brands_at_baseline()
    c.listing("Tudor", 4000, 9)
    c.listing("Tudor", 4001, 8)

    output = run(c, tmp_path, monkeypatch)

    assert "Tudor" not in output["brand_subindices"]


# ── Published-list truncation ─────────────────────────────────────────────

def test_brand_contributions_are_truncated_to_eight(tmp_path, monkeypatch):
    brands = [("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000), ("Tudor", 4000),
              ("Breitling", 6000), ("Panerai", 7000), ("Hublot", 12000),
              ("Zenith", 5500), ("Chopard", 9000), ("Longines", 2000)]
    c = Corpus()
    for i, (brand, base) in enumerate(brands):
        for j in range(4):
            c.listing(brand, base + j, 9)
        for j in range(4):
            c.listing(brand, base + 200 + i * 10 + j, 8)

    output = run(c, tmp_path, monkeypatch)

    assert len(output["brand_contributions"]) == 8
    # The full total still reflects every brand, not just the published eight.
    assert output["contributions_total"] != sum(
        e["contribution"] for e in output["brand_contributions"]
    )


def test_price_outliers_are_truncated_to_two_hundred_but_counted_in_full(tmp_path, monkeypatch):
    c = Corpus()
    # 40 honest Rolex listings first, so the first-30 baseline sample is clean.
    for i in range(40):
        c.listing("Rolex", 16000 + i, 30 - (i % 20))
    for brand, base in (("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
    # 201 junk prices, all far below Rolex's baseline, all on one later day.
    for i in range(201):
        c.listing("Rolex", 700 + i, 5)

    output = run(c, tmp_path, monkeypatch)

    assert output["price_outlier_count"] == 201
    assert len(output["price_outliers"]) == 200


# ── Insights ──────────────────────────────────────────────────────────────

def test_condition_insight_quotes_the_spread(tmp_path, monkeypatch):
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
        for i in range(2):
            c.raw(f"{brand} Model BNIB Price: SGD ${base + 1000 + i}", 8)
        for i in range(2):
            c.raw(f"{brand} Model Preowned Price: SGD ${base - 500 + i}", 8)

    output = run(c, tmp_path, monkeypatch)

    spread = output["condition_indices"]["spread"]
    assert f"{spread:+.4f}" in output["insights"]["condition"]


def test_availability_insight_quotes_the_score(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    score = output["availability"]["current"]
    assert f"Availability Score: {score}/100" in output["insights"]["availability"]


def test_no_condition_insight_when_the_spread_cannot_be_computed(tmp_path, monkeypatch):
    # Every listing is condition-unknown, so neither sub-index has a value and
    # there is no spread to describe.
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert output["condition_indices"]["spread"] is None
    assert "condition" not in output["insights"]


def test_condition_index_ignores_brands_that_have_no_baseline(tmp_path, monkeypatch):
    # Metamorphic: adding Brand New listings for a brand that never earned a
    # baseline must leave the NEW sub-index exactly where it was.
    def corpus():
        c = Corpus()
        for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
            for i in range(4):
                c.listing(brand, base + i, 9)
            for i in range(2):
                c.raw(f"{brand} Model BNIB Price: SGD ${base + 1000 + i}", 8)
        return c

    without = run(corpus(), tmp_path, monkeypatch, name="without")

    c = corpus()
    for i in range(2):
        c.raw(f"Tudor Model BNIB Price: SGD ${40000 + i}", 8)
    with_unbaselined = run(c, tmp_path, monkeypatch, name="with")

    assert with_unbaselined["condition_indices"]["new"]["current"] == \
        without["condition_indices"]["new"]["current"]


# ── The operator-facing summary ───────────────────────────────────────────
# build_indices() prints a summary block that is the only feedback a scheduled
# run gives. It is part of the contract with whoever reads the job log.

def test_printed_summary_reports_the_headline_number(tmp_path, monkeypatch, capsys):
    run(three_brands_at_baseline(), tmp_path, monkeypatch)

    out = capsys.readouterr().out

    assert "SG-LWIX: 1.0000" in out
    assert "Brands baselined: 3/3" in out


def test_printed_summary_says_so_when_there_is_no_qualifying_day(tmp_path, monkeypatch, capsys):
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000)):
        for i in range(4):
            c.listing(brand, base + i, 9 - i)

    run(c, tmp_path, monkeypatch)
    out = capsys.readouterr().out

    assert "N/A (no qualifying day)" in out
    assert "no day has reached 3 qualifying brands" in out


# ── Window pooling is visible in the published counts ─────────────────────

def test_total_listings_reports_the_pooled_window_not_the_single_day(tmp_path, monkeypatch):
    # One listing per brand per date, four dates. The first point sees only its
    # own day; the last sees the whole pool.
    c = Corpus()
    for d in (9, 8, 7, 6):
        for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
            c.listing(brand, base + d, d)

    output = run(c, tmp_path, monkeypatch)
    series = output["composite"]["series"]

    assert series[0]["total_listings"] == 3
    assert series[-1]["total_listings"] == 12


# ── Dead code stays dead ──────────────────────────────────────────────────

def test_unused_trend_variables_are_not_reintroduced():
    # trend_30d / day_direction / week_direction were computed and never read.
    # A dead assignment cannot be covered by any test, so it registers as a
    # permanently surviving mutant and quietly caps the file's score.
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(ie.build_indices)))
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    read = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    for name in ("trend_30d", "day_direction", "week_direction"):
        assert name not in assigned, f"{name} is back and is still unused"
    # And nothing else has quietly become dead in the same way.
    assert (assigned - read - {"_"}) == set(), "dead assignment(s) in build_indices"


# ── Rounding precision ────────────────────────────────────────────────────
# Every published number goes through round(x, 4) — or round(x, 2) for
# percentages. Tests that land on tidy values like 1.0 or 1.25 cannot detect a
# change to that precision, so this one is deliberately untidy.

def two_era_corpus(dear_prices):
    """Ten cheap dates supplying exactly BASELINE_SAMPLE_TARGET listings per
    brand, then twenty dearer ones. The baseline is the cheap era; the pooled
    window at the final date is the dear era."""
    c = Corpus()
    cheap = [15990, 16000, 16010]
    for day_index in range(30):
        days_ago = 40 - day_index
        prices = cheap if day_index < 10 else dear_prices
        for brand in ("Rolex", "Omega", "Cartier"):
            for p in prices:
                c.listing(brand, p, days_ago)
    return c


def test_composite_is_rounded_to_four_decimals(tmp_path, monkeypatch):
    # Window median 20003 over a baseline of 16000 gives 1.2501875 — a ratio
    # that survives rounding to five places but not to four.
    output = run(two_era_corpus([19993, 20003, 20013]), tmp_path, monkeypatch)

    assert output["composite"]["current"] == 1.2502


def test_no_published_series_value_exceeds_four_decimals(tmp_path, monkeypatch):
    output = run(two_era_corpus([19993, 20003, 20013]), tmp_path, monkeypatch)

    series = (output["composite"]["series"]
              + output["condition_indices"]["preowned"]["series"]
              + output["condition_indices"]["new"]["series"])
    for pt in series:
        if pt["value"] is None or isinstance(pt["value"], int):
            continue
        decimals = str(pt["value"]).split(".")[-1]
        assert len(decimals) <= 4, f"{pt} carries more precision than it earned"


# ── The published key contract ────────────────────────────────────────────
# web/ reads this JSON. A renamed key is a broken page, and the renames are
# exactly what a mutation run produces, so name every key that ships.

def test_meta_publishes_its_full_identity_block(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)
    meta = output["meta"]

    assert meta["name"] == "SG Luxury Watch Index"
    assert meta["symbol"] == "SG-LWIX"
    assert meta["updated"]
    assert set(meta) == {
        "name", "symbol", "version", "methodology", "base_value", "anchor_date",
        "first_computed", "updated", "total_records", "tracked_brands",
    }


def test_top_level_shape_is_exactly_what_the_site_consumes(tmp_path, monkeypatch):
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)

    assert set(output) == {
        "meta", "composite", "condition_indices", "availability",
        "brand_subindices", "brand_weights", "brand_counts",
        "brand_contributions", "contributions_total", "composition_effect",
        "insights", "price_outliers", "price_outlier_count",
    }
    assert set(output["composite"]) == {
        "current", "stale", "days_since_fresh", "change_1d", "change_1d_pct",
        "change_7d", "change_7d_pct", "change_30d", "change_30d_pct",
        "change_90d", "change_90d_pct", "series",
    }
    assert set(output["condition_indices"]) == {"preowned", "new", "spread"}


def test_methodology_quotes_the_parameters_it_actually_ran_with(tmp_path, monkeypatch):
    # The methodology paragraph is published on the site as a factual claim
    # about how the number was produced. If a constant changes and the prose
    # does not, the site starts lying — so the prose interpolates the
    # constants and this checks the interpolation really happened.
    output = run(three_brands_at_baseline(), tmp_path, monkeypatch)
    text = output["meta"]["methodology"]

    assert f"{ie.WINDOW_DAYS}-day rolling window" in text
    assert f"at least {ie.MIN_PER_BRAND} listings per brand" in text
    assert str(ie.ANCHOR_VALUE) in text


# ── Contribution decomposition, in detail ─────────────────────────────────

def test_each_contribution_reports_the_window_listing_count(tmp_path, monkeypatch):
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
        for i in range(4):
            c.listing(brand, base + 500 + i, 8)

    output = run(c, tmp_path, monkeypatch)

    for entry in output["brand_contributions"]:
        # Eight listings per brand, all inside the final pooled window.
        assert entry["listings"] == 8


def test_composition_effect_is_zero_when_the_brand_set_is_unchanged(tmp_path, monkeypatch):
    # Same three brands qualifying on both of the last two days and identical
    # weights, so nothing is left over for the composition term to explain.
    c = Corpus()
    for brand, base in (("Rolex", 16000), ("Omega", 5000), ("Cartier", 8000)):
        for i in range(4):
            c.listing(brand, base + i, 9)
        for i in range(4):
            c.listing(brand, base + i, 8)

    output = run(c, tmp_path, monkeypatch)

    assert output["composition_effect"] == pytest.approx(0.0, abs=1e-6)
