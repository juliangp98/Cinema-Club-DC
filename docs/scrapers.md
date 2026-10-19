# Scrapers

`backend/scraper.py` reads every theatre's schedule and syncs it into the database. The full run is
scheduled every 6 hours, and Suns alone every 30 minutes ([deploying.md](deploying.md)):

```bash
python scraper.py                    # every enabled theatre
python scraper.py --only suns,afi    # some (even if switched off)
python scraper.py --list             # the registry
```

Each theatre is a `TheatreConfig` in `backend/scrapers/__init__.py` (name, address, map pin, color,
its scrape function, whether it's enabled, and how a schedule drop is announced). One module per chain
in `backend/scrapers/` returns a list of films, each with its showtimes; `scrapers/sync.py` writes them.

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
| **AMC** (Georgetown, Hoffman Center) — off | AMC's developer API | One request per date for 45 days. Needs `AMC_API_KEY`. | `isSoldOut`; `isCanceled` → cancelled |

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

1. Write a scraper in `backend/scrapers/` that returns `new_movie_dict()`s with `make_showtime(...)`s.
   Use `get_soup` / `get_json` (pooled, with retries), `PerDateFetcher` for one request per date, and end
   with `finish_scrape(label, movies, error, missed_dates=…, skipped=…)` — it raises when nothing was read
   and marks a run partial when pages failed.
2. Mark sold out wherever the site says so; leave `runtime_minutes=None` if the site doesn't give one.
3. Add a `TheatreConfig` to the registry (start it `enabled=False` until it's checked).
4. Save a trimmed copy of the site's page or feed in `tests/fixtures/scrapers/` (a few films, no
   personal details) and test the scraper against it in `tests/backend/test_scraper_pages.py`.
5. Add it to the theatre lists in the README and this page.

## When a site changes

The owner's DM says which theatre failed and why ("no films on the upcoming page — has its layout
changed?"). Save a fresh copy of the page, update the scraper and its fixture together, and run
`tests/run.sh -k scraper`.
