#!/usr/bin/env python3
"""Filter pipeline - determine if a Telegram message is a genuine watch listing."""
import re
import unicodedata

try:
    from brands import match_brand as _match_brand
except ImportError:
    from parser.brands import match_brand as _match_brand

# --- NON-SINGAPORE EXCLUSION ---
# This index prices the SINGAPORE secondary market. Foreign stock used to be
# converted into SGD at hardcoded rates and folded in, which put Malaysian
# inventory into a Singapore index. Measured across the corpus: 6,007 SGD /
# 12 MYR / 0 USD / 0 HKD / 0 EUR — the entire conversion subsystem existed to
# launder ~282 Malaysian listings (4.7%) into the number. Conversion is gone;
# anything not buyable in Singapore is excluded outright, never converted.
MY_SIGNALS = [
    re.compile(r'\bRM\s*\$?\s*\d', re.I),        # RM53,800 — ringgit price
    re.compile(r'\bMYR\b', re.I),
    re.compile(r'\b(malaysia|malaysian|johor|kuala\s*lumpur|penang)\b', re.I),
]
MY_FLAG = "\U0001F1F2\U0001F1FE"  # 🇲🇾

# Other non-SGD currencies. None appear in the corpus today, but a listing
# priced in them is by definition not Singapore stock, so exclude rather than
# convert if one ever shows up.
FOREIGN_CURRENCY = re.compile(
    r'(?:\b(?:USD|HKD|EUR|GBP|AUD|THB|IDR|PHP)\b|\bUS\s*\$|\bHK\s*\$|€|£)', re.I
)


def is_singapore_market(text):
    """False when a listing is not buyable in Singapore.

    Applied as a hard gate in classify(), so non-SG stock never becomes a
    listing at all -- it does not reach the index, the API or the page.
    """
    if not text:
        return True
    t = unicodedata.normalize("NFKC", text)
    if MY_FLAG in text:
        return False
    for pat in MY_SIGNALS:
        if pat.search(t):
            return False
    if FOREIGN_CURRENCY.search(t):
        return False
    return True


# Prices deliberately masked by the dealer: "RM14x,800", "$13x,800". These
# used to parse into implausible values (the visible digits only) rather than
# being rejected. 136 listings in the corpus do this.
# A price stated as a label followed by a bare number, possibly with emoji or
# newlines in between: "Priced at\n💲\n22300". Anchored on the word so a bare
# 6-digit reference number ("Model : 126331") can never be mistaken for one.
LABELLED_BARE_PRICE = re.compile(
    r'(?i)\bprice[ds]?\b\s*(?:at|:|-)?[\s\S]{0,12}?(\d{4,6})(?!\d)'
)

MASKED_PRICE = re.compile(r'(?:SGD?|USD|RM|MYR|\$|S\$)\s*\d+x{1,3}[\d,]*', re.I)

# --- EMOJI DIGIT DECODER ---
EMOJI_DIGITS = {
    '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
    '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
}

def normalize_currency_emoji(text):
    """Treat the 💲 emoji as a dollar sign. HengWatch and others use it as the
    only currency marker, on its own line above a bare number."""
    return (text or "").replace("\U0001F4B2", "$")


def decode_emoji_digits(text):
    """Convert emoji keycap digits (0U+FE0F+U+20E3) to plain digits."""
    # The pattern used UTF-8 BYTE escapes inside a str regex, so it matched
    # the characters U+00EF U+00B8 U+008F rather than the real keycap
    # sequence and never fired. U+FE0F is optional in the wild.
    pat = re.compile('([0-9])\ufe0f?\u20e3')
    return pat.sub(lambda m: m.group(1), text)

