COUNTRY_KEYWORDS = {
    "worldwide": ["worldwide", "world wide", "global", "international", "all countries", "worldwide entry", "open to all"],
    "germany": ["germany", "deutschland", "german only", "de only", "german residents", "wohnhaft in deutschland", "nur deutschland", " residents of germany"],
    "us": ["us only", "usa only", "united states only", "us residents", "usa residents", " residents of the us"],
    "uk": ["uk only", "united kingdom only", "uk residents", "british residents", "residents of the uk", " residents of the united kingdom"],
    "eu": ["eu only", "european union", "europe only", "eu residents", "european residents"],
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


def detect_country_restriction(html_text):
    text = html_text.lower()

    for keyword in RESTRICTED_KEYWORDS:
        if keyword in text:
            return "restricted"

    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return country

    return "worldwide"


def is_eligible_for_country(restriction, target_country="germany"):
    if restriction == "worldwide":
        return True
    if restriction == "restricted":
        return False
    if restriction == target_country:
        return True
    if restriction == "eu" and target_country in ["germany"]:
        return True
    return False
