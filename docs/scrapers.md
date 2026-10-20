# Scrapers

`backend/scraper.py` reads every theatre's schedule and syncs it into the database. The full run is
scheduled every 6 hours, and Suns alone every 30 minutes ([deploying.md](deploying.md)):

```bash
python scraper.py                    # every enabled theatre
python scraper.py --only suns,afi    # some (even if switched off)
python scraper.py --city dc          # one city's (each city can have its own schedule)
python scraper.py --list             # every theatre in cities.json, its city, area and scraper (and checks the file)
```

Cities, their areas and their theatres are data: `backend/cities.json`. Each theatre there (name,
address, map pin, color, its area, whether it's an arthouse or a big screen, whether it's enabled, how a
schedule drop is announced) names a **scraper** — one module per chain in `backend/scrapers/`, listed in
`SCRAPERS` in `scrapers/__init__.py` — and that scraper's **args**: which theatre it is on the chain's
site. The registry builds a `TheatreConfig` from each; a scraper returns a list of films, each with its
showtimes, and `scrapers/sync.py` writes them. The file is checked whenever it's read (the backend's
start, every scrape, `--list`): a mistake stops it with the entry and what's wrong — "city nyc, theatre
amc-empire: area 'brooklyn' isn't one of nyc's (manhattan, new-jersey)".

## The theatres

| Theatre | Source | How it's read | Sold out |
|---|---|---|---|
| **Suns Cinema** | sunscinema.com | The upcoming-films page (HTML); dates in DC time. Films Suns has *announced* come from its WordPress API (`/wp-json/nj/v1/show`). | Marked (`.sold-out`), ticket link kept |
| **AFI Silver** | silver.afi.com | Now Playing (~100 films), then every film's page for its showtimes and runtime — about 3 minutes, half a second apart. | Not marked — a full show disappears (→ off sale) |
| **Alamo Drafthouse** (DC Bryant Street, Crystal City) | drafthouse.com | One JSON feed per market, shared by both cinemas. No runtimes (end times come from the film's TMDB runtime); hidden sessions skipped. | `SOLDOUT` status |
| **Regal** (Gallery Place, Ballston Quarter, Majestic) | regmovies.com | JSON API through Cloudflare (curl_cffi). One request per date covers all three. | `StopSales` |
| **Smithsonian IMAX** (Air & Space, Udvar-Hazy) | si.edu | Each theater's page, then each film's page (shared by both venues). | Marked in the time's class or text |
| **Avalon** | Agile Ticketing feed | JSON with a ticket link per showing; in-person only. | `SalesState` |
| **National Gallery of Art** | nga.gov | The film calendar (the date and time are in each link), then each event page for details. | Free — never |
| **Angelika** (Mosaic, Union Market Pop-Up) | Reading Cinemas API | A token, then one request per date (1 s apart, up to 60 dates). | `soldout` |
| **AMC** (DC: Georgetown, Hoffman Center · New York: Lincoln Square, Empire 25, 34th Street · New Jersey: Newport Centre, Clifton Commons) | AMC's developer API | One request per date for 45 days. Needs `AMC_API_KEY`, authorized by AMC: each full run checks it once first; the AMCs are shown and scraped only while it works. The owner gets one DM when it's refused, then none until it works, then one saying it does ("✅ AMC accepted the API key: 7 theatres are on the site now"). | `isSoldOut`; `isCanceled` → cancelled |

## Being a good guest

- **One connection per site.** HTML pages go through one pooled session (`base.http()`); retries wait
  1 s, then 2 s, and a `429` or `5xx` waits as long as the site's `Retry-After` asks (up to 2 minutes).
- **Regal** allows about 25 requests before refusing for minutes. Every run checks the next 14 days at
  2–3 s apart; the dates further out are checked on one run a day (20 s apart, at most 40 minutes),
  remembered as `regal_deep_at` in the database. Three refused dates in a row end the run's requests.
- **Bot checks** — si.edu and nga.gov sometimes answer with a verification page instead. That page is
  recognized (`base.looks_blocked`), not parsed, and not asked for again in the run; NGA then uses the
  titles on its listing. Nothing tries to get around a bot check.
- **Every film is looked up once.** TMDB and OMDb are asked about a film the first time it appears;
  films TMDB can't identify (shorts programs, trivia nights) are retried at most weekly.

## What sync does with a run

- **New showtimes** are added; a burst of them (10+ by default, or the calendar reaching more than a
  week further) is a *schedule drop*, announced in Discord for theatres the club turned on, and watchers
  of an announced or watchlisted film are alerted.
- **A show that disappears** from the theatre's site is **off sale** — most likely sold out (AFI never
  marks sold out; it drops the show). It stays on the calendar, counted as sold out, labeled
  "Off sale — likely sold out", RSVPs kept; it's back to normal if it reappears. Only a theatre that says
  so outright (AMC) cancels a show.
- **Nothing is taken off sale** on dates a scraper couldn't fetch (`missed_dates`), or anywhere on a
  **partial** run — one where a page failed partway, so a film's showings may just be unread.
- **A scraper that fails outright** (nothing read, or a page layout that changed) records an error run,
  and the owner gets a Discord DM, at most once a day per theatre.
