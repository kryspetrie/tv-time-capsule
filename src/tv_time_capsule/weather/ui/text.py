"""Short display strings for CRT weather panels (VCR OSD–safe ASCII)."""

from __future__ import annotations

import re
from collections.abc import Callable

from ...fonts import vcr_safe_text

# Long NWS / WMO phrases → compact panel text (longer phrases first).
_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("slight chance of showers and thunderstorms", "Shwrs & ThdSt"),
    ("slight chance of showers & thunderstorms", "Shwrs & ThdSt"),
    ("chance of showers and thunderstorms", "Shwrs & ThdSt"),
    ("chance of showers & thunderstorms", "Shwrs & ThdSt"),
    ("showers and thunderstorms", "Shwrs & ThdSt"),
    ("showers & thunderstorms", "Shwrs & ThdSt"),
    ("severe thunderstorms", "Sev ThdSt"),
    ("severe thunderstorm", "Sev ThdSt"),
    ("slight chance of", "Slgt Chance"),
    ("chance of", "Chance"),
    ("thunderstorms", "ThdSt"),
    ("thunderstorm", "ThdSt"),
    ("rain showers", "Rain Shwrs"),
    ("snow showers", "Snow Shwrs"),
    ("freezing rain", "Frz Rain"),
    ("heavy rain", "Hvy Rain"),
    ("light rain", "Lt Rain"),
    ("heavy snow", "Hvy Snow"),
    ("light snow", "Lt Snow"),
    ("heavy showers", "Hvy Shwrs"),
    ("rain and snow", "Rain/Snow"),
    ("snow and rain", "Snow/Rain"),
    ("showers", "Shwrs"),
    ("increasing clouds", "Incr Cldy"),
    ("becoming sunny", "Bcmg Sunny"),
    ("becoming clear", "Bcmg Clear"),
    ("scattered", "Sct"),
    ("isolated", "Isol"),
    ("partly cloudy", "Ptly Cldy"),
    ("mostly cloudy", "Mstly Cldy"),
    ("partly sunny", "Ptly Sunny"),
    ("mostly sunny", "Mstly Sunny"),
    ("mostly clear", "Mstly Clear"),
    ("areas of", ""),
    ("patchy", ""),
)

# Drop common NWS filler after phrase compression.
_FILLER_RE = re.compile(
    r"\b(?:then|likely|with|and|of)\b",
    re.IGNORECASE,
)


def ascii_safe(text: str) -> str:
    """Replace characters the bundled VCR font cannot draw."""
    return vcr_safe_text(text)

def _compress_condition(text: str) -> str:
    """Apply phrase / filler compression (always)."""
    s = ascii_safe((text or "").strip())
    if not s:
        return ""
    low = s.lower()
    for src, dst in _PHRASE_REPLACEMENTS:
        if src in low:
            s = re.sub(re.escape(src), dst, s, flags=re.IGNORECASE)
            low = s.lower()
    # Preserve intentional ampersands; strip leftover filler words.
    s = s.replace("&", "\x00")
    s = _FILLER_RE.sub(" ", s)
    s = s.replace("\x00", "&")
    return re.sub(r"\s+", " ", s).strip(" ,")


def _clip_words(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 3].rsplit(" ", 1)[0]
    return (cut or text[: max_len - 3]).rstrip() + "..."


def abbreviate_condition(text: str, *, max_len: int = 22) -> str:
    """Prefer full wording; compress only when it cannot fit ``max_len`` chars."""
    full = ascii_safe((text or "").strip())
    if not full:
        return ""
    if len(full) <= max_len:
        return full
    short = _compress_condition(full)
    if len(short) <= max_len:
        return short
    return _clip_words(short, max_len)


def fit_condition(
    text: str,
    *,
    max_len: int | None = None,
    fits: Callable[[str], bool] | None = None,
) -> str:
    """Return full text when ``fits(text)`` / ``max_len`` allows; else compress.

    ``fits`` should return True when the candidate string clearly fits the
    available layout (pixel width and/or wrapped line budget).
    """
    full = ascii_safe((text or "").strip())
    if not full:
        return ""
    if fits is not None:
        if fits(full):
            return full
        short = _compress_condition(full)
        if fits(short):
            return short
        if max_len is not None:
            return _clip_words(short, max_len)
        # Last resort: keep the compressed form even if still tight.
        return short
    if max_len is None:
        return full
    return abbreviate_condition(full, max_len=max_len)


def rain_chance_label(precip_pct: float | None, *, min_pct: float = 15.0) -> str:
    """Bare chance label (``45%``); skip tiny noise values."""
    if precip_pct is None:
        return ""
    pct = int(round(precip_pct))
    if pct < min_pct:
        return ""
    return f"{pct}%"


def rain_amount_label(precip_in: float | None) -> str:
    """Compact inches label (``.17in``)."""
    if precip_in is None or precip_in <= 0:
        return ""
    amt = f"{precip_in:.2f}".lstrip("0") + "in"
    if amt.startswith("."):
        return amt
    if amt and amt[0].isdigit():
        return amt
    return f"{precip_in:.2f}in"


