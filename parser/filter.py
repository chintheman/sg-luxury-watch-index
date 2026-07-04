#!/usr/bin/env python3
"""Filter pipeline - determine if a Telegram message is a genuine watch listing."""
import re

# --- CURRENCY CONVERSION ---
CURRENCY_RATES = {
    "USD": 1.35,   # 1 USD ≈ 1.35 SGD
    "EUR": 1.47,   # 1 EUR ≈ 1.47 SGD
    "HKD": 0.173,  # 1 HKD ≈ 0.173 SGD
    "MYR": 0.29,   # 1 MYR ≈ 0.29 SGD
}

CURRENCY_PATTERNS = [
    (re.compile(r'\b(?:USD?|US)\s*\$', re.I), "USD"),
    (re.compile(r'\b(?:HKD?|HK)\s*\$', re.I), "HKD"),
    (re.compile(r'€|\bEUR\b', re.I), "EUR"),
    (re.compile(r'\b(?:MYR|RM)\b', re.I), "MYR"),
    (re.compile(r'\bUSD\b', re.I), "USD"),
    (re.compile(r'\bHKD\b', re.I), "HKD"),
    (re.compile(r'\bEUR\b', re.I), "EUR"),
    (re.compile(r'\bMYR\b', re.I), "MYR"),
]

def detect_currency(text):
    """Detect if a listing is priced in a non-SGD currency. Returns currency code or None."""
    if not text:
        return None
    # First check for explicit "All Prices are in Singapore Dollars" override
    if re.search(r'(?i)all prices are in singapore dollars', text):
        return None
    for pat, code in CURRENCY_PATTERNS:
        if pat.search(text):
            return code
    return None

# --- EMOJI DIGIT DECODER ---
EMOJI_DIGITS = {
    '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
    '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
}

def decode_emoji_digits(text):
    """Convert emoji keycap digits (0U+FE0F+U+20E3) to plain digits."""
    # Match: digit followed by variation selector U+FE0F then enclosing keycap U+20E3
    pat = re.compile(r'([0-9])\xef\xb8\x8f\xe2\x83\xa3')
    return pat.sub(lambda m: m.group(1), text)

