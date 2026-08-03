#!/usr/bin/env python3
"""Structured attributes beyond brand/model/price/condition.

These are stored but not displayed. Measured presence across the corpus at the
time they were added, which is why this particular set was chosen:

    case size        82%     already regex-detected as a filter gate, then discarded
    case material    75%     steel vs gold is a large price difference on one reference
    bracelet/strap   72%     Jubilee vs Oyster vs leather moves price on one reference
    box & papers     71%     biggest price driver after the model itself
    warranty         69%     drives resale value and enables an age-of-stock signal
    dealer stock code 64%    tracks the SAME PHYSICAL WATCH across reposts and channels
    dial variant     39%     nicknamed dials (Pepsi, Panda, Wimbledon) carry premiums
    year             7%*     *rises sharply once template channels parse

Everything returns None when absent. None means "not stated", never "no" —
a listing that does not mention papers is not a listing without papers, and
downstream code must not treat the two as the same.

Two fields are looser than their names suggest, and are recorded here rather
than being quietly over-trusted later:

  year      The year the DEALER states, which for these channels is usually
            production or purchase ("New Jun 2026 ...", "Mint Jan 2010 ...").
            It is not a verified manufacture date. Coverage came out at 86%,
            far above the 7% the audit predicted, precisely because this
            "Mon YYYY" prefix is so common — do not read that as 86% of
            listings having a confirmed production year.

  warranty  Either a warranty expiry, a card date, or the bare string
            "stated". Useful as a signal, not as a precise date field.
"""
import re
import unicodedata

# ── Case size ───────────────────────────────────────────────────────────────
# Bounded to plausible wristwatch diameters so a water-resistance depth
# ("1200M"), a movement calibre or a reference number cannot be mistaken for one.
_CASE_SIZE = re.compile(r'(?i)\b(2[0-9]|3[0-9]|4[0-9]|5[0-5])(?:\.\d)?\s*mm\b')

# ── Case material ──────────────────────────────────────────────────────────
# Order matters: the most specific wins, so "steel & rose gold" reads as
# two-tone rather than plain steel.
_MATERIALS = [
    ("two-tone",   r'(?i)\b(two[\s-]?tone|steel\s*(?:&|and|\+|/)\s*(?:yellow|rose|white|pink)?\s*gold|half\s*gold|rolesor)\b'),
    ("platinum",   r'(?i)\bplatinum\b|\bplat\b'),
    ("rose gold",  r'(?i)\b(rose\s*gold|everose|pink\s*gold|red\s*gold)\b'),
    ("white gold", r'(?i)\bwhite\s*gold\b|\bwg\b'),
    ("yellow gold",r'(?i)\b(yellow\s*gold|full\s*gold|18k\s*gold|yg)\b'),
    ("ceramic",    r'(?i)\bceramic\b|\bcerachrom\b'),
    ("titanium",   r'(?i)\btitanium\b|\bti\b'),
    ("carbon",     r'(?i)\b(carbon|ntpt|forged\s*carbon)\b'),
    ("steel",      r'(?i)\b(stainless\s*steel|oystersteel|steel|ss)\b'),
]

# ── Bracelet / strap ───────────────────────────────────────────────────────
_BRACELETS = [
    ("jubilee",    r'(?i)\bjubilee\b'),
    ("president",  r'(?i)\bpresident(?:ial)?\b'),
    ("oysterflex", r'(?i)\boysterflex\b'),
    ("oyster",     r'(?i)\boyster\b(?!\s*perpetual)'),
    ("rubber",     r'(?i)\brubber\b'),
    ("leather",    r'(?i)\bleather\b|\balligator\b|\bcrocodile\b'),
    ("nato",       r'(?i)\bnato\b'),
    ("integrated", r'(?i)\bintegrated\s*bracelet\b'),
    ("bracelet",   r'(?i)\bbracelet\b'),
    ("strap",      r'(?i)\bstrap\b'),
]

# ── Box & papers ───────────────────────────────────────────────────────────
_FULL_SET   = re.compile(r'(?i)\b(full\s*set|complete\s*set|box\s*(?:&|and|\+|,)?\s*papers?|papers?\s*(?:&|and|\+|,)?\s*box|b\s*&\s*p)\b')
_BOX_ONLY   = re.compile(r'(?i)\b(?:original\s*)?box\b\s*[:\-]?\s*(yes|✓)?')
_PAPERS_ONLY= re.compile(r'(?i)\b(?:original\s*)?(?:papers?|cert(?:ificate)?s?|warranty\s*card)\b\s*[:\-]?\s*(yes|✓)?')
_WATCH_ONLY = re.compile(r'(?i)\b(watch\s*only|bare\s*watch|no\s*box|without\s*box|naked)\b')