- **Announced films** (Suns posts films a week ahead) show as "Tickets soon" on their day until their
  showtimes appear — or the film has a show within a week of the post, even a sold-out or started one.

## Adding a theatre

**Of a chain we already read** — an AMC, Regal, Alamo, Angelika or Smithsonian IMAX — it's an entry in
`backend/cities.json`, under its city, and no code:

```json
{
  "slug": "regal-example", "name": "Regal Example 12", "short_name": "REGAL EX",
  "area": "manhattan", "address": "1 Example St, New York, NY 10001", "lat": 40.7500, "lon": -73.9900,
  "website": "https://www.regmovies.com/theatres/regal-example-1234", "color": "#3a6bb5",
  "scraper": "regal", "args": ["1234", "regal-example-1234"]
}
```

| `scraper` | `args` | Where to find them |
|---|---|---|
| `amc` | `[theatre_id, theatre_slug]` — both the slug | The theatre page's address: `amctheatres.com/movie-theatres/<city>/amc-empire-25` → `"amc-empire-25"` twice |
| `regal` | `[code, path]` | The theatre page's address: `regmovies.com/theatres/regal-majestic-1862` → `"1862"`, `"regal-majestic-1862"` |
| `alamo` | `[market, cinema]` | `drafthouse.com/<market>/theater/<cinema>` |
| `angelika` | `[cinema_id, site_path]` | The ID is in the site's API calls (ten digits, like `"0000000006"`); the path is `angelikafilmcenter.com/<site_path>` |
| `smithsonian` | `[theater]` | `si.edu/theaters/<theater>` |
| `suns`, `afi`, `avalon`, `nga` | none | One house each |

- **Required:** `slug` (lowercase, dashes; never change it once live — clubs and showtimes use it),
  `name`, `short_name` (unique site-wide; the calendar's chips), `area` (one of its city's), `address`,
  `lat`/`lon` (the map pin: right-click the place in Google Maps → the numbers), `website`, `color`
  (unique within its city), `scraper`.
- **Optional:** `args`; `"arthouse": true` or `"big_screen": true` (Discover's shelves); `"enabled":
  false` (kept, not shown or scraped — try it with `--only` first); `"announce_mode"` (`drop_only`,
  `all` or `none`), `"drop_min_count"` and `"drop_horizon_days"` (what counts as a schedule drop);
  `"announced": true` (Suns only: films announced before their showtimes).
- AMC theatres wait on the API key by themselves.

Then run `python scraper.py --list` (it checks the file), `python scraper.py --only <slug>` to see it
read, add it to the theatre lists in the README and this page, and deploy. Its showtimes are its city's
wall-clock times, as the site shows them.

**Of a new chain, or a one-off house** — a scraper first:

1. Write it in `backend/scrapers/`, returning `new_movie_dict()`s with `make_showtime(...)`s. Use
   `get_soup` / `get_json` (pooled, with retries), `PerDateFetcher` for one request per date, and end
   with `finish_scrape(label, movies, error, missed_dates=…, skipped=…)` — it raises when nothing was
   read and marks a run partial when pages failed. Its arguments are what tells one of the chain's
   theatres from another.
2. Mark sold out wherever the site says so; leave `runtime_minutes=None` if the site doesn't give one.
3. Add it to `SCRAPERS` in `backend/scrapers/__init__.py`, then its theatres to `cities.json` as above.
4. Save a trimmed copy of the site's page or feed in `tests/fixtures/scrapers/` (a few films, no
   personal details) and test the scraper against it in `tests/backend/test_scraper_pages.py`.

## Adding a city

1. Add it to `backend/cities.json`:

   ```json
   {
     "slug": "chicago", "name": "Chicago", "short": "CHI", "tz": "America/Chicago",
     "phrase": "Chicago-area", "lat": 41.8781, "lon": -87.6298, "words": ["chicago"],
     "hint": "The Loop and River North are Downtown; Evanston is the North Shore.",
     "known_for": "the Music Box, Siskel and more",
     "areas": [
       {"key": "downtown", "label": "Downtown", "words": ["downtown", "the loop", "river north"]},
       {"key": "north-shore", "label": "North Shore", "words": ["north shore", "evanston"]}
     ],
     "theatres": [ … ]
   }
   ```

   `slug` goes in URLs and the database (never change it once live); `short` tags its theatres beside
   other cities'; `tz` is its showtimes' clock; `phrase` reads "12 Chicago-area theatres"; `lat`/`lon`
   is its center. `words` are what someone asking in plain English calls the city, and each area's
   `words` what they call that area — whole words or phrases, any case. `hint` tells the AI search which
   area a neighborhood is in; `known_for` names a few theatres for page descriptions. Area keys go in
   URLs, so they're unique across every city.
2. Add its theatres under `theatres`, as above.
3. Schedule its run: `python scraper.py --city <slug>` (its own Task Scheduler entry, like DC's).

Nothing else changes: the moment a second city has an active theatre, the site shows the city menu, puts
each city's theatres and clubs under its name, and keeps every page, alert, digest and calendar on the
right city's clock. Clubs in it pick it as their home city.

## When a site changes

The owner's DM says which theatre failed and why ("no films on the upcoming page — has its layout
changed?"). Save a fresh copy of the page, update the scraper and its fixture together, and run
`tests/run.sh -k scraper`.
