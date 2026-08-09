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