# --- NOISE PATTERNS ---
NOISE_PATTERNS = [
    # Giveaway / contest
    r'(?i)(giveaway|give\s*away|win\s+(a|this)\s+\w+\s+watch|going\s+to\s+one\s+lucky|competition|contest\s+alert)',
    # Pure promotion (no specific listing)
    r'(?i)^(?:[📢🎉🎊✨\s]*(?:big\s+deal|great\s+deal|flash\s+sale|promotion|announcement)[\s!🎉🎊✨]*)$',
    # Testimonials
    r'(?i)\bthank\s+you\b.*\b(trust|support|enjoy|patronage)\b',
    # Follow/subscribe CTAs (standalone)
    r'(?i)^\s*(?:follow|subscribe|join)\s+(?:us|our|now)\s*[!📱]',
    # Operating hours / shop info
    r'(?i)\b(pinned.*message|deleted message|opening hours|operating hours|shop base)\b',
    # Dealer update broadcasts (not individual listings)
    r'(?i)^(?:[📢🕘⏰🔄\s]*(?:watch\s+district\s+update|daily\s+update|weekly\s+update|stock\s+update|new\s+arrivals?\s+update)[\s!📢🕘⏰]*)$',
    # Service / repair
    r'(?i)\b(service centre|warranty registration|repair service|servicing special)\b',
    # Accessories with no watch (matches "cufflink(s)"/"cuff links" — was
    # singular-only before and silently never matched the plural/two-word
    # forms dealers actually use)
    r'(?i)\b(watch winder|watch box|watch roll|watch pouch|travel case|cuff\s*links?)\b',
    # Strap/bracelet standalone — only when no brand is present
    r'(?i)^\s*(?:leather strap|rubber strap|nato strap|bracelet|buckle|clasp)\b.*\$',
    # TikTok/Instagram links only (no watch details)
    r'(?i)^\s*https?://(?:vt\.)?tiktok\.com/\S+\s*$',
    # "Rate on request" or "Price on request"
    r'(?i)(rate|price|pricing)\s+(on|upon)\s+(request|enquiry|inquiry)',
    # Sold-only messages (any position, any formatting)
    r'(?i)\bSOLD\b',
    # App download / promotion (no watch listing)
    r'(?i)(download\s+\w+\s+app|unlock\s+exclusive\s+benefits|app\s+credits|watch\s+protective\s+film|watchskins|watchlab\s+servicing)',
    # Generic promotional taglines
    r'(?i)(lowest\s+(possible\s+)?price\s+guaranteed|best\s+(possible\s+)?price|unbeatable\s+value)',
]

# --- ACCESSORY KEYWORDS ---
# Deliberately excludes strap/buckle/clasp/band/deployant/end-link: those are
# common attributes *of* real watch listings (bracelet/strap material, clasp
# type — often even part of the model name, e.g. "Hublot Classic Fusion
# Strap"), not accessory-exclusive terms. Gating on them caused real, priced
# watch listings to get rejected outright. NOISE_PATTERNS already separately
# catches genuine standalone strap/buckle/clasp-for-sale posts (message
# *starts* with the term, ends with a price) with much better precision.
# What's left here is accessory products that have no legitimate reason to
# appear in a full watch listing.
ACCESSORY_KW = re.compile(
    r'(?i)\b(cuff\s*links?|desk\s*clock|watch\s*winder|wind\s*er|travel\s*pouch|watch\s*roll|watch\s*box|spring\s*bar|pen(?:cil)?\s*set|crown[-\s]?(stem|tube)|dial\s*(only|for\s*sale)|movement\s*(only|for\s*sale)|hands\s*set|crystal\s*(only|replacement))\b'
)

def has_brand(text):
    """Quick check if message mentions any watch brand."""
    return _match_brand(text) is not None

def has_watch_terms(text):
    """Check for watch-specific terminology."""
    terms = [
        r'\b\d{2,4}mm\b', r'\bref[:#.]?\s*\d', r'\bmodel\s*(no|#|number)',
        r'\b\d{4,6}[A-Z]{0,4}\b',
        r'\b(automatic|quartz|manual|mechanical)\b',
        r'\b(chronograph|chronometer|tourbillon)\b',
        r'\b(dial|bezel|case|movement)\b',
        r'\b(full set|box.*papers?|box.*cert|cert.*box)\b',
        r'\b(bnib|nib|pre-?owned|preowned|mint|unworn)\b',
        r'\b(new.*arrival|brand new)\b',
    ]
    return any(re.search(t, text or '', re.I) for t in terms)

def has_price(text):
    if not text:
        return False
    clean = normalize_currency_emoji(text).replace('\n', ' ').replace('|', ' ')
    # Check for real prices first (SGD and foreign currencies)
    has_real = False
    if re.search(r'(?:SGD? *\$|S\$ ?|USD? *\$|US *\$|HKD? *\$|HK *\$|MYR|RM *\$?)', clean, re.I):
        has_real = True
    elif re.search(r'€|EUR', clean, re.I):
        has_real = True
    elif re.search(r'\$\s*[\d,]+(?:\.\d{2})?', clean):
        has_real = True
    elif re.search(r'Price[:\s]+\$?[\d,]+', clean, re.I):
        has_real = True
    elif re.search(r'(?:sgd|usd|hkd|myr)\s*[\d,]+', clean, re.I):
        has_real = True
    elif LABELLED_BARE_PRICE.search(clean):
        # "Priced at 22300" — no symbol, no comma. Whole channels post this way.
        has_real = True
    # Reject if ONLY installment/monthly pricing
    if has_real:
        return True
    if re.search(r'(?i)(per\s*month|/month|monthly|installment|36\s*month)', clean):
        return False
    if re.search(r'(?i)only\s+SGD?\$?\d+.*(?:month|mth)', clean):
        return False
    # Reject discount/promo messages ($X off, X% off)
    if re.search(r'(?i)(s?\$?\s*\d[\d,]*\s*(?:%?\s*off)|(?:up\s+to\s+)?\$?\d[\d,]*\s*(?:%{0,2}\s*off))', clean):
        return False
    return False

