#!/usr/bin/env python3
"""Canonical brand table — single source of truth for brand matching.

Previously filter.py::has_brand(), index_engine.py::extract_brand(), and
sold_tracer.py each carried their own independent hardcoded brand list, and
they had already drifted out of sync (has_brand() knew brands extract_brand()
didn't), which let listings pass classification with a resolved brand for the
admission check but then get `brand: null` from the field actually shown/used
downstream. Everything routes through here now so that can't happen again.

Canonical names must stay exactly as-is: they're also the keys used by
BRAND_MODEL_MAP in index_engine.py and filter.py.
"""
import re
import unicodedata

# canonical name -> alternate spellings/formatting seen in dealer posts.
# Matching is done on a normalized form (lowercased, periods stripped,
# hyphens/whitespace collapsed) so listing the canonical name alone is
# usually enough to also catch hyphen/space/case variants for free.
BRAND_ALIASES = {
    "Rolex": [],
    "Omega": [],
    "Patek Philippe": [],
    "Tudor": [],
    "Cartier": [],
    "Breitling": [],
    "Audemars Piguet": [],
    "IWC": [],
    "Panerai": [],
    "Hublot": [],
    "TAG Heuer": [],
    "Seiko": [],
    "Grand Seiko": [],
    "Chopard": [],
    "Blancpain": [],
    "Breguet": [],
    "Vacheron Constantin": [],
    "Jaeger-LeCoultre": [],
    "Franck Muller": [],
    "A. Lange & Sohne": ["A. Lange & Söhne", "A Lange Sohne"],
    "Richard Mille": [],
    "Bell & Ross": [],
    "Casio": [],
    "Oris": [],
    "Zenith": [],
    "Piaget": [],
    "Longines": [],
    "Tissot": [],
    "Hamilton": [],
    "G-Shock": [],
    "Baltic": [],
    "Nomos": [],
    "Ulysse Nardin": [],
    "Girard-Perregaux": [],
    "Bulgari": [],
    "Bvlgari": [],
    "Corum": [],
    "MB&F": [],
    "FP Journe": ["F.P. Journe", "F.P Journe", "F P Journe"],
    "Urwerk": [],
    "H. Moser": ["H Moser", "Moser & Cie", "Moser & Cie."],
    "Sinn": [],
    "Swarovski": [],
    "Gucci": [],
    "Hermes": ["Hermès"],
    "Montblanc": [],
    # previously missing from every brand list — confirmed present in the
    # live dealer data with brand: null as a result
    "Gerald Genta": ["Gérald Genta"],
    "Parmigiani Fleurier": ["Parmigiani"],
    "Roger Dubuis": [],
    "Louis Moinet": [],
    "Glashutte Original": ["Glashütte Original", "Glashutte", "Glashütte"],
    "Chanel": [],
    "Louis Erard": [],
    # Second batch, same cause: real brands present in the dealer data that no
    # brand list knew about, so their listings passed classification and then
    # vanished from the index with brand: null.
    "Frederique Constant": [],
    "Jacob & Co": ["Jacob and Co", "Jacob & Co."],
    "Baume & Mercier": ["Baume et Mercier", "Baume and Mercier"],
    "Carl F. Bucherer": ["Carl F Bucherer", "Carl Bucherer"],
    "Graham": [],
    "Czapek": [],
    "Bovet": [],
    "Chronoswiss": [],
    "Jaquet Droz": [],
    "Konstantin Chaykin": [],
    "Bedat": ["Bedat & Co"],
    "Fears": [],
    "Arnold & Son": ["Arnold and Son"],
}

# Short abbreviations need word-boundary matching, not substring — "RM" or
# "AP" as loose substrings would false-positive constantly.
ABBREVIATIONS = {
    "AP": "Audemars Piguet",
    "JLC": "Jaeger-LeCoultre",
    "GS": "Grand Seiko",
}

# "RM" is both a Richard Mille model prefix and the Malaysian Ringgit symbol,
# and treating it as a plain abbreviation mis-attributed ringgit prices
# ("RM53,800", "RM14x,800") to Richard Mille. A real model reference is 2-3
# digits, optionally hyphen-suffixed (RM 011, RM 030-01, RM 67-01); a ringgit
# amount runs to 4+ digits or carries a thousands comma. Require the model
# shape and reject the money shape.
RM_MODEL_RE = re.compile(r"\bRM\s?\d{2,3}(?:-\d{2})?\b(?![\d,])")

CANONICAL_BRANDS = list(BRAND_ALIASES.keys())


def _normalize(text):
    # NFKC first: dealers style brand names with Unicode maths-bold and other
    # presentation forms (𝐑𝐨𝐥𝐞𝐱), which .lower() does not fold, so the brand
    # simply never matched and the listing was published with brand: null.
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace(".", "")
    t = re.sub(r"[-\s]+", " ", t)
    return t.strip()


# (normalized variant, canonical name), longest normalized form first so e.g.
# "grand seiko" is tried before the "seiko" it contains as a substring.
_LOOKUP = sorted(
    (
        (_normalize(variant), canonical)
        for canonical, aliases in BRAND_ALIASES.items()
        for variant in [canonical] + aliases
    ),
    key=lambda pair: -len(pair[0]),
)


def match_brand(text):
    """Return the canonical brand name for the *first-mentioned* brand in
    text (earliest position wins, longer match breaks a tie), or None.

    Position, not just presence, matters: dealers put the item's actual
    brand at/near the start of a listing. A brand mentioned later — e.g.
    "Rolex Daytona ... similar vibe to a Vacheron Constantin Overseas" — is
    far more likely to be an incidental comparison than the item being sold.
    Matching on presence alone (the old behavior) mis-attributed listings
    like that to whichever brand happened to be checked, regardless of
    where it actually appeared in the text.
    """
    if not text:
        return None
    norm = _normalize(text)
    best_pos, best_len, best_canonical = None, -1, None
    for norm_variant, canonical in _LOOKUP:
        if not norm_variant:
            continue
        idx = norm.find(norm_variant)
        if idx == -1:
            continue
        if best_pos is None or idx < best_pos or (idx == best_pos and len(norm_variant) > best_len):
            best_pos, best_len, best_canonical = idx, len(norm_variant), canonical
    if best_canonical is not None:
        return best_canonical

    # Abbreviations only as a fallback when no full brand name matched —
    # weaker signal, but still prefer whichever appears earliest.
    upper = unicodedata.normalize("NFKC", text).upper()
    best_abbr_pos, best_abbr_canonical = None, None
    for abbr, canonical in ABBREVIATIONS.items():
        m = re.search(r'\b' + abbr + r'\b', upper)
        if m and (best_abbr_pos is None or m.start() < best_abbr_pos):
            best_abbr_pos, best_abbr_canonical = m.start(), canonical

    m = RM_MODEL_RE.search(upper)
    if m and (best_abbr_pos is None or m.start() < best_abbr_pos):
        best_abbr_pos, best_abbr_canonical = m.start(), "Richard Mille"
    return best_abbr_canonical


def has_brand(text):
    return match_brand(text) is not None
