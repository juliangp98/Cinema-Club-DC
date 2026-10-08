"""Theatre scraper registry.

Each venue is a TheatreConfig: metadata that seeds the Theatre table plus a
scrape() callable returning the standard movie-dict list. Adding a venue =
one scraper module + one entry here. This module must NOT import app (the
sync layer imports app lazily inside functions).
"""

from dataclasses import dataclass
from functools import partial
from typing import Callable, List

from .suns import scrape_suns
from .afi import scrape_afi
from .alamo import scrape_alamo
from .regal import scrape_regal
from .smithsonian import scrape_smithsonian
from .avalon import scrape_avalon
from .nga import scrape_nga
from .angelika import scrape_angelika
from .amc import scrape_amc


@dataclass
class TheatreConfig:
    slug: str
    name: str
    short_name: str
    address: str
    website: str
    color: str
    scrape: Callable[[], list]
    enabled: bool = True
    # Where it is (for the theatre page's map). Looked up once from the
    # address with OpenStreetMap's search.
    lat: float = None
    lon: float = None
    # 'drop_only': announce only schedule drops; 'all': also announce small
    # additions; 'none': never announce.
    announce_mode: str = 'drop_only'
    drop_min_count: int = 10     # new future showtimes in one run = a "drop"
    drop_horizon_days: int = 7   # or calendar horizon extends by more than this