# Watch-exclusive anatomy signals — deliberately excludes generic luxury-goods
# boilerplate like "certified" or a bare "ref #" that accessories get posted
# with too (confirmed in the raw data: dealers use the identical
# Ref/Price/Case/Material/Box/Papers template for both). Matches "Case: 40mm"
# as well as "Case Diameter/Size/Width: 40mm" — dealers use both phrasings.
_CASE_DIAMETER_RE = re.compile(
    r'(?i)(case\s*(?:diamet\w*|size|width)?|diamet\w*)\s*[:\s]*([12]\d|3[0-9]|4[0-5])\s*mm'
)
_WATCH_MECHANISM_RE = re.compile(
    r'(?i)\b(automatic|quartz|manual[\s-]?winding|mechanical|chronograph|'
    r'chronometer|tourbillon|perpetual\s*calendar|moon\s*phase|caliber|calibre)\b'
)


def _has_watch_anatomy(t, require_two_signals):
    """Signals that a listing describes an actual watch movement/case, used to
    rescue a listing that also matched ACCESSORY_KW. A case-diameter mention
    counts as one signal, each distinct mechanism term as another. When an
    accessory keyword is present, require two signals total rather than any
    single one — a case-diameter placeholder alone (confirmed present on real
    cufflink listings that otherwise use an identical template to watches)
    is exactly the gap that let accessories through before."""
    has_diameter = bool(_CASE_DIAMETER_RE.search(t))
    mechanism_hits = set(m.group(0).lower() for m in _WATCH_MECHANISM_RE.finditer(t))
    signal_count = (1 if has_diameter else 0) + len(mechanism_hits)
    if not require_two_signals:
        return signal_count >= 1
    return signal_count >= 2


# Two noise rules were killing the whole message when only ONE LINE was
# noise, and the collateral damage was enormous: HengWatch posts perfectly
# structured listings (Model / Condition / Year / Case size) and appends an
# "Installment Plan" line -- 2,097 of its 2,100 messages were discarded on
# that alone. watchdistrictsg links to its own shop in most posts; 422 real
# listings died the same way. Strip these lines, then judge what remains.
LINE_NOISE = [
    re.compile(r'(?i)(only\s+SGD?\$?\d+[/\s]*month|per\s+month|/\s*month'
               r'|instal?lments?|interest\s*free|payment\s+plan'
               r'|\d+\s*months?\s+via\s+\w+'
               r'|\b(?:DBS|POSB|OCBC|UOB|HSBC|Maybank|Citibank|Standard\s+Chartered)\b)'),
    re.compile(r'(?i)(watchdistrict\.store|linktree|carousell(?:\.app)?)'),
]


def strip_noise_lines(text):
    """Drop lines that are noise in themselves, keep the rest of the post."""
    kept = [ln for ln in (text or "").split("\n")
            if not any(p.search(ln) for p in LINE_NOISE)]
    return "\n".join(kept)


def classify(text):
    """Main filter. Returns (passed: bool, reason: str|None) — reason is None
    when passed, otherwise a short code identifying which check rejected it."""
    if not text or not text.strip():
        return False, "empty"

    t = text.strip()

    # Decode emoji digits first
    t = decode_emoji_digits(t)

    # 0. Singapore-only. Hard gate: non-SG stock never becomes a listing.
    if not is_singapore_market(t):
        return False, "not_singapore"

    # Drop noise LINES before judging the message, so one financing or
    # shop-link line cannot discard an otherwise-real listing.
    t = strip_noise_lines(t)
    if not t.strip():
        return False, "empty_after_noise_strip"

    # 1. Noise patterns
    for pat in NOISE_PATTERNS:
        if re.search(pat, t):
            return False, "noise_pattern"

    # 2. Strong accessory rejection — even with brand, reject clear accessories that lack watch anatomy
    if ACCESSORY_KW.search(t):
        if not _has_watch_anatomy(t, require_two_signals=True):
            return False, "accessory_no_anatomy"

    # 3. Must have a brand OR watch-specific terms
    if not has_brand(t) and not has_watch_terms(t):
        return False, "no_brand_or_terms"

    # 4. Must mention a real price (not monthly installment)
    if not has_price(t):
        return False, "no_price"

    return True, None


