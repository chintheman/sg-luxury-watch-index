"""Phase 3 — extraction correctness, Singapore-only gating, and attributes.

Each test here corresponds to a bug measured against the live corpus, not a
hypothetical. The comments name the damage each one was doing.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "parser"))

from attributes import extract_attributes  # noqa: E402
from brands import match_brand  # noqa: E402
from filter import (  # noqa: E402
    classify, extract_condition, extract_price, is_singapore_market,
    strip_noise_lines,
)


# ── Brand matching ─────────────────────────────────────────────────────────

def test_unicode_bold_brand_resolves():
    """𝐑𝐨𝐥𝐞𝐱 — .lower() does not fold maths-bold, so brand came back None."""
    assert match_brand("𝐑𝐨𝐥𝐞𝐱 𝐂𝐨𝐬𝐦𝐨𝐠𝐫𝐚𝐩𝐡 𝐃𝐚𝐲𝐭𝐨𝐧𝐚") == "Rolex"


@pytest.mark.parametrize("text,expected", [
    ("Frederique Constant Highlife Worldtimer", "Frederique Constant"),
    ("Jacob & Co. Epic X Chrono", "Jacob & Co"),
    ("Carl F. Bucherer Heritage BiCompax", "Carl F. Bucherer"),
    ("Baume & Mercier Clifton Baumatic", "Baume & Mercier"),
])
def test_previously_missing_brands_resolve(text, expected):
    assert match_brand(text) == expected


def test_ringgit_price_is_not_richard_mille():
    """RM is both a Richard Mille prefix and the Malaysian Ringgit symbol."""
    assert match_brand("Rolex Daytona 🇲🇾 RM53,800") == "Rolex"
    assert match_brand("Price 🇲🇾 RM14x,800") is None


def test_real_richard_mille_still_resolves():
    assert match_brand("RM 011 Felipe Massa") == "Richard Mille"
    assert match_brand("Richard Mille RM030 Titanium") == "Richard Mille"


# ── Singapore-only gating ──────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Rolex Submariner RM53,800",
    "Rolex Submariner 🇲🇾 Price 88,800",
    "Rolex Submariner MYR 53800",
    "Rolex Submariner, collection in Johor",
    "Rolex Submariner USD $14,400",
])
def test_non_singapore_stock_is_excluded(text):
    assert is_singapore_market(text) is False
    assert classify(text)[1] == "not_singapore"


def test_singapore_listing_passes_the_gate():
    assert is_singapore_market("Rolex Submariner SGD $17,700") is True


def test_no_currency_conversion_exists():
    """Conversion was deleted outright; a foreign price must never become SGD."""
    import filter as f
    assert not hasattr(f, "CURRENCY_RATES")


# ── Line-level noise ───────────────────────────────────────────────────────

def test_financing_line_does_not_kill_the_listing():
    """2,097 of HengWatch's 2,100 posts died on an 'Installment Plan' line."""
    text = ("Rolex Datejust 41\n• Model : 126331\n• Case size : 41mm\n"
            "Priced at\n💲\n22300\n"
            "• Hsbc / Standard Chartered / Dbs / Uob Installment payment plan accepted , 6 / 12 / 24 months")
    assert classify(text)[0] is True
    assert extract_price(text) == 22300, "the price must survive the financing line"


def test_shop_link_line_does_not_kill_the_listing():
    """422 watchdistrictsg listings died on a store link."""
    text = "Rolex Lady Datejust 179160\nPrice: SGD $8,500\nShop at watchdistrict.store"
    assert classify(text)[0] is True


def test_strip_noise_lines_keeps_the_watch_content():
    kept = strip_noise_lines("Rolex Submariner\nPrice: $17,700\nInstallment plan available")
    assert "Submariner" in kept and "17,700" in kept and "Installment" not in kept


# ── Price parsing ──────────────────────────────────────────────────────────

def test_labelled_bare_price_is_read():
    assert extract_price("Priced at\n💲\n22300") == 22300


def test_reference_number_is_never_read_as_a_price():
    assert extract_price("• Model : 126331\n• Case size : 41mm") is None


def test_masked_price_is_rejected_not_guessed():
    """'RM14x,800' used to parse to the visible digits — a wrong number."""
    assert extract_price("Rolex Daytona $13x,800") is None


@pytest.mark.parametrize("text,expected", [
    ("SGD $17,950", 17950), ("Price: $8,700", 8700), ("$16.8k", 16800),
    ("Only SGD$500/month", None), ("Prices are subject to change", None),
])
def test_price_parsing_regressions(text, expected):
    assert extract_price(text) == expected


# ── Condition ──────────────────────────────────────────────────────────────

def test_box_and_papers_marks_preowned():
    """'box.*papers' was a literal inside a substring test and never matched."""
    assert extract_condition("Rolex, box and papers, 2021") == "p"
    assert extract_condition("Papers and box included") == "p"


@pytest.mark.parametrize("text,expected", [
    ("Rolex BNIB", "n"), ("LNIB May 2025", "n"),
    ("Rolex full set", "p"), ("Rolex Datejust", "u"),
])
def test_condition_classification(text, expected):
    assert extract_condition(text) == expected


# ── Attributes ─────────────────────────────────────────────────────────────

def test_attributes_from_a_real_listing():
    text = ("New Jun 2026 Hublot Classic Fusion Strap\n542.NX.7170.LR\nBlue Dial\n"
            "Our Ref: Z25924\nPrice: $6,700\nCase Diameter: 42mm\n"
            "Material: Titanium\nOriginal Box: Yes\nOriginal Cert/Papers: Yes")
    a = extract_attributes(text)
    assert a["case_size_mm"] == 42
    assert a["case_material"] == "titanium"
    # "Original Box: Yes" + "Original Cert/Papers: Yes" is more specific than
    # the catch-all "full set" phrasing, and is reported as such.
    assert a["box_papers"] == "box + papers"
    assert a["stock_code"] == "Z25924"
    assert a["dial_colour"] == "blue"
    assert a["year"] == 2026


def test_explicit_full_set_phrasing_is_recognised():
    assert extract_attributes("Rolex Submariner, full set")["box_papers"] == "full set"


def test_watch_only_is_distinguished_from_unknown():
    assert extract_attributes("Rolex Submariner, watch only")["box_papers"] == "watch only"


def test_absent_attributes_are_none_not_false():
    """None means 'not stated'. It must never be read as 'no box'."""
    a = extract_attributes("Rolex Submariner SGD $17,700")
    assert a["box_papers"] is None
    assert a["case_size_mm"] is None


def test_water_resistance_is_not_mistaken_for_case_size():
    a = extract_attributes("Omega Ploprof 1200M Rubber\nCase Diameter: 55mm")
    assert a["case_size_mm"] == 55


def test_dial_nickname_is_captured():
    assert extract_attributes("Rolex GMT-Master II Pepsi")["dial_nickname"] == "Pepsi"


def test_two_tone_beats_plain_steel():
    a = extract_attributes("Rolex Datejust steel & rose gold")
    assert a["case_material"] == "two-tone"
