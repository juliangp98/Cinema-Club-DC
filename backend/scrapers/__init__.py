"""Theatre scraper registry.

Each venue is a TheatreConfig: metadata that seeds the Theatre table plus a
scrape() callable returning the standard movie-dict list. The venues come
from cities.json, under their city; each names one of SCRAPERS below and that
scraper's arguments (which theatre it is on the chain's site). So a theatre
of a chain we already read is a cities.json entry; a new chain or a one-off
house is a scraper module + a SCRAPERS line, then its entry. This module
must NOT import app (the sync layer imports app lazily inside functions).
"""

import inspect
import re
from dataclasses import dataclass
from functools import partial
from typing import Callable, List

import cities
from cities import PlacesFileError, check_keys, check_number

from .suns import scrape_suns, scrape_suns_announced
from .afi import scrape_afi
from .alamo import scrape_alamo
from .regal import scrape_regal
from .smithsonian import scrape_smithsonian
from .avalon import scrape_avalon
from .nga import scrape_nga
from .angelika import scrape_angelika
from .amc import scrape_amc

# What a cities.json theatre's "scraper" can name; its "args" are the
# function's, in order (docs/scrapers.md lists them per chain).
SCRAPERS = {
    'suns': scrape_suns, 'afi': scrape_afi, 'avalon': scrape_avalon, 'nga': scrape_nga,
    'alamo': scrape_alamo, 'regal': scrape_regal, 'smithsonian': scrape_smithsonian,
    'angelika': scrape_angelika, 'amc': scrape_amc,
}
# Scrapers that also read films announced before their showtimes ("announced": true).
ANNOUNCED = {'suns': scrape_suns_announced}
# Scrapers that need a key the chain must accept first (scraper.py checks it
# each full run): their theatres stay hidden until it works.
NEED_KEYS = {'amc'}
ANNOUNCE_MODES = ('drop_only', 'all', 'none')


@dataclass
class TheatreConfig:
    slug: str
    name: str
    short_name: str
    address: str
    website: str
    color: str
    scraper: str = ''            # a SCRAPERS name
    args: tuple = ()             # its arguments: which theatre on the chain's site
    scrape: Callable[[], list] = None
    enabled: bool = True
    city: str = 'dc'             # cities.json — whose clock its showtimes are on
    area: str = ''               # one of its city's areas (Browse's "Where", the Theatres page)
    arthouse: bool = False       # Discover: independent and repertory houses
    big_screen: bool = False     # Discover: giant screens even without a format label (IMAX museums)
    # A service that must work before it's shown: 'amc' — AMC's API key, which
    # each full scrape run checks (scraper.py). Until it works the theatre stays
    # hidden; once it does, it switches on by itself.
    needs: str = ''
    # Where it is (for the theatre page's map).
    lat: float = None
    lon: float = None
    # Films announced (with a date) before their showtimes are up (R8b).
    announced: Callable[[], list] = None
    # 'drop_only': announce only schedule drops; 'all': also announce small
    # additions; 'none': never announce.
    announce_mode: str = 'drop_only'
    drop_min_count: int = 10     # new future showtimes in one run = a "drop"
    drop_horizon_days: int = 7   # or calendar horizon extends by more than this


THEATRE_KEYS = {'slug', 'name', 'short_name', 'area', 'address', 'lat', 'lon', 'website', 'color', 'scraper'}
THEATRE_OPTIONAL = {'args', 'arthouse', 'big_screen', 'enabled', 'announced', 'announce_mode',
                    'drop_min_count', 'drop_horizon_days'}
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def _arg_names(fn):
    params = list(inspect.signature(fn).parameters.values())
    return [p.name for p in params if p.default is p.empty], [p.name for p in params]