# ── Warranty ───────────────────────────────────────────────────────────────
_WARRANTY_UNDER = re.compile(r'(?i)\b(under\s*warranty|warranty\s*(?:till|until|valid|to)\b|int(?:\'l|ernational)?\s*warranty)')
_WARRANTY_DATE  = re.compile(r'(?i)\bwarranty\b[^\n]{0,30}?((?:19|20)\d{2})')
_CARD_DATE      = re.compile(r'(?i)\b(?:card|cert(?:ificate)?|papers?)\s*(?:dated?|date)\b[^\n]{0,20}?((?:19|20)\d{2})')

# ── Year of manufacture ────────────────────────────────────────────────────
# Anchored on an explicit label or a "Mon YYYY" stamp, so a reference number
# or a price can never be read as a year.
_YEAR_LABELLED = re.compile(r'(?i)\b(?:year|yr|prod(?:uction)?|manufactured)\b\s*[:\-]?\s*(?:\w{3,9}\s+)?((?:19|20)\d{2})')
_YEAR_MONTH    = re.compile(r'(?i)\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+((?:19|20)\d{2})\b')
_YEAR_PAREN    = re.compile(r'\((?:[A-Za-z]{3,9}\s+)?((?:19|20)\d{2})\)')

# ── Dealer stock code ──────────────────────────────────────────────────────
_STOCK_CODE = re.compile(r'(?i)\b(?:our\s*ref|ref\s*(?:no|code)|stock\s*(?:no|code)|item\s*(?:no|code))\b\s*[:\-#]?\s*([A-Z]{1,3}\d{3,7})\b')

# ── Dial nicknames — the market's own vocabulary ───────────────────────────
_NICKNAMES = [
    "Pepsi", "Batman", "Batgirl", "Hulk", "Kermit", "Starbucks", "Sprite",
    "Root Beer", "Rootbeer", "Coke", "Bluesy", "Wimbledon", "Panda",
    "Reverse Panda", "Tiffany", "Smurf", "Bruce Wayne", "John Mayer",
    "Green Bay", "Pikachu", "Ice Blue", "Sundust", "Meteorite",
]
_NICK_RE = re.compile(r'(?i)\b(' + "|".join(re.escape(n) for n in _NICKNAMES) + r')\b')
_DIAL_COLOUR = re.compile(
    r'(?i)\b(black|white|blue|green|silver|champagne|salmon|grey|gray|brown|'
    r'chocolate|choco|aubergine|rhodium|slate|olive|turquoise|'
    r'mop|mother\s*of\s*pearl)\s*(?:dial|face)\b'
)


def _first_match(text, table):
    for label, pattern in table:
        if re.search(pattern, text):
            return label
    return None


def extract_attributes(text):
    """Return a dict of structured attributes. Values are None when absent."""
    if not text:
        return {}
    t = unicodedata.normalize("NFKC", text)

    # box & papers
    if _FULL_SET.search(t):
        box_papers = "full set"
    elif _WATCH_ONLY.search(t):
        box_papers = "watch only"
    else:
        has_box, has_papers = bool(_BOX_ONLY.search(t)), bool(_PAPERS_ONLY.search(t))
        box_papers = ("box + papers" if has_box and has_papers
                      else "box only" if has_box
                      else "papers only" if has_papers else None)

    # warranty
    warranty = None
    m = _WARRANTY_DATE.search(t) or _CARD_DATE.search(t)
    if m:
        warranty = m.group(1)
    elif _WARRANTY_UNDER.search(t):
        warranty = "stated"

    # year of manufacture
    year = None
    for pat in (_YEAR_LABELLED, _YEAR_MONTH, _YEAR_PAREN):
        m = pat.search(t)
        if m:
            y = int(m.group(1))
            if 1900 <= y <= 2035:
                year = y
                break

    size = _CASE_SIZE.search(t)
    nick = _NICK_RE.search(t)
    colour = _DIAL_COLOUR.search(t)
    stock = _STOCK_CODE.search(t)

    return {
        "case_size_mm":   int(float(size.group(1))) if size else None,
        "case_material":  _first_match(t, _MATERIALS),
        "bracelet":       _first_match(t, _BRACELETS),
        "box_papers":     box_papers,
        "warranty":       warranty,
        "year":           year,
        "dial_nickname":  nick.group(1).title() if nick else None,
        "dial_colour":    (colour.group(1).lower() if colour else None),
        "stock_code":     stock.group(1).upper() if stock else None,
    }