def rain_summary(
    precip_pct: float | None,
    precip_in: float | None = None,
    *,
    min_pct: float = 15.0,
) -> str:
    """Compact rain text; chance and amount on separate lines when both set.

    Examples: ``45%``, ``.16in``, ``45%\\n.16in``.
    """
    chance = rain_chance_label(precip_pct, min_pct=min_pct)
    amt = rain_amount_label(precip_in)
    if chance and amt:
        return f"{chance}\n{amt}"
    return chance or amt


# US state / territory full names → postal codes.
_US_STATES: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "puerto rico": "PR",
    "guam": "GU",
    "american samoa": "AS",
    "u.s. virgin islands": "VI",
    "us virgin islands": "VI",
    "virgin islands": "VI",
}

# Country / region full names → short codes (CRT-friendly).
_COUNTRIES: dict[str, str] = {
    "united states": "US",
    "united states of america": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "usa": "US",
    "canada": "CA",
    "mexico": "MX",
    "united kingdom": "UK",
    "great britain": "UK",
    "england": "UK",
    "scotland": "UK",
    "wales": "UK",
    "northern ireland": "UK",
    "ireland": "IE",
    "australia": "AU",
    "new zealand": "NZ",
    "germany": "DE",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "japan": "JP",
    "china": "CN",
    "india": "IN",
    "brazil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    "south africa": "ZA",
    "netherlands": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "austria": "AT",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "portugal": "PT",
    "greece": "GR",
    "turkey": "TR",
    "israel": "IL",
    "saudi arabia": "SA",
    "united arab emirates": "AE",
    "south korea": "KR",
    "korea": "KR",
    "taiwan": "TW",
    "hong kong": "HK",
    "singapore": "SG",
    "philippines": "PH",
    "thailand": "TH",
    "vietnam": "VN",
    "indonesia": "ID",
    "malaysia": "MY",
    "russia": "RU",
    "ukraine": "UA",
}


def abbreviate_region(token: str) -> str:
    """``Massachusetts`` → ``MA``, ``United States`` → ``US``."""
    t = ascii_safe((token or "").strip())
    if not t:
        return ""
    # Already a short code (MA, US, NSW).
    if re.fullmatch(r"[A-Za-z]{2,3}", t):
        return t.upper()
    low = t.lower().rstrip(".")
    if low in _US_STATES:
        return _US_STATES[low]
    if low in _COUNTRIES:
        return _COUNTRIES[low]
    # Keep short admin names; clamp longer unknowns.
    if len(t) <= 4:
        return t.upper() if t.isalpha() else t
    return shorten_place_name(t, max_len=10)


def shorten_place_name(name: str, *, max_len: int = 18) -> str:
    """Truncate long town names only when they exceed ``max_len``."""
    s = ascii_safe((name or "").strip())
    if not s or len(s) <= max_len:
        return s
    # Drop common suffixes that burn width (only when over budget).
    s2 = re.sub(
        r"\b(Township|Charter Township|Borough|Village|Municipality)\b\.?",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s2 = re.sub(r"\s+", " ", s2).strip(" ,")
    if len(s2) <= max_len:
        return s2 or s[:max_len]
    cut = s2[: max_len - 3].rsplit(" ", 1)[0]
    return (cut or s2[: max_len - 3]).rstrip(" ,.-") + "..."


def format_place_line(
    city: str,
    context: str = "",
    *,
    max_len: int = 28,
    city_max: int = 22,
) -> str:
    """Build a compact ``City, ST`` / ``City, Country`` line for the lower-thirds.

    Keeps the full town name when the finished line fits ``max_len``.
    """
    city_full = ascii_safe((city or "").strip())
    raw_ctx = ascii_safe((context or "").strip())
    parts = [p.strip() for p in raw_ctx.split(",") if p.strip()]

    # Drop city echo from context ("Boston, Massachusetts, United States").
    if parts and city_full and parts[0].lower() == city_full.lower():
        parts = parts[1:]

    regions = [abbreviate_region(p) for p in parts]
    regions = [r for r in regions if r]

    # Prefer state/province; keep country only when not US (or alone).
    state = ""
    country = ""
    for r in regions:
        if r in _US_STATES.values() and not state:
            state = r
        elif r in _COUNTRIES.values() or (len(r) <= 3 and r.isalpha() and r.isupper()):
            if r == "US" and state:
                continue
            if not country:
                country = r
        elif not state:
            state = r

    tail_bits = [b for b in (state, country if country and country != "US" else "") if b]
    # Deduplicate ("MA", "MA").
    tail: list[str] = []
    for b in tail_bits:
        if not tail or tail[-1].lower() != b.lower():
            tail.append(b)

    def _join(city_s: str) -> str:
        if city_s and tail:
            if len(tail) == 1 and tail[0].lower().startswith(city_s.lower()):
                return city_s
            return f"{city_s}, {', '.join(tail)}"
        return city_s or ", ".join(tail) or "Local"

    line = _join(city_full)
    if len(line) <= max_len:
        return line
    # Shrink city only as far as needed so ", ST" still fits.
    reserve = len(", ".join(tail)) + 2 if tail else 0
    room = max(6, min(city_max, max_len - reserve))
    return _join(shorten_place_name(city_full, max_len=room))
