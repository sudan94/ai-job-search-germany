"""Germany-only filtering.

Applied to raw postings before anything is stored, so the database stays free
of roles that are not applicable from Germany.

The rule (matching the `germany_only` setting): keep a posting when it is
located in Germany, or when it is remote *and* the employer or the posting is
German. A remote job that names another country - "Remote, Brasil",
"Remote - Spain" - is dropped, and so is an unqualified "Remote EU" from a
company with no German footprint.
"""

from __future__ import annotations

import re

#: Country, states, and the cities these boards actually return.
GERMAN_PLACES = {
    "deutschland", "germany", "german", "allemagne", "brd", "bundesweit",
    # federal states
    "baden-württemberg", "baden-wuerttemberg", "bayern", "bavaria", "berlin",
    "brandenburg", "bremen", "hamburg", "hessen", "hesse", "mecklenburg",
    "niedersachsen", "lower saxony", "nordrhein-westfalen", "north rhine",
    "nrw", "rheinland-pfalz", "rhineland", "saarland", "sachsen", "saxony",
    "sachsen-anhalt", "schleswig-holstein", "thüringen", "thuringia",
    # cities
    "münchen", "muenchen", "munich", "köln", "koeln", "cologne", "frankfurt",
    "stuttgart", "düsseldorf", "duesseldorf", "dusseldorf", "dortmund", "essen",
    "leipzig", "dresden", "hannover", "hanover", "nürnberg", "nuernberg",
    "nuremberg", "duisburg", "bochum", "wuppertal", "bielefeld", "bonn",
    "münster", "muenster", "karlsruhe", "mannheim", "augsburg", "wiesbaden",
    "mönchengladbach", "gelsenkirchen", "braunschweig", "chemnitz", "kiel",
    "aachen", "halle", "magdeburg", "freiburg", "krefeld", "lübeck", "luebeck",
    "oberhausen", "erfurt", "rostock", "kassel", "hagen", "potsdam", "saarbrücken",
    "saarbruecken", "hamm", "ludwigshafen", "mülheim", "oldenburg", "osnabrück",
    "osnabrueck", "solingen", "heidelberg", "herne", "neuss", "darmstadt",
    "paderborn", "regensburg", "ingolstadt", "würzburg", "wuerzburg", "fürth",
    "wolfsburg", "offenbach", "ulm", "heilbronn", "pforzheim", "göttingen",
    "goettingen", "bottrop", "trier", "recklinghausen", "reutlingen", "bremerhaven",
    "koblenz", "bergisch gladbach", "jena", "remscheid", "erlangen", "moers",
    "siegen", "hildesheim", "salzgitter", "cottbus", "eschborn", "walldorf",
}

#: Places that positively rule a posting out when they appear in the location.
NON_GERMAN_PLACES = {
    "brasil", "brazil", "argentina", "mexico", "colombia", "chile", "peru",
    "united states", "usa", "u.s.", "canada", "san francisco", "new york",
    "seattle", "austin", "boston", "chicago", "los angeles", "toronto", "denver",
    "united kingdom", "london", "manchester", "edinburgh", "ireland", "dublin",
    "france", "paris", "lyon", "montpellier", "spain", "madrid", "barcelona",
    "valencia", "portugal", "lisbon", "lisboa", "porto", "italy", "milan",
    "milano", "rome", "netherlands", "amsterdam", "rotterdam", "utrecht",
    # German-speaking but not Germany - and they use "GmbH" too, so they must be
    # named explicitly or the employer-signal fallback would let them through.
    "austria", "vienna", "wien", "graz", "linz", "salzburg", "innsbruck",
    "switzerland", "zurich", "zürich", "geneva", "basel", "bern", "lausanne",
    "lugano", "winterthur", "zug", "liechtenstein", "vaduz",
    "belgium", "brussels", "poland", "warsaw", "krakow", "kraków", "wrocław",
    "czech", "prague", "praha", "slovakia", "hungary", "budapest", "romania",
    "bucharest", "bulgaria", "sofia", "greece", "athens", "sweden", "stockholm",
    "denmark", "copenhagen", "norway", "oslo", "finland", "helsinki", "estonia",
    "tallinn", "latvia", "riga", "lithuania", "vilnius", "india", "bangalore",
    "singapore", "japan", "tokyo", "australia", "sydney", "melbourne", "china",
    "israel", "tel aviv", "dubai", "uae", "south africa", "cape town", "nigeria",
    "kenya", "egypt", "turkey", "istanbul", "ukraine", "kyiv", "serbia",
    "belgrade", "croatia", "zagreb", "luxembourg", "philippines", "indonesia",
    "vietnam", "thailand", "malaysia", "korea", "taiwan", "new zealand",
}


def _place_pattern(places: set[str]) -> re.Pattern[str]:
    """Whole-word matcher for a set of place names.

    Substring matching is not safe here: "challenges" contains "halle",
    "Copenhagen" contains "hagen", and "essential" contains "essen". Each of
    those would otherwise mark a posting as German.
    """
    ordered = sorted(places, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in ordered) + r")\b", re.IGNORECASE)


_GERMAN_RE = _place_pattern(GERMAN_PLACES)
_NON_GERMAN_RE = _place_pattern(NON_GERMAN_PLACES)

#: German legal forms - a strong signal the employer is a German entity.
_LEGAL_FORM_RE = re.compile(
    r"\b(gmbh|g?mbh\s*&\s*co|ug\s*\(haftungsbeschränkt\)|kgaa|e\.?\s?v\.?|se\s*&\s*co)\b",
    re.IGNORECASE,
)


def _mentions_germany(text: str) -> bool:
    return bool(_GERMAN_RE.search(text or ""))


def has_german_employer_signal(
    *, source: str = "", company: str = "", description: str = "", location: str = ""
) -> bool:
    """Is the employer or the posting itself German?"""
    if source == "arbeitsagentur":
        return True  # the Bundesagentur index is the German labour market
    if _LEGAL_FORM_RE.search(company or ""):
        return True
    if _mentions_germany(company) or _mentions_germany(location):
        return True
    # Only the head of the description: a footer listing every global office
    # should not make a Spanish role look German.
    return _mentions_germany((description or "")[:3000])


def is_germany_related(
    *,
    location: str = "",
    source: str = "",
    company: str = "",
    description: str = "",
) -> bool:
    """Should this posting be kept when `germany_only` is on?

    The location text already carries the remote signal ("Remote, Brasil",
    "Remote - Germany"), so a separate remote flag adds nothing here.
    """
    place = (location or "").strip().lower()

    if _mentions_germany(place):
        return True

    if _NON_GERMAN_RE.search(place):
        return False  # "Remote, Brasil" and "Madrid" alike

    # Everything left is a location we cannot place: empty, bare "Remote", or a
    # town too small to list (Gilching, Walldorf, Eschborn...). Fall back to the
    # employer: a GmbH, or a posting that talks about Germany, is worth keeping.
    return has_german_employer_signal(
        source=source, company=company, description=description, location=location
    )
