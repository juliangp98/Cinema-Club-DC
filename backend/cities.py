"""The cities the site covers, the areas within each — and, under each city,
its theatres — all from one data file, cities.json.

A city is the top level: its theatres, its time zone (a showtime's start is
that city's wall-clock time) and how it's named. Areas are the sections
inside a city — DC / Maryland / Virginia — that Browse's "Where" filter and
the Theatres page use (the URL keeps its old name, `regions=`).

Adding a city, an area or a theatre of a chain we already read (AMC, Regal,
Alamo, Angelika, …) is an edit to cities.json, not to code
(docs/scrapers.md). The file is checked when it's read: a mistake stops the
backend and the scraper with a message naming the entry. This module reads
the cities; the scraper registry (scrapers/__init__.py) reads the theatres.
It must NOT import app (the scraper registry and the bot's tests read it).
"""
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATA_FILE = Path(__file__).with_name('cities.json')
SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


class PlacesFileError(ValueError):
    """A mistake in cities.json, named so it can be found and fixed."""
    def __init__(self, where, problem):
        super().__init__(f'{DATA_FILE.name}: {where}: {problem}')


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


def words_pattern(phrases):
    """Plain words and phrases ("silver spring", "d.c.") as one pattern that
    finds any of them, whole, in a lowercased ask."""
    phrases = sorted({str(p).strip().lower() for p in phrases or () if str(p).strip()}, key=len, reverse=True)
    return r'(?<!\w)(?:' + '|'.join(re.escape(p) for p in phrases) + r')(?!\w)' if phrases else ''


CITY_KEYS = {'slug', 'name', 'short', 'tz', 'phrase', 'lat', 'lon', 'areas'}
CITY_OPTIONAL = {'words', 'hint', 'known_for', 'theatres'}
AREA_KEYS = {'key', 'label', 'words'}


def check_keys(where, entry, required, optional=frozenset()):
    """An entry has what it must and nothing unknown (a misspelled key would otherwise be ignored)."""
    if not isinstance(entry, dict):
        raise PlacesFileError(where, 'should be an object ({ … })')
    missing = sorted(required - entry.keys())
    if missing:
        raise PlacesFileError(where, f"missing {', '.join(missing)}")
    unknown = sorted(entry.keys() - required - optional)
    if unknown:
        raise PlacesFileError(where, f"unknown {', '.join(unknown)} (known: {', '.join(sorted(required | optional))})")


def check_number(where, entry, *keys):
    for k in keys:
        if isinstance(entry[k], bool) or not isinstance(entry[k], (int, float)):
            raise PlacesFileError(where, f'{k} should be a number')


def read_file(path=None):
    """cities.json, parsed (the theatre registry reads its theatres from here too)."""
    path = Path(path or DATA_FILE)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise PlacesFileError(f'line {e.lineno}, column {e.colno}', f'not valid JSON ({e.msg})') from None
    if not isinstance(data, dict) or not isinstance(data.get('cities'), list) or not data['cities']:
        raise PlacesFileError('top level', 'should be {"cities": [ … ]} with at least one city')
    return data


def load_cities(data):
    """The City list from parsed cities.json, checked."""
    out, slugs, area_keys = [], set(), set()
    for i, c in enumerate(data['cities']):
        where = f"city {c.get('slug') or i + 1}" if isinstance(c, dict) else f'city {i + 1}'
        check_keys(where, c, CITY_KEYS, CITY_OPTIONAL)
        if not SLUG.match(str(c['slug'])):
            raise PlacesFileError(where, 'slug should be lowercase letters, digits and dashes')
        if c['slug'] in slugs:
            raise PlacesFileError(where, 'slug used twice')
        slugs.add(c['slug'])
        try:
            ZoneInfo(c['tz'])
        except (ZoneInfoNotFoundError, ValueError):
            raise PlacesFileError(where, f"tz {c['tz']!r} isn't a time zone (like America/Chicago)") from None
        check_number(where, c, 'lat', 'lon')
        if not isinstance(c['areas'], list) or not c['areas']:
            raise PlacesFileError(where, 'needs at least one area')
        areas = []
        for a in c['areas']:
            aw = f"{where}, area {a.get('key') if isinstance(a, dict) else '?'}"
            check_keys(aw, a, AREA_KEYS)
            if not SLUG.match(str(a['key'])):
                raise PlacesFileError(aw, 'key should be lowercase letters, digits and dashes')
            if a['key'] in area_keys:
                raise PlacesFileError(aw, 'key used twice (area keys are unique across cities: they go in URLs)')
            area_keys.add(a['key'])
            areas.append(Area(a['key'], a['label'], words_pattern(a['words'])))
        out.append(City(c['slug'], c['name'], c['short'], c['tz'], c['phrase'], c['lat'], c['lon'], areas=tuple(areas),
                        words=words_pattern(c.get('words')), hint=c.get('hint', ''), known_for=c.get('known_for', '')))
    return out


DATA = read_file()
CITIES = load_cities(DATA)
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