def is_watch_listing(text):
    """Main filter: returns True if this is likely a genuine watch listing."""
    return classify(text)[0]

def extract_price(text):
    """Extract the asking price in SGD. Returns int or None.

    Handles SGD $17,950, $16.8k, 16,800/- and emoji-encoded digits. There is
    deliberately no currency conversion: a non-SGD listing is not Singapore
    stock and is excluded upstream by is_singapore_market(), never converted.
    """
    if not text:
        return None
    
    # Decode emoji digits first
    # Strip noise LINES first, exactly as classify() does. Without this a
    # dealer who appends an "Installment Plans" line to every post has the
    # whole message rejected below, price and all — which is what silenced
    # HengWatch's 2,100 listings.
    # Strip URLs first. Article slugs like
    # ".../rolex-retail-price-increase-2025-price-hike/" put a year right
    # after the word "price", which the labelled-bare-price pattern below
    # then read as an asking price.
    clean = re.sub(r'https?://\S+', ' ', text)
    clean = decode_emoji_digits(normalize_currency_emoji(strip_noise_lines(clean)))
    raw_multiline = clean            # keep newlines for the labelled-bare match
    clean = clean.replace('\n', ' ').replace('\\n', ' ')
    
    # ── Strip retail-price references (keeps listings from capturing MSRP instead of asking price) ──
    # Remove segments like "AD Retail Price @ S$213,000", "RRP $15,000", "MSRP: $12,000" etc.
    retail_strip = re.compile(
        r'(?i)\b('
        r'(?:suggested|ad|authori[sz]ed)\s+retail\s+price'
        r'|rrp|msrp|list\s+price|retail\s+price'
        r')\b\s*[@:]\s*\S*\d\S*(?:\s*\S*\d\S*)*',
        re.I
    )
    clean = retail_strip.sub(' ', clean)
    
    # A masked price ("RM14x,800", "$13x,800") is unusable: the visible digits
    # are not the price. Reject rather than parse a wrong number from it.
    if MASKED_PRICE.search(clean):
        return None

    # Reject if it's an installment plan
    if re.search(r'(?i)(per\s*month|/month|monthly|instal?lments?)', clean):
        return None
    if re.search(r'(?i)only\s+SGD?\$?\d+', clean):
        return None
    # Reject discount/promotional pricing ("$100 off", "save $x", "up to $x off")
    if re.search(r'(?i)(\$?\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:off|discount|savings?)|save\s+\$?\d+|up\s+to\s+\$?\d+\s*(?:off|discount))', clean):
        return None
    
    # Priority patterns — explicit Price: labels FIRST, then currency-prefixed, then bare $
    patterns = [
        # Explicit price label (highest priority — this IS the asking price)
        r'Price[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        r'(?:asking|selling|our|sale)\s+price[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        # SGD formatted: SGD $17,950/-  or  SGD$13,800
        r'(?:SGD? *\$)\s*([\d,]+(?:\.\d{2})?)\/?',
        # Foreign currencies with $: USD $14,400, HKD $50,000
        r'(?:USD? *\$|US *\$|HKD? *\$|HK *\$)\s*([\d,]+(?:\.\d{2})?)\/?',
        # MYR/RM: MYR 5,000 or RM5,000
        r'(?:MYR|RM)\s*\$?\s*([\d,]+(?:\.\d{2})?)\/?',
        # Euro: €5,000 or EUR 5,000
        r'(?:EUR|€)\s*\$?\s*([\d,]+(?:\.\d{2})?)\/?',
        # Foreign currency without $: USD 22,500, HKD 38,000
        r'(?:USD|HKD)\s+([\d,]+(?:\.\d{2})?)\/?',
        # S$ 3,988
        r'S\$\s*([\d,]+(?:\.\d{2})?)',
        # Standard dollar: $16,800 (lowest priority — catches anything)
        r'\$\s*([\d,]+(?:\.\d{2})?)\s*(?:\/|,|$|\s)',
    ]
    
    for pat in patterns:
        m = re.search(pat, clean, re.I)
        if m:
            val = m.group(1).replace(',', '').replace('$', '').strip()
            try:
                num = float(val)
                if 50 <= num <= 5000000:
                    return int(num)
            except:
                continue
    
    # Try "k" suffix: $16.8k
    m = re.search(r'\$?([\d]+(?:\.\d)?)\s*k\b', clean, re.I)
    if m:
        try:
            num = float(m.group(1)) * 1000
            if 50 <= num <= 5000000:
                return int(num)
        except:
            pass
    
    # Labelled bare number: "Priced at\n💲\n22300"
    m = LABELLED_BARE_PRICE.search(raw_multiline)
    if m:
        try:
            num = float(m.group(1))
            # A bare 4-digit number in the year range next to the word
            # "price" is far more often a model year or an article date than
            # an asking price. Require an explicit currency marker to accept
            # one; a genuine $2,025 watch will carry a symbol.
            looks_like_year = 1990 <= num <= 2035
            has_currency = bool(re.search(r'[$€£]|\bSGD?\b', raw_multiline, re.I))
            if 500 <= num <= 5000000 and not (looks_like_year and not has_currency):
                return int(num)
        except ValueError:
            pass

    # Bare number followed by /- pattern: 16,800/-
    m = re.search(r'([\d,]{4,9})(?:\s*\/\-)', clean, re.I)
    if m:
        try:
            num = float(m.group(1).replace(',', ''))
            if 50 <= num <= 5000000:
                return int(num)
        except:
            pass
    
    return None

_COND_NEW = re.compile(r'(?i)\b(brand\s*new|bnib|nib|new\s+old\s+stock|nos|unworn|lnib)\b')
# 'box.*papers' was written as a literal string inside a substring test, so it
# could only ever match the characters "box.*papers" and never real text like
# "box and papers". It is a regex now.
_COND_USED = re.compile(
    r'(?i)\b(pre[\s-]?owned|used|mint|full\s*set|complete\s*set'
    r'|box\b[^\n]{0,20}\bpapers?|papers?\b[^\n]{0,20}\bbox)\b'
)


def extract_condition(text):
    """Classify watch condition: 'n' brand new, 'p' pre-owned, 'u' unknown."""
    t = unicodedata.normalize("NFKC", text or "")
    if _COND_NEW.search(t):
        return 'n'
    if _COND_USED.search(t):
        return 'p'
    return 'u'

# ── Model extraction ────────────────────────────────────────────────────
BRAND_MODEL_MAP = [
    ("Rolex", [r'(?:Submariner|GMT.Master|Daytona|Datejust|Explorer|Yacht.Master|Day.Date|Sea.Dweller|Sky.Dweller|Air.King|Milgauss|Oyster Perpetual|OP)\b']),
    ("Omega", [r'(?:Speedmaster|Seamaster|Planet Ocean|Aqua Terra|Constellation|De Ville|Globemaster|Moonwatch)\b']),
    ("Cartier", [r'(?:Santos|Tank|Panthere|Ballon Bleu|Ronde|Tortue|Calibre|Drive|Pasha)\b']),
    ("Tudor", [r'(?:Black Bay|Pelagos|Royal|1926|North Flag|Fastrider|Heritage|Prince|Ranger)\b']),
    ("Audemars Piguet", [r'(?:Royal Oak|Millenary|Code 11|Jules Audemars|Edward Piguet|Concept)\b']),
    ("Patek Philippe", [r'(?:Nautilus|Aquanaut|Calatrava|Grand Complications|Twenty.4|World Time)\b']),
    ("IWC", [r'(?:Portofino|Pilot|Ingenieur|Aquatimer|Da Vinci|Portugieser|Top Gun)\b']),
    ("Panerai", [r'(?:Luminor|Radiomir|Submersible|Mare Nostrum)\b']),
    ("Hublot", [r'(?:Big Bang|Classic Fusion|Spirit|King Power|Square Bang|MP)\b']),
    ("TAG Heuer", [r'(?:Carrera|Monaco|Aquaracer|Formula 1|Link|Autavia)\b']),
    ("Vacheron Constantin", [r'(?:Overseas|Patrimony|Traditionnelle|Malte|Fiftysix|Historiques)\b']),
    ("Grand Seiko", [r'(?:Heritage|Evolution 9|Elegance|Sport|Prospex|Presage|Astron|5 Sports|Coutura)\b']),
    ("Breguet", [r'(?:Classique|Marine|Type XX|Tradition|Heritage|Reine de Naples|Regulator)\b']),
    ("A. Lange & Sohne", [r'(?:Lange 1|Zeitwerk|Saxonia|Odysseus|1815|Richard Lange|Datograph)\b']),
    ("Breitling", [r'(?:Navitimer|Superocean|Avenger|Chronomat|Premier|Top Time|Colt|Endurance Pro)\b']),
    ("Jaeger-LeCoultre", [r'(?:Reverso|Master|Duometre|Polaris|Memovox|Atmos|Deep Sea)\b']),
    ("Zenith", [r'(?:El Primero|Chronomaster|Defy|Pilot|Grande Class|Captain)\b']),
    ("Franck Muller", [r'(?:Vanguard|Casablanca|Conquistador|Long Island|Crazy Hours|Master Banker)\b']),
    ("Chopard", [r'(?:Happy Sport|Happy Diamond|Mille Miglia|L.U.C|Alpine Eagle|Imperiale)\b']),
    ("Ulysse Nardin", [r'(?:Marine|Freak|Diver|Executive|Classico)\b']),
    ("Bvlgari", [r'(?:Octo|Serpenti|Diagono|B.Zero1)\b']),
    ("Bulgari", [r'(?:Octo|Serpenti|Diagono|B.Zero1)\b']),
    ("MB&F", [r'(?:Horological Machine|Legacy Machine|Sherman|HM|LM)\b']),
    ("Girard-Perregaux", [r'(?:Laureato|1966|Sea Hawk|Bridges)\b']),
    ("Bell & Ross", [r'(?:BR 03|BR 05|BR V|BR X|BR S)\b']),
    ("H. Moser", [r'(?:Endeavour|Pioneer|Streamliner|Venturer)\b']),
    ("Longines", [r'(?:Master|HydroConquest|Conquest|Legend Diver|Spirit)\b']),
    ("Oris", [r'(?:Aquis|Divers|Big Crown|ProPilot|Artelier)\b']),
    ("Nomos", [r'(?:Tangente|Orion|Metro|Ludwig|Zurich|Ahoi|Club|Tetra)\b']),
    ("Hamilton", [r'(?:Khaki|Jazzmaster|Ventura|Intra.Matic|Pan Europ)\b']),
    ("Tissot", [r'(?:PRX|PRC|Le Locle|Gentleman|Seastar|Chemin des Tourelles)\b']),
    ("Piaget", [r'(?:Altiplano|Polo|Limelight|Possession|Emperador)\b']),
    ("Sinn", [r'(?:U1|U2|U50|856|104|556|144|103|EZM|Flieger)\b']),
]


REF_PATTERN = re.compile(r'\b(\d{3,6}(?:\.\d{2,4}){0,2}[A-Z]{0,4})\b')
YEAR_RE = re.compile(r'\b(19\d{2}|20[0-3]\d)\b')


def extract_model(text, brand=None):
    """Extract watch model from listing text, optionally validating against brand."""
    if not text:
        return None, None
    if brand:
        for bw, patterns in BRAND_MODEL_MAP:
            if bw.lower() in brand.lower():
                for pat in patterns:
                    m = re.search(pat, text, re.I)
                    if m:
                        model = m.group(0)
                        ref = None
                        for ref_m in REF_PATTERN.finditer(text):
                            rv = ref_m.group(1)
                            if YEAR_RE.fullmatch(rv):
                                continue
                            ref = rv
                            break
                        return model, ref
                # Only try this brand's patterns - nothing matched
                return None, None
    # Last resort: reference number
    for ref_m in REF_PATTERN.finditer(text):
        rv = ref_m.group(1)
        if YEAR_RE.fullmatch(rv):
            continue
        if '.' in rv or re.search(r'(?i)\b(ref|model)\b', text):
            return None, rv
    return None, None


def clean_listing_title(text):
    """Return a short, clean title from raw listing text (first meaningful line)."""
    if not text:
        return ""
    lines = text.strip().split('\n')
    # Find first line that looks substantive
    for line in lines:
        clean = line.strip()
        if not clean or len(clean) < 5:
            continue
        if re.match(r'^[📢🕘⏰🔄✅💰🔥🎉]', clean):
            continue
        if 't.me/' in clean or 'bit.ly/' in clean or 'http' in clean:
            continue
        if re.match(r'^(Join|Follow|Subscribe|DM|PM|WhatsApp|WA:|Telegram|Contact)\b', clean, re.I):
            continue
        return clean[:120]
    return lines[0].strip()[:120] if lines else ""