THEATRE_REGISTRY: List[TheatreConfig] = [
    TheatreConfig(
        slug='suns', lat=38.92896, lon=-77.03722, name='Suns Cinema', short_name='SUNS',
        address='3107 Mt Pleasant St NW, Washington, DC 20010',
        website='https://sunscinema.com', color='#e8a838',
        scrape=scrape_suns,
    ),
    TheatreConfig(
        slug='afi', lat=38.99659, lon=-77.0272, name='AFI Silver Theatre', short_name='AFI',
        address='8633 Colesville Rd, Silver Spring, MD 20910',
        website='https://silver.afi.com', color='#c45c3a',
        scrape=scrape_afi,
    ),
    TheatreConfig(
        slug='alamo-dc', lat=38.92218, lon=-76.99775, name='Alamo Drafthouse DC', short_name='ALAMO DC',
        address='630 Rhode Island Ave NE, Washington, DC 20002',
        website='https://drafthouse.com/dc-metro-area/theater/dc-bryant-street',
        color='#7b5ea7',
        scrape=partial(scrape_alamo, 'dc-metro-area', 'dc-bryant-street'),
    ),
    TheatreConfig(
        slug='alamo-crystal', lat=38.85879, lon=-77.04966, name='Alamo Drafthouse Crystal City', short_name='ALAMO CC',
        address='1660 Crystal Dr, Arlington, VA 22202',
        website='https://drafthouse.com/dc-metro-area/theater/crystal-city',
        color='#9b7bc7',
        scrape=partial(scrape_alamo, 'dc-metro-area', 'crystal-city'),
    ),
    TheatreConfig(
        slug='regal-gallery', lat=38.89879, lon=-77.02107, name='Regal Gallery Place', short_name='REGAL GP',
        address='701 7th St NW, Washington, DC 20001',
        website='https://www.regmovies.com/theatres/regal-gallery-place-4dx-1551',
        color='#3a6bb5',
        scrape=partial(scrape_regal, '1551', 'regal-gallery-place-4dx-1551'),
    ),
    TheatreConfig(
        slug='regal-ballston', lat=38.87848, lon=-77.11187, name='Regal Ballston Quarter', short_name='REGAL BQ',
        address='671 N Glebe Rd, Arlington, VA 22203',
        website='https://www.regmovies.com/theatres/regal-ballston-quarter-0296',
        color='#5a86c5',
        scrape=partial(scrape_regal, '0296', 'regal-ballston-quarter-0296'),
    ),
    TheatreConfig(
        slug='regal-majestic', lat=38.99655, lon=-77.0254, name='Regal Majestic', short_name='REGAL MAJ',
        address='900 Ellsworth Dr, Silver Spring, MD 20910',
        website='https://www.regmovies.com/theatres/regal-majestic-1862',
        color='#2a4f8f',
        scrape=partial(scrape_regal, '1862', 'regal-majestic-1862'),
    ),
    TheatreConfig(
        slug='smi-dc', lat=38.88813, lon=-77.01982, name='Lockheed Martin IMAX (Air & Space)', short_name='IMAX DC',
        address='National Air and Space Museum, 600 Independence Ave SW, Washington, DC 20560',
        website='https://www.si.edu/theaters/lockheedmartin', color='#4a7c6f',
        scrape=partial(scrape_smithsonian, 'lockheedmartin'),
        drop_min_count=6,
    ),
    TheatreConfig(
        slug='smi-udvar', lat=38.91084, lon=-77.44446, name='Airbus IMAX (Udvar-Hazy)', short_name='IMAX UH',
        address='Steven F. Udvar-Hazy Center, 14390 Air and Space Museum Pkwy, Chantilly, VA 20151',
        website='https://www.si.edu/theaters/airbus', color='#6aa08f',
        scrape=partial(scrape_smithsonian, 'airbus'),
        drop_min_count=6,
    ),
    TheatreConfig(
        slug='avalon', lat=38.96528, lon=-77.07627, name='Avalon Theatre', short_name='AVALON',
        address='5612 Connecticut Ave NW, Washington, DC 20015',
        website='https://www.theavalon.org', color='#a87520',
        scrape=scrape_avalon,
    ),
    TheatreConfig(
        slug='nga', lat=38.89147, lon=-77.01339, name='National Gallery of Art', short_name='NGA',
        address='East Building Auditorium, 4th St & Constitution Ave NW, Washington, DC 20565',
        website='https://www.nga.gov/calendar/film-programs.html', color='#8a8f5c',
        scrape=scrape_nga,
        drop_min_count=5,
    ),
    TheatreConfig(
        slug='angelika-mosaic', lat=38.87188, lon=-77.22949, name='Angelika Mosaic', short_name='ANGELIKA',
        address='2911 District Ave, Fairfax, VA 22031',
        website='https://angelikafilmcenter.com/mosaic', color='#b54a7c',
        scrape=partial(scrape_angelika, '0000000006', 'mosaic'),
    ),
    TheatreConfig(
        slug='angelika-popup', lat=38.9102, lon=-76.99617, name='Angelika Pop-Up Union Market', short_name='ANG UM',
        address='550 Penn St NE, Washington, DC 20002',
        website='https://angelikafilmcenter.com/popup', color='#d47ba3',
        scrape=partial(scrape_angelika, '0000000007', 'popup'),
    ),
    # AMC entries stay disabled until an official API key is approved
    # (developers.amctheatres.com) and AMC_API_KEY is set — see scrapers/amc.py.
    TheatreConfig(
        slug='amc-georgetown', lat=38.90274, lon=-77.06171, name='AMC Georgetown 14', short_name='AMC GT',
        address='3111 K St NW, Washington, DC 20007',
        website='https://www.amctheatres.com/movie-theatres/washington-d-c/amc-georgetown-14',
        color='#b5503a',
        scrape=partial(scrape_amc, 'amc-georgetown-14', 'amc-georgetown-14'),
        enabled=False,
    ),
    TheatreConfig(
        slug='amc-hoffman', lat=38.80237, lon=-77.07047, name='AMC Hoffman Center 22', short_name='AMC HC',
        address='206 Swamp Fox Rd, Alexandria, VA 22314',
        website='https://www.amctheatres.com/movie-theatres/washington-d-c/amc-hoffman-center-22',
        color='#8f3a2e',
        scrape=partial(scrape_amc, 'amc-hoffman-center-22', 'amc-hoffman-center-22'),
        enabled=False,
    ),
]


def get_config(slug):
    for cfg in THEATRE_REGISTRY:
        if cfg.slug == slug:
            return cfg
    return None


def enabled_configs():
    return [cfg for cfg in THEATRE_REGISTRY if cfg.enabled]