def _theatre(city, t):
    """One cities.json theatre as a TheatreConfig, checked."""
    where = f"city {city.slug}, theatre {t.get('slug') if isinstance(t, dict) else '?'}"
    check_keys(where, t, THEATRE_KEYS, THEATRE_OPTIONAL)
    if not cities.SLUG.match(str(t['slug'])):
        raise PlacesFileError(where, 'slug should be lowercase letters, digits and dashes')
    if not any(a.key == t['area'] for a in city.areas):
        raise PlacesFileError(where, f"area {t['area']!r} isn't one of {city.slug}'s "
                                     f"({', '.join(a.key for a in city.areas)})")
    if t['scraper'] not in SCRAPERS:
        raise PlacesFileError(where, f"scraper {t['scraper']!r} isn't one we have ({', '.join(sorted(SCRAPERS))}); "
                                     'a new chain needs a scraper written first')
    fn, args = SCRAPERS[t['scraper']], t.get('args', [])
    required, every = _arg_names(fn)
    if not isinstance(args, list) or not len(required) <= len(args) <= len(every):
        wants = f"({', '.join(required)})" if required else 'none'
        raise PlacesFileError(where, f"args for {t['scraper']}: wants {wants}, got {args!r}")
    check_number(where, t, 'lat', 'lon')
    if not COLOR.match(str(t['color'])):
        raise PlacesFileError(where, f"color {t['color']!r} should look like #3a6bb5")
    if t.get('announced') and t['scraper'] not in ANNOUNCED:
        raise PlacesFileError(where, f"the {t['scraper']} scraper doesn't read announced films")
    if t.get('announce_mode', 'drop_only') not in ANNOUNCE_MODES:
        raise PlacesFileError(where, f"announce_mode should be one of {', '.join(ANNOUNCE_MODES)}")
    return TheatreConfig(
        slug=t['slug'], name=t['name'], short_name=t['short_name'], address=t['address'], website=t['website'],
        color=t['color'], scraper=t['scraper'], args=tuple(args), scrape=partial(fn, *args),
        enabled=bool(t.get('enabled', True)), city=city.slug, area=t['area'],
        arthouse=bool(t.get('arthouse')), big_screen=bool(t.get('big_screen')),
        needs=t['scraper'] if t['scraper'] in NEED_KEYS else '', lat=t['lat'], lon=t['lon'],
        announced=ANNOUNCED[t['scraper']] if t.get('announced') else None,
        announce_mode=t.get('announce_mode', 'drop_only'),
        drop_min_count=int(t.get('drop_min_count', 10)), drop_horizon_days=int(t.get('drop_horizon_days', 7)))


def load_registry(data, city_list):
    """Every city's theatres from parsed cities.json, checked: slugs and short
    names unique site-wide, colors unique within a city."""
    out, slugs, shorts, colors = [], set(), set(), {}
    by_slug = {c.slug: c for c in city_list}
    for c in data['cities']:
        city = by_slug[c['slug']]
        for t in c.get('theatres') or []:
            cfg = _theatre(city, t)
            where = f'city {city.slug}, theatre {cfg.slug}'
            if cfg.slug in slugs:
                raise PlacesFileError(where, 'slug used twice')
            if cfg.short_name in shorts:
                raise PlacesFileError(where, f'short_name {cfg.short_name!r} used twice')
            if cfg.enabled and cfg.color.lower() in colors.setdefault(city.slug, set()):
                raise PlacesFileError(where, f"color {cfg.color} is another {city.slug} theatre's")
            slugs.add(cfg.slug)
            shorts.add(cfg.short_name)
            if cfg.enabled:
                colors[city.slug].add(cfg.color.lower())
            out.append(cfg)
    return out


THEATRE_REGISTRY: List[TheatreConfig] = load_registry(cities.DATA, cities.CITIES)


def get_config(slug):
    for cfg in THEATRE_REGISTRY:
        if cfg.slug == slug:
            return cfg
    return None


def enabled_configs():
    return [cfg for cfg in THEATRE_REGISTRY if cfg.enabled]
