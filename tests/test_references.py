"""Per-reference price cards — the properties a published card must hold.

A card makes a direct claim to a buyer ("fair asking is X to Y"), so the
failure mode that matters is not a crash but a plausible, confidently-rendered,
wrong number. These assert against the real generated references.json for the
same reason the v3 index tests do.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "parser"))
sys.path.insert(0, str(ROOT / "index"))

REFS = ROOT / "data" / "references.json"


@pytest.fixture(scope="module")
def refs():
    if not REFS.exists():
        pytest.skip("no built references.json")
    return json.loads(REFS.read_text())


@pytest.fixture(scope="module")
def cards(refs):
    return refs["references"]


# ── The fair range is the product. It must be internally coherent. ──

def test_fair_range_contains_the_median(cards):
    for c in cards:
        assert c["fair_low"] <= c["median"] <= c["fair_high"], c["slug"]


def test_fair_range_sits_inside_the_observed_range(cards):
    for c in cards:
        assert c["low"] <= c["fair_low"], c["slug"]
        assert c["fair_high"] <= c["high"], c["slug"]


def test_every_card_states_its_sample_size(cards):
    """A range without an n is a claim with no evidence attached."""
    for c in cards:
        assert c["n_recent"] >= 10, c["slug"]
        assert c["n_total"] >= c["n_recent"], c["slug"]
        assert c["window_days"] > 0


def test_confidence_tier_matches_the_sample(cards):
    for c in cards:
        expected = "full" if c["n_recent"] >= 20 else "limited"
        assert c["confidence"] == expected, c["slug"]


# ── Identity ──

def test_slugs_are_unique_and_url_safe(cards):
    import re
    slugs = [c["slug"] for c in cards]
    assert len(slugs) == len(set(slugs)), "duplicate slugs would collide as URLs"
    for s in slugs:
        assert re.fullmatch(r"[a-z0-9-]+", s), s


def test_slug_is_brand_prefixed(cards):
    """Bare references collide: 9 reference tokens in this corpus are claimed
    by more than one brand."""
    for c in cards:
        assert c["slug"].startswith(c["brand"].lower().split()[0].strip("&.")), c["slug"]


def test_no_card_is_built_on_a_fabricated_reference(cards):
    """Bare 3-digit 'references' were digit runs lifted out of the price."""
    from filter import is_junk_ref
    for c in cards:
        assert not is_junk_ref(c["ref"]), c["slug"]


# ── Thin data is withheld, not smoothed over ──

def test_monthly_points_are_never_built_on_one_listing(cards):
    for c in cards:
        for m in c["monthly"]:
            assert m["n"] >= 3, f"{c['slug']} {m['month']}"


def test_year_breakdown_is_never_built_on_one_listing(cards):
    for c in cards:
        for y in c["by_year"]:
            assert y["n"] >= 3, f"{c['slug']} {y['year']}"


def test_time_to_sell_is_omitted_rather_than_published_thin(cards):
    for c in cards:
        if c["time_to_sell"] is None:
            continue
        assert c["time_to_sell"]["n"] >= 3, c["slug"]
        assert c["time_to_sell"]["n"] == c["sales_observed"], c["slug"]


# ── Specs are consensus, and say how strong the consensus is ──

def test_specs_carry_their_backing_counts(cards):
    """For Rolex 126334 the parser reads one fixed material as two-tone (107),
    steel (15), white gold (9) and null (39). Publishing the mode is fine;
    publishing it without saying how thin the agreement is, is not."""
    for c in cards:
        for name, s in (c["specs"] or {}).items():
            assert s["n"] >= 1, f"{c['slug']}.{name}"
            assert s["n"] <= s["of"], f"{c['slug']}.{name}"
            assert s["value"] not in (None, ""), f"{c['slug']}.{name}"


def test_absent_specs_are_omitted_not_guessed(cards):
    """None means 'not stated', never 'no'. An unstated field must be missing
    from specs entirely rather than present with a falsy value."""
    for c in cards:
        for name, s in (c["specs"] or {}).items():
            assert s is not None, f"{c['slug']}.{name}"


# ── Coverage is declared, not implied ──

def test_coverage_is_published_and_consistent(refs, cards):
    cov = refs["coverage"]
    assert cov["references_published"] == len(cards)
    assert cov["full_confidence"] + cov["limited_confidence"] == len(cards)
    assert sum(cov["by_brand"].values()) == len(cards)


def test_caveat_states_the_two_things_that_could_mislead(refs):
    """Asking-not-sold, and that coverage is concentrated rather than a market
    sample. Both were live misreadings on the previous page."""
    c = refs["caveat"].lower()
    assert "asking" in c and "not transacted" in c or "asking prices" in c
    assert "rolex" in c


def test_sorted_by_confidence(cards):
    ns = [c["n_recent"] for c in cards]
    assert ns == sorted(ns, reverse=True)
