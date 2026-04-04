# --- EU member states (ISO-style lowercase keys) ---
EU_MEMBERS = [
    "germany", "austria", "france", "italy", "spain", "netherlands",
    "belgium", "poland", "sweden", "denmark", "finland", "ireland",
    "portugal", "greece", "czech republic", "romania", "hungary",
    "croatia", "slovakia", "slovenia", "bulgaria", "lithuania",
    "latvia", "estonia", "luxembourg", "malta", "cyprus",
]

# --- DACH member states ---
DACH_MEMBERS = ["germany", "austria", "switzerland"]

# --- Country keywords for eligibility detection ---
# Order matters: check specific regions BEFORE broad ones to avoid
# "worldwide" matching on a page that also says "Germany only".
# Dict is iterated in insertion order (Python 3.7+).
COUNTRY_KEYWORDS = {
    # Most specific first
    "germany": [
        "germany only", "german only", "de only",
        "nur deutschland", "nur für deutschland",
        "german residents", "residents of germany",
        "wohnhaft in deutschland",
        "nur für teilnehmer aus deutschland",
        "teilnahmeberechtigt sind personen mit wohnsitz in deutschland",
    ],
    "dach": [
        "dach", "d-a-ch", "dach-raum", "dach-region",
        "germany, austria and switzerland",
        "germany, austria, and switzerland",
        "germany, austria & switzerland",
        "deutschland, österreich und schweiz",
        "deutschland, österreich und der schweiz",
        "deutschland, österreich, schweiz",
    ],
    "eu": [
        "eu only", "eu residents",
        "european union only", "european union residents",
        "europe only", "european residents",
        "european economic area", "eea only",
        "europäische union", "eu-länder",
        "innerhalb der eu", "eu-raum",
    ],
    "us": [
        "us only", "usa only", "united states only",
        "us residents", "usa residents",
        "residents of the us", "residents of the united states",
    ],
    "uk": [
        "uk only", "united kingdom only",
        "uk residents", "british residents",
        "residents of the uk", "residents of the united kingdom",
        "great britain only",
    ],
    # Broadest last
    "worldwide": [
        "worldwide", "world wide", "global", "international",
        "all countries", "worldwide entry", "open to all",
        "no country restriction", "weltweit", "keine länderbeschränkung",
    ],
}

RESTRICTED_KEYWORDS = [
    "not available in your region",
    "not available in your country",
    "sorry, this promotion",
    "not open to",
    "only open to",
    "excluded countries",
    "not eligible in",
    "restricted to",
]

# Keywords indicating the giveaway page is region-blocked (gleam.io shows
# a full-page message when your IP is not in an allowed region).
REGION_BLOCKED_KEYWORDS = [
    "sorry, this promotion is not available in your region",
    "this promotion is not available in your region",
    "not available in your region",
    "promotion is not available in your country",
    "not available in your country",
    "!contestantstate.location_allowed",
    "location_allowed",
]

# Keywords indicating the giveaway/competition has ended.
ENDED_KEYWORDS = [
    "this competition has ended",
    "this giveaway has ended",
    "this promotion has ended",
    "this sweepstakes has ended",
    "competition has ended",
    "giveaway has ended",
    "promotion has ended",
    "sweepstakes has ended",
    "this competition is over",
    "this giveaway is over",
    "this promotion is over",
    "contest has ended",
    "this contest has ended",
    "this contest is over",
    "entries are now closed",
    "entry period has ended",
    "this campaign has ended",
]


def is_region_blocked(html_text):
    """Check if a gleam.io page is region-blocked.

    Gleam shows a ``massive-message`` div with text like
    "Sorry, this promotion is not available in your region"
    when the visitor's IP is outside the allowed countries.

    Returns True if the page is region-blocked.
    """
    text = html_text.lower()
    return any(kw in text for kw in REGION_BLOCKED_KEYWORDS)


def is_ended(html_text):
    """Check if a gleam.io giveaway has ended.

    Gleam shows a ``massive-message`` div with text like
    "This Competition has ended" when the giveaway is over.

    Returns True if the giveaway has ended.
    """
    text = html_text.lower()
    return any(kw in text for kw in ENDED_KEYWORDS)


def detect_country_restriction(html_text):
    """Detect country/region restriction from page text.

    Returns one of: "germany", "dach", "eu", "us", "uk",
    "worldwide", or "restricted".
    """
    text = html_text.lower()

    # First pass: check for specific country/region keywords.
    # These are more informative than generic restriction phrases.
    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return country

    # Second pass: generic restriction phrases (no specific country found).
    for keyword in RESTRICTED_KEYWORDS:
        if keyword in text:
            return "restricted"

    return "worldwide"


def is_eligible_for_country(restriction, target_country="germany"):
    """Check if a giveaway with *restriction* is eligible for *target_country*.

    Hierarchy:
        worldwide  -> eligible for everyone
        restricted -> eligible for nobody
        exact match -> eligible
        dach       -> eligible for germany, austria, switzerland
        eu         -> eligible for EU member states
    """
    if restriction == "worldwide":
        return True
    if restriction == "restricted":
        return False
    if restriction == target_country:
        return True

    # DACH includes Germany, Austria, Switzerland
    if restriction == "dach" and target_country in DACH_MEMBERS:
        return True

    # EU includes all EU member states
    if restriction == "eu" and target_country in EU_MEMBERS:
        return True

    return False
