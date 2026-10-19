"""The cities the site covers, and the areas within each.

A city is the top level: its theatres, its time zone (a showtime's start is
that city's wall-clock time) and how it's named. Areas are the sections
inside a city — DC / Maryland / Virginia — that Browse's "Where" filter and
the Theatres page use (the URL keeps its old name, `regions=`).

Adding a city = one City here, then its theatres in the scraper registry
(scrapers/__init__.py), each naming the city and one of its areas. This
module must NOT import app (the scraper registry and the bot's tests read it).
"""
from dataclasses import dataclass
from functools import lru_cache
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Area:
    key: str            # in URLs: ?regions=maryland
    label: str
    words: str          # what a plain-English ask calls it (a regex): "silver spring" -> Maryland


@dataclass(frozen=True)
class City:
    slug: str           # in URLs and the database: 'dc'
    name: str           # "Washington, DC"
    short: str          # "DC" — the city menu, tags beside theatre names
    tz: str             # its showtimes' clock
    phrase: str         # "DC-area" — "12 DC-area theatres"
    lat: float
    lon: float
    areas: tuple
    words: str = ''     # what an ask calls the city itself, once there's more than one
    hint: str = ''      # for the AI search: neighborhoods it might hear, and which area they're in
    known_for: str = '' # a few of its theatres, for page descriptions ("AFI, Suns, … and more")


CITIES = [
    City('dc', 'Washington, DC', 'DC', 'America/New_York', 'DC-area', 38.9072, -77.0369, areas=(
        Area('dc', 'DC', r"\bd\.?c\.?\b|\bthe district\b"),
        Area('maryland', 'Maryland', r"\bmaryland\b|\bmd\b|\bsilver spring\b|\bbethesda\b|\brockville\b"),
        Area('virginia', 'Virginia', r"\bvirginia\b|\bva\b|\bnova\b|\barlington\b|\balexandria\b|\bfairfax\b"
                                     r"|\bcrystal city\b"),
    ), words=r"\bwashington\b",
       hint='Downtown, Penn Quarter, Georgetown and the like are DC; Silver Spring and Bethesda are Maryland; '
            'Arlington, Alexandria and Fairfax are Virginia.',
       known_for='AFI, Suns, Alamo, the Smithsonian and more'),
]
DEFAULT_CITY = CITIES[0].slug
_BY_SLUG = {c.slug: c for c in CITIES}


def get(slug):
    """The City for a slug, or None."""
    return _BY_SLUG.get(slug)


def clean(slug):
    """A known city's slug from anything a request might send, else None."""
    slug = str(slug or '').strip().lower()
    return slug if slug in _BY_SLUG else None


@lru_cache(maxsize=None)
def zone(slug):
    return ZoneInfo((_BY_SLUG.get(slug) or _BY_SLUG[DEFAULT_CITY]).tz)


def area(city_slug, key):
    """The Area `key` in a city, or None."""
    c = _BY_SLUG.get(city_slug)
    return next((a for a in c.areas if a.key == key), None) if c else None


def area_label(city_slug, key):
    a = area(city_slug or DEFAULT_CITY, key)
    return a.label if a else None


def area_keys(city_slug=None):
    """{area key: label} for one city, or every city's (keys are unique across cities)."""
    picked = [_BY_SLUG[city_slug]] if city_slug in _BY_SLUG else CITIES
    return {a.key: a.label for c in picked for a in c.areas}


def as_dict(c):
    return {'slug': c.slug, 'name': c.name, 'short': c.short, 'tz': c.tz, 'phrase': c.phrase, 'known_for': c.known_for,
            'areas': [{'key': a.key, 'label': a.label} for a in c.areas]}
