"""Dedupe — collapse reposts of the same watch without deleting real inventory.

The dangerous failure here is over-merging: two dealers each holding a
Submariner 126610LN are two watches, not one. Merging them would understate
the market, and because brand weights are volume-driven, it would corrupt
every baseline. Several tests below exist specifically to hold that line.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "parser"))

from dedupe import PRICE_TOLERANCE_PCT, dedupe, summarise  # noqa: E402


def rec(id, channel, brand, price, date, ref=None, stock_code=None):
    return {"id": id, "channel": channel, "brand": brand, "price": price,
            "date": date, "ref": ref, "stock_code": stock_code}


# ── Collapsing genuine reposts ─────────────────────────────────────────────

def test_same_dealer_same_stock_code_is_one_watch():
    out, st = dedupe([
        rec(1, "a", "Rolex", 10600, "2026-06-10", "126610", "Z1"),
        rec(2, "a", "Rolex", 10600, "2026-06-24", "126610", "Z1"),
        rec(3, "a", "Rolex", 10400, "2026-07-08", "126610", "Z1"),
    ])
    assert st["output"] == 1
    assert out[0]["id"] == 3, "the newest sighting carries the current asking price"


def test_repost_history_is_preserved_not_discarded():
    """This is the price-cut signal; dedupe must not throw it away."""
    out, _ = dedupe([
        rec(1, "a", "Rolex", 10600, "2026-06-10", "126610", "Z1"),
        rec(2, "a", "Rolex", 10400, "2026-07-08", "126610", "Z1"),
    ])
    d = out[0]["dup"]
    assert d["times_listed"] == 2
    assert d["first_price"] == 10600 and d["last_price"] == 10400
    assert d["price_change_pct"] < 0
    assert d["days_listed"] == 28


def test_no_repeat_means_no_dup_block():
    out, st = dedupe([rec(1, "a", "Rolex", 10600, "2026-06-10", "126610", "Z1")])
    assert st["removed"] == 0
    assert "dup" not in out[0]


# ── Holding the line against over-merging ──────────────────────────────────

def test_two_dealers_with_the_same_reference_stay_separate():
    """Median price spread between dealers for one reference is 36%."""
    out, st = dedupe([
        rec(1, "a", "Rolex", 10600, "2026-07-08", "126610", "Z1"),
        rec(2, "b", "Rolex", 14500, "2026-07-08", "126610", "X9"),
    ])
    assert st["output"] == 2, "cross-dealer matching would delete real inventory"


def test_two_dealers_at_an_identical_price_still_stay_separate():
    """Even an exact price match across channels is two watches."""
    out, st = dedupe([
        rec(1, "a", "Rolex", 12000, "2026-07-08", "126610"),
        rec(2, "b", "Rolex", 12000, "2026-07-08", "126610"),
    ])
    assert st["output"] == 2


def test_one_dealer_holding_two_of_a_reference_at_different_prices():
    out, st = dedupe([
        rec(1, "c", "Omega", 5000, "2026-07-01", "310.30"),
        rec(2, "c", "Omega", 9000, "2026-07-02", "310.30"),
    ])
    assert st["output"] == 2, "an 80% gap is two watches, not a re-price"


def test_no_reference_and_no_stock_code_never_merges():
    """Without an identifier there is no evidence two rows are one watch."""
    out, st = dedupe([
        rec(1, "c", "Rolex", 12000, "2026-07-01"),
        rec(2, "c", "Rolex", 12000, "2026-07-02"),
    ])
    assert st["output"] == 2


# ── The fallback path ──────────────────────────────────────────────────────

def test_close_prices_without_a_stock_code_collapse():
    out, st = dedupe([
        rec(1, "c", "Tudor", 4000, "2026-07-01", "79030"),
        rec(2, "c", "Tudor", 4100, "2026-07-05", "79030"),
    ])
    assert st["output"] == 1 and out[0]["id"] == 2


def test_tolerance_boundary_behaviour():
    just_inside = 1000 * (1 + PRICE_TOLERANCE_PCT / 100)
    out, st = dedupe([
        rec(1, "c", "Tudor", 1000, "2026-07-01", "79030"),
        rec(2, "c", "Tudor", int(just_inside), "2026-07-02", "79030"),
    ])
    assert st["output"] == 1

    out, st = dedupe([
        rec(1, "c", "Tudor", 1000, "2026-07-01", "79030"),
        rec(2, "c", "Tudor", int(just_inside) + 50, "2026-07-02", "79030"),
    ])
    assert st["output"] == 2


def test_stock_code_beats_price_distance():
    """The dealer's own identifier outranks any price heuristic."""
    out, st = dedupe([
        rec(1, "a", "Rolex", 10000, "2026-06-01", "126610", "Z1"),
        rec(2, "a", "Rolex", 30000, "2026-07-01", "126610", "Z1"),
    ])
    assert st["output"] == 1, "same stock code is the same watch, however it was repriced"


# ── Summary maths ──────────────────────────────────────────────────────────

def test_summarise_reports_a_flat_price_as_no_change():
    s = summarise([rec(1, "a", "Rolex", 100, "2026-01-01"),
                   rec(2, "a", "Rolex", 100, "2026-01-05")])
    assert s["price_change_pct"] is None
    assert s["days_listed"] == 4


def test_stats_are_internally_consistent():
    out, st = dedupe([
        rec(1, "a", "Rolex", 100, "2026-01-01", "r1", "Z1"),
        rec(2, "a", "Rolex", 100, "2026-01-02", "r1", "Z1"),
        rec(3, "b", "Omega", 200, "2026-01-01", "r2", "Z2"),
    ])
    assert st["input"] == 3 and st["output"] == 2 and st["removed"] == 1
    assert st["output"] + st["removed"] == st["input"]
