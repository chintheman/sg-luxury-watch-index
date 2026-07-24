#!/usr/bin/env python3
"""Canonical brand table — single source of truth for brand matching.

Previously filter.py::has_brand(), index_engine.py::extract_brand(), and
sold_tracer.py each carried their own independent hardcoded brand list, and
they had already drifted out of sync (has_brand() knew brands extract_brand()
didn't), which let listings pass classification with a resolved brand for the
admission check but then get `brand: null` from the field actually shown/used
downstream. Everything routes through here now so that can't happen again.

Canonical names must stay exactly as-is: they're also the keys used by
PRESTIGE / RETAIL_PRICES / BRAND_MODEL_MAP in index_engine.py and filter.py.
"""
import re

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
}

# Short abbreviations need word-boundary matching, not substring — "RM" or
# "AP" as loose substrings would false-positive constantly.
ABBREVIATIONS = {
    "AP": "Audemars Piguet",
    "RM": "Richard Mille",
    "JLC": "Jaeger-LeCoultre",
    "GS": "Grand Seiko",
}

CANONICAL_BRANDS = list(BRAND_ALIASES.keys())


def _normalize(text):
    t = (text or "").lower()
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
    """Return the canonical brand name if any known brand/alias appears in
    text, else None."""
    if not text:
        return None
    norm = _normalize(text)
    for norm_variant, canonical in _LOOKUP:
        if norm_variant and norm_variant in norm:
            return canonical
    upper = text.upper()
    for abbr, canonical in ABBREVIATIONS.items():
        if re.search(r'\b' + abbr + r'\b', upper):
            return canonical
    return None


def has_brand(text):
    return match_brand(text) is not None
