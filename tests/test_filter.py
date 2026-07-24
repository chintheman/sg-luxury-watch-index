"""Regression tests for parser/filter.py, built from real examples found
while auditing why cufflinks/accessories occasionally showed up on the site
as "watches", and why some genuine watches were vanishing (brand: null)."""
from filter import classify, is_watch_listing, has_brand


# ── Real cufflink listings that must never be classified as watches ────────

PATEK_CUFFLINKS = (
    "LNIB Apr 2026 Patek Philippe Nautilus Cuff Links NA 205.9057G-014 "
    "Sunburst Blue Dial\nOur Ref: Z25825\nPrice: $4,900\nCase Diameter: -\n"
    "Material: White Gold"
)

ROLEX_CUFFLINKS = (
    "New Mar 2026 Rolex 'Fluted' cufflinks NA A1038GREEN Green Dial\n"
    "Our Ref: A6796\nPrice: $4,500\nCase Diameter: -\n"
    "Material: Ceramic & Yellow Gold"
)

# The exact attack scenario the audit flagged: an accessory listing with a
# filled-in case-diameter placeholder and no genuine watch anatomy. Uses
# "crystal only" rather than "cufflinks" so this specifically exercises the
# ACCESSORY_KW/anatomy carve-out (below) rather than the earlier absolute
# NOISE_PATTERNS reject that "cufflinks" itself now also triggers.
ACCESSORY_WITH_FAKE_DIAMETER = (
    "Crystal Only Patek Philippe Ref: Z99999 Price: $500 "
    "Case Diameter: 20mm Material: Sapphire"
)

DESK_CLOCK = (
    "New Jun 2026 Rolex Submariner Desk Clock 909010LN Black Dial\n"
    "Our Ref: A7751\nPrice: $17,950\nCase Diameter: 80mm\n"
    "Material: Steel/Gold"
)


def test_rejects_cufflinks_regardless_of_case_diameter_field():
    # Caught by the absolute NOISE_PATTERNS reject (fixed to match the
    # plural/two-word "cufflinks"/"Cuff Links" dealers actually use, not
    # just the singular "cufflink" the original pattern was stuck on).
    assert classify(PATEK_CUFFLINKS) == (False, "noise_pattern")
    assert classify(ROLEX_CUFFLINKS) == (False, "noise_pattern")
    assert not is_watch_listing(PATEK_CUFFLINKS)
    assert not is_watch_listing(ROLEX_CUFFLINKS)


def test_rejects_accessory_even_with_a_plausible_diameter_placeholder():
    # A single filled-in mm value must not be enough on its own to admit an
    # accessory — this is exactly the gap the audit found.
    assert classify(ACCESSORY_WITH_FAKE_DIAMETER) == (False, "accessory_no_anatomy")


def test_rejects_desk_clock_despite_oversized_case_diameter():
    assert classify(DESK_CLOCK) == (False, "accessory_no_anatomy")


# ── Real watch listings that must NOT be rejected (false-positive guard) ───
# All of these were confirmed being wrongly rejected by an earlier, stricter
# version of the accessory carve-out that treated "strap"/"bezel insert" as
# accessory-exclusive terms, when they're common real-watch spec vocabulary.

GML3575_ROLEX = (
    "Price : SGD $56'500.00\nItem no: GML3575\n"
    "Brand : Rolex Submariner Gold Blue\nModel : 16618LB\n"
    "Dial : Blue dial w/ applied tritium markers\nCase : 40mm gold\n"
    "Bezel : Blue Aluminum Bezel insert\nBracelet / Strap : Gold\n"
    "Movement : Automatic\nBox / Cert : Full Set Jan 1993\n"
    "Condition : Look New In Box."
)

ROLEX_DAYTONA_OYSTERFLEX = (
    "Mint Mar 2025 Rolex Daytona Oysterflex 126515LN Black Dial\n"
    "Our Ref: Z26025\nPrice: $57,800\nCase Diameter: 40mm\n"
    "Material: Everose Gold"
)

HUBLOT_CLASSIC_FUSION_STRAP = (
    "New Jun 2026 Hublot Classic Fusion Strap 542.NX.7170.LR Blue Dial\n"
    "Our Ref: Z25924\nPrice: $6,700\nCase Diameter: 45mm\nMaterial: Titanium"
)


def test_accepts_real_watch_that_mentions_bezel_insert_and_strap():
    ok, reason = classify(GML3575_ROLEX)
    assert (ok, reason) == (True, None)


def test_accepts_real_watches_with_strap_in_model_name():
    assert is_watch_listing(ROLEX_DAYTONA_OYSTERFLEX)
    assert is_watch_listing(HUBLOT_CLASSIC_FUSION_STRAP)


def test_accepts_plain_watch_listing():
    assert is_watch_listing(
        "Rolex Submariner 126610LN Price: SGD $16,800 BNIB full set"
    )


# ── Brand spelling/formatting variants (previously caused brand: null) ─────

def test_brand_variants_resolve_to_canonical_form():
    cases = [
        ("Girard Perregaux Laureato 42mm Price: $18,000", "Girard-Perregaux"),
        ("F.P. Journe Chronometre Bleu Price: $95,000", "FP Journe"),
        ("Roger Dubuis Excalibur Price: $45,000", "Roger Dubuis"),
        ("Chanel J12 Automatic 33mm Price: $8,500", "Chanel"),
        ("Louis Erard Le Regulateur Price: $3,500", "Louis Erard"),
        ("Parmigiani Fleurier Tonda Price: $22,000", "Parmigiani Fleurier"),
        ("Glashutte Original Senator Price: $9,000", "Glashutte Original"),
    ]
    from brands import match_brand

    for text, expected in cases:
        assert match_brand(text) == expected, text
        assert has_brand(text), text


def test_abbreviations_still_word_bounded():
    from brands import match_brand

    assert match_brand("AP Royal Oak 15400 Price: $45,000") == "Audemars Piguet"
    # "gap" must not spuriously match the "AP" abbreviation
    assert match_brand("Massive gap in the market Price: $100") is None


# ── Cross-brand mention hijacking (a Rolex listing that name-drops another
# brand as a comparison must not get attributed to the mentioned brand) ────

def test_earliest_mentioned_brand_wins_over_a_later_comparison():
    from brands import match_brand

    assert match_brand(
        "Rolex Daytona 116500LN Price: $45,000 (similar vibe to a Vacheron "
        "Constantin Overseas but way more iconic)"
    ) == "Rolex"
    assert match_brand(
        "Patek Philippe Nautilus 5711 Price: $180,000. Comes with overseas "
        "shipping available worldwide."
    ) == "Patek Philippe"
    assert match_brand(
        "Omega Speedmaster Price: $9,000 (not to be confused with a Tudor "
        "Black Bay, totally different watch)"
    ) == "Omega"


def test_position_tiebreak_prefers_more_specific_longer_match():
    from brands import match_brand

    # "Grand Seiko" must win over the "Seiko" it contains as a substring
    # when both start at the same position.
    assert match_brand("Grand Seiko SBGA211 Price: $5,000") == "Grand Seiko"
    # Plain "Seiko" with no "Grand" prefix must still resolve correctly.
    assert match_brand("Seiko 5 Sports SRPD Price: $300") == "Seiko"
