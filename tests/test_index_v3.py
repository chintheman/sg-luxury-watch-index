"""v3 index maths — the properties that must hold on every build.

These assert against the real generated index.json rather than fixtures,
because the failures they guard against were all invisible in unit terms:
each one produced a plausible number that was simply wrong.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))

INDEX = ROOT / "data" / "index.json"
pytestmark = pytest.mark.skipif(not INDEX.exists(), reason="no built index")


@pytest.fixture(scope="module")
def idx():
    return json.loads(INDEX.read_text())


# ── Version and parameters ─────────────────────────────────────────────────

def test_index_reports_v3(idx):
    assert idx["meta"]["version"].startswith("3.")


def test_prestige_is_no_longer_used_for_weighting():
    """A hand-assigned brand ranking must not drive a price index."""
    import index.index_engine as ie
    src = (ROOT / "index" / "index_engine.py").read_text()
    weight_block = src[src.index("Phase 3: Brand weights"):src.index("Phase 4:")]
    assert "PRESTIGE" not in weight_block


# ── Retail measures are gone, not merely fixed ─────────────────────────────
# v3 first repaired the inverted retail comparison, then removed it: it rested
# on ~300 hand-entered, undated, unsourced list prices where 62% of lookups
# fell through to a brand-wide median. This asserts it cannot creep back in
# without someone deliberately re-adding it.

def test_no_retail_measures_are_published(idx):
    for key in ("retail_composite", "retail_spread"):
        assert key not in idx, f"{key} is back in the index output"


def test_no_retail_wording_in_insights(idx):
    for name, text in (idx.get("insights") or {}).items():
        assert "retail" not in text.lower(), f"insight {name!r} mentions retail: {text}"


# ── The insight sign bug ───────────────────────────────────────────────────

def test_insight_direction_matches_the_actual_move(idx):
    text = idx["insights"].get("composite", "")
    pct = idx["composite"]["change_1d_pct"]
    if not text or pct is None:
        pytest.skip("no insight this build")
    if pct > 0:
        assert "moved up" in text
    elif pct < 0:
        assert "moved down" in text


def test_leaders_move_with_the_index_not_against_it(idx):
    """v2 credited the brands that went UP on days the index went DOWN."""
    contribs = idx.get("brand_contributions") or []
    pct = idx["composite"]["change_1d_pct"]
    text = idx["insights"].get("composite", "")
    if not contribs or not pct or "led by" not in text:
        pytest.skip("nothing to check this build")
    leaders = text.split("led by")[1].split(".")[0]
    named = [c for c in contribs if c["brand"] in leaders]
    assert named, "the named leaders should appear in the contributions"
    for c in named:
        assert (c["contribution"] > 0) == (pct > 0), (
            f"{c['brand']} is named as leading a {'rise' if pct > 0 else 'fall'} "
            f"but contributed {c['contribution']:+f}"
        )


# ── Contribution reconciliation ────────────────────────────────────────────

def test_contributions_reconcile_to_the_actual_move(idx):
    """v2's contributions summed to about a third of the move."""
    chg = idx["composite"]["change_1d"]
    total = idx.get("contributions_total")
    comp = idx.get("composition_effect")
    if chg is None or total is None or comp is None:
        pytest.skip("no contribution data this build")
    assert abs((total + comp) - chg) < 5e-4, (
        f"per-brand terms {total} + composition {comp} != change {chg}"
    )


def test_published_contribution_list_is_a_labelled_subset(idx):
    """The visible list is truncated; contributions_total carries the full sum."""
    contribs = idx.get("brand_contributions") or []
    assert len(contribs) <= 8
    assert "contributions_total" in idx


# ── Window and freshness ───────────────────────────────────────────────────

def test_ninety_day_change_actually_resolves(idx):
    """v2 computed this from a 180-day lookback, so it was permanently null."""
    series = [p for p in idx["composite"]["series"] if p["value"] is not None]
    if len(series) < 90:
        pytest.skip("series too short to expect a 90-day change")
    assert idx["composite"]["change_90d_pct"] is not None


def test_staleness_is_reported(idx):
    c = idx["composite"]
    assert "stale" in c and "days_since_fresh" in c
    assert all("stale" in p for p in c["series"])


def test_index_is_not_mostly_noise(idx):
    """v2 moved 13.6% on an average day with 76% of days over 5%."""
    fresh = [p["value"] for p in idx["composite"]["series"]
             if p["value"] is not None and not p.get("stale")]
    if len(fresh) < 10:
        pytest.skip("not enough fresh points")
    moves = [abs(fresh[i] - fresh[i - 1]) / fresh[i - 1] * 100
             for i in range(1, len(fresh))]
    mean_move = sum(moves) / len(moves)
    over5 = 100 * sum(1 for m in moves if m > 5) / len(moves)
    assert mean_move < 8, f"mean daily move {mean_move:.1f}% — too noisy to publish"
    assert over5 < 40, f"{over5:.0f}% of days move >5% — too noisy to publish"


# ── Sanity ─────────────────────────────────────────────────────────────────

def test_no_single_brand_dominates_the_weighting(idx):
    w = idx["brand_weights"]
    top = max(w.values())
    assert top < 0.40, f"top brand carries {top:.0%} of the index"


def test_baseline_covers_the_major_brands(idx):
    """Anchoring the baseline on calendar time silently dropped AP and Hublot."""
    counts = idx["brand_counts"]
    majors = [b for b, n in counts.items() if n >= 50]
    weighted = set(idx["brand_weights"])
    for b in majors:
        assert b in weighted, f"{b} has {counts[b]} listings but no weight"


# ── Matched-model (v3.1) ───────────────────────────────────────────────────

def test_records_are_matched_at_model_level():
    """A brand's median moves when the MIX of references changes, not only
    when prices change. Rolex read -25% at brand level while its actual
    references were flat to up; matched, the same comparison reads +13%."""
    src = (ROOT / "index" / "index_engine.py").read_text()
    assert "UNIT_REF_MIN_LISTINGS" in src
    assert "def brand_ratios_on" in src
    # the composite must be built from matched ratios, not raw brand medians
    loop = src[src.index("for date in dates_sorted:"):src.index("# Availability — raw same-day count")]
    assert "brand_ratios_on(date)" in loop


def test_matched_index_is_quieter_than_brand_level(idx):
    """Removing mix noise should reduce volatility, not add to it."""
    fresh = [p["value"] for p in idx["composite"]["series"]
             if p["value"] is not None and not p.get("stale")]
    if len(fresh) < 10:
        pytest.skip("not enough fresh points")
    moves = [abs(fresh[i] - fresh[i - 1]) / fresh[i - 1] * 100 for i in range(1, len(fresh))]
    assert sum(moves) / len(moves) < 3.5


def test_no_year_is_parsed_as_a_price():
    """Article slugs like 'price-increase-2025' were read as $2,025."""
    from filter import extract_price
    assert extract_price("rolex-retail-price-increase-2025-confirmed") is None
    assert extract_price("https://x.com/news/rolex-price-2026-daytona/") is None
    # a genuine price in that numeric range must still parse
    assert extract_price("SGD $2,025") == 2025