# --- NOISE PATTERNS ---
NOISE_PATTERNS = [
    # Financing / installment spam
    r'(?i)(only\s+SGD?\$?\d+[/\s]*month|per\s+month|36\s*months?\s+via\s+DBS|POSB\s+credit\s+card|interest\s*free!\s*$|installment\s+plan)',
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
    # Link aggregator posts (linktree, carousell pages, store links with no watch)
    r'(?i)(?:watchdistrict\.store|linktree|carousell|carousell\.app)\b',
    # Service / repair
    r'(?i)\b(service centre|warranty registration|repair service|servicing special)\b',
    # Accessories with no watch
    r'(?i)\b(watch winder|watch box|watch roll|watch pouch|travel case|cufflink)\b',
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
ACCESSORY_KW = re.compile(
    r'(?i)\b(strap|leather\s*band|rubber\s*band|buckle|clasp|cuff\s*links?|cufflink|desk\s*clock|watch\s*winder|wind\s*er|travel\s*pouch|watch\s*roll|watch\s*box|deployant|end\s*link|spring\s*bar|pen(?:cil)?\s*set|crown[-\s]?(stem|tube)|bezel\s*insert|dial\s*(only|for\s*sale)|movement\s*(only|for\s*sale)|hands\s*set|crystal\s*(only|replacement))\b'
)

def has_brand(text):
    """Quick check if message mentions any watch brand."""
    brands_full = [
        'Rolex', 'Omega', 'Patek Philippe', 'Tudor', 'Cartier', 'Breitling',
        'Audemars Piguet', 'IWC', 'Panerai', 'Hublot', 'Tag Heuer', 'TAG Heuer',
        'Seiko', 'Grand Seiko', 'Chopard', 'Blancpain', 'Breguet',
        'Vacheron Constantin', 'Jaeger-LeCoultre', 'Franck Muller', 'A. Lange',
        'Richard Mille', 'Bell & Ross', 'Casio', 'Oris',
        'Zenith', 'Piaget', 'Longines', 'Tissot', 'Hamilton',
        'G-Shock', 'Baltic', 'Nomos', 'Ulysse Nardin', 'Girard-Perregaux',
        'Bulgari', 'Bvlgari', 'Corum', 'MB&F', 'FP Journe', 'Urwerk',
        'H. Moser', 'Sinn', 'Swarovski', 'Gucci', 'Hermes', 'Montblanc',
    ]
    up = (text or '').upper()
    for b in brands_full:
        if b.upper() in up:
            return True
    # Short abbreviations — word boundary only (no substring matches)
    short_brands = [
        ('AP', 'Audemars Piguet'),
        ('RM', 'Richard Mille'),
        ('JLC', 'Jaeger-LeCoultre'),
        ('GS', 'Grand Seiko'),
    ]
    for abbr, _ in short_brands:
        if re.search(r'\b' + abbr + r'\b', up):
            return True
    return False

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
    clean = text.replace('\n', ' ').replace('|', ' ')
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

def is_watch_listing(text):
    """Main filter: returns True if this is likely a genuine watch listing."""
    if not text or not text.strip():
        return False
    
    t = text.strip()
    
    # Decode emoji digits first
    t = decode_emoji_digits(t)
    
    # 1. Noise patterns
    for pat in NOISE_PATTERNS:
        if re.search(pat, t):
            return False
    
    # 2. Strong accessory rejection — even with brand, reject clear accessories that lack watch anatomy
    if ACCESSORY_KW.search(t):
        has_watch_anatomy = bool(
            re.search(r'(?i)(automatic|quartz|manual.*winding|mechanical|chronograph|chronometer|tourbillon|perpetual|certified|caliber|water.resist|ref\s*\.?\s*\d)'
                      r'|(case\s*(diamet|size|width)|diamet)\s*[:\s]*([12]\d|3[0-9]|4[0-5])\s*mm', t)
        )
        if not has_watch_anatomy:
            return False
    
    # 3. Must have a brand OR watch-specific terms
    if not has_brand(t) and not has_watch_terms(t):
        return False
    
    # 4. Must mention a real price (not monthly installment)
    if not has_price(t):
        return False
    
    return True

def extract_price(text, convert_to_sgd=True):
    """Extract price from listing text. Returns int or None.
    Handles: SGD $17,950, $16.8k, 16,800/- etc.
    Also handles emoji-encoded digits.
    If convert_to_sgd=True and a non-SGD currency is detected, converts to SGD."""
    if not text:
        return None
    
    # Decode emoji digits first
    clean = decode_emoji_digits(text)
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
    
    # Detect currency
    detected_currency = detect_currency(clean) if convert_to_sgd else None
    
    # Reject if it's an installment plan
    if re.search(r'(?i)(per\s*month|/month|monthly|installment|36\s*month|DBS|POSB\s*credit)', clean):
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
                    result = int(num)
                    # Convert to SGD if foreign currency detected
                    if detected_currency and detected_currency in CURRENCY_RATES:
                        result = int(result * CURRENCY_RATES[detected_currency])
                    return result
            except:
                continue
    
    # Try "k" suffix: $16.8k
    m = re.search(r'\$?([\d]+(?:\.\d)?)\s*k\b', clean, re.I)
    if m:
        try:
            num = float(m.group(1)) * 1000
            if 50 <= num <= 5000000:
                result = int(num)
                if detected_currency and detected_currency in CURRENCY_RATES:
                    result = int(result * CURRENCY_RATES[detected_currency])
                return result
        except:
            pass
    
    # Bare number followed by /- pattern: 16,800/-
    m = re.search(r'([\d,]{4,9})(?:\s*\/\-)', clean, re.I)
    if m:
        try:
            num = float(m.group(1).replace(',', ''))
            if 50 <= num <= 5000000:
                result = int(num)
                if detected_currency and detected_currency in CURRENCY_RATES:
                    result = int(result * CURRENCY_RATES[detected_currency])
                return result
        except:
            pass
    
    return None

def extract_condition(text):
    """Classify watch condition from text."""
    t = (text or '').lower()
    if any(w in t for w in ['brand new', 'bnib', 'nib', 'new old stock', 'nos', 'unworn']):
        return 'n'
    if any(w in t for w in ['pre-owned', 'preowned', 'used', 'mint', 'full set', 'box.*papers', 'complete set']):
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
