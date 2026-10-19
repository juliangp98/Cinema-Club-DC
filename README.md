# Cinema Club DC

A film club for the DC area's repertory and independent theatres — **[cinemaclubdc.com](https://cinemaclubdc.com)**.
It gathers every showtime from 13 theatres into one place, helps you find something worth seeing,
and lets a club of friends make plans, talk about films, and play games around them — on the site
and in the club's Discord server.

Anyone can browse what's playing. Clubs are private groups (ours is invite-only); members RSVP,
keep watchlists, check in after screenings, and earn 🍿 kernels.

---

## What's on the site

| Page | What it does |
|---|---|
| **Discover** (home) | Shelves of what's worth seeing — rare screenings and 35/70mm prints, last chances, openings, **For you** (from Your taste), double features, spotlights — plus one search bar (✨ describes what you want in words, for club members) and *Surprise me*. |
| **Browse** | Every film in a time window with filters: theatres and regions, genres, decade, format, time of day, rarity, runtime, mood, tickets (available, sold out, coming soon). Any search can be saved as an alert. |
| **Calendar** | Every showtime as an agenda, a week or a month, with the same filters. Announced films show on the day a theatre expects them. |
| **Film** and **Theatre** pages | A film's details, ratings, trailer and every showing; a theatre's map, what's on this week, and members' notes. |
| **Feed** | The club's activity: who's going where, check-ins (with Letterboxd ratings if shared), discussion, polls, weekly recaps. |
| **Play** | The games hub: daily and anytime **trivia**, **repertory bingo** (a monthly card filled by screenings — and Letterboxd diary entries, if the club allows), **quiz games** (Higher or lower, Who said it, Guess the still, Guess from the reviews, Emoji plot), **polls** with kernel stakes, and **Records** for you, everyone and the club. |
| **Club** | Members, the leaderboard, the club's theatres and settings (organizers and admins). |
| **Me** | Your plans, history, watchlist, check-ins and **Settings** — by category: profile, Your taste, notifications, connections (Discord, Letterboxd, calendar feeds), privacy. |
| **People** pages | A member's profile, taste match, history and game records (within your clubs). |
| **Help** | Every question answered, with links to the place; ✨ **Ask** answers in your own words (club members). Every page has a short tour (**?** in the top bar). |

Around the pages:

- **Alerts, all opt-in** — watchlist films booked or going on sale, saved searches, favorites booked,
  game reminders — in the bell, by email, Discord DM or phone push, as each member chooses.
- **Sold out and off sale** — sold-out showings are marked; one that disappears from a theatre's site
  stays listed as "Off sale — likely sold out", with RSVPs kept.
- **Discord** — the bot mirrors the site in the club's server: slash commands for everything above,
  screening threads mirrored with the site's discussions, a Monday digest, game posts, and an
  @-mention chatbot. See [docs/discord-bot.md](docs/discord-bot.md).
- **Letterboxd** — connect your diary to check in automatically, fill bingo squares from home
  viewings, and show your ratings; bring in your watchlist from Letterboxd's export (its films join
  your watchlist as theatres book them).
- **Calendar feeds** — your plans (or your club's) in Google, Apple or Outlook calendar.

### Theatres

Suns Cinema · AFI Silver · Alamo Drafthouse (DC Bryant Street, Crystal City) · Regal (Gallery Place,
Ballston Quarter, Majestic) · Smithsonian IMAX (Air & Space, Udvar-Hazy) · Avalon · National Gallery of
Art · Angelika (Mosaic, Union Market Pop-Up). AMC is ready and waits for an API key.
How each is read: [docs/scrapers.md](docs/scrapers.md).

---

## How it's built

- **Backend** — Flask, SQLAlchemy and SQLite (WAL), served by Gunicorn. Scrapers use requests,
  BeautifulSoup and curl_cffi; films are enriched from TMDB and OMDb; AI (Help's ✨ Ask, ✨ search,
  poll drafts, the chatbot) runs on Groq.
- **Frontend** — React 18 and Vite, React Router; a hand-made UI kit (`frontend/src/ui`) with one set of
  design tokens. Admins can see every piece live at `/styleguide`.
- **Discord bot** — discord.py, talking to the backend's internal API only.
- **Deployment** — three Docker containers (backend, frontend on nginx, bot) on a Synology NAS behind a
  Cloudflare Tunnel.

```
├── backend/
│   ├── app.py                 # Flask app: config, sessions, shared helpers; imports the routes
│   ├── models.py              # The database tables
│   ├── migrations.py          # Bringing the database up to date on start (prepare_db)
│   ├── config_check.py        # Names unset settings at start
│   ├── routes/                # The site's API by area (auth, people, clubs, schedule, plans,
│   │   │                      #   social, polls, quizzes, alerts, help, discord)
│   │   └── internal/          # The bot's API by area (posts, schedule, threads, people, games, admin)
│   ├── discover.py            # Shelves, Browse, Calendar, digest picks
│   ├── notify.py              # Personal alerts: bell, Discord DM, email, push
│   ├── trivia.py, bingo.py, quizzes.py, play.py, kernels.py, club_stats.py   # Games and standings
│   ├── letterboxd.py, taste.py, help_ai.py, ai.py, …
│   ├── scraper.py + scrapers/ # One scraper per theatre chain, and the sync into the database
│   └── entrypoint.sh          # Docker start: prepare_db, settings check, gunicorn
├── bot/
│   ├── bot.py                 # Starts the bot
│   ├── features/              # By feature: shared, chat, alerts, schedule, threads, profile,
│   │                          #   polls, admin, games, club
│   └── api.py, embeds.py, llm.py, quotes.py
├── frontend/src/
│   ├── pages/, components/    # The pages and their parts
│   ├── ui/                    # The UI kit (ui.css, Panel, Settings, SearchField, TicketRow, …)
│   ├── shell/                 # App shell: top bar, nav, tours, activity
│   └── help.json              # Help's questions and answers (also read by ✨ Ask)
├── tests/                     # pytest (backend + bot) and vitest (frontend): tests/run.sh
├── docs/                      # Configuration, deploying, the bot, scrapers, contributing
├── docker-compose.yml, Dockerfile.backend, Dockerfile.frontend, Dockerfile.bot
└── .env.production.example    # Every setting, with where to get it
```

---

## Running it locally

You need Python 3.12 and Node 20.

```bash
# Backend (http://localhost:5001)
cd backend
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env.development        # set ADMIN_EMAIL to your address
./venv/bin/python app.py
```

```bash
# Showtimes (a full run takes 10–15 minutes; --only suns,afi for a quick one)
cd backend
./venv/bin/python scraper.py --only suns,afi
```

```bash
# Frontend (http://localhost:5173, proxies /api to :5001)
cd frontend
npm install
npm run dev
```

Sign in with your `ADMIN_EMAIL`: without email settings, the sign-in link prints in the backend's
console. Every setting is optional locally — the backend names what's missing when it starts.

Tests: `tests/run.sh` (everything), `tests/run.sh -k discord`, `tests/run.sh frontend`.

---

## Docs

- [Configuration](docs/configuration.md) — every setting, what it's for and where to get it
- [Deploying](docs/deploying.md) — Docker on a NAS, a domain through Cloudflare, scheduled scrapes, updates and backups
- [The Discord bot](docs/discord-bot.md) — what it does, its commands, and setting it up for your own server
- [Scrapers](docs/scrapers.md) — each theatre, how it's read, sold-out handling, adding a theatre
- [Contributing](docs/contributing.md) — the dev setup, tests, the UI kit and house rules
- [Tests](tests/README.md) — how the suite is laid out

**Start a club in your city:** the whole stack — site, bot and scrapers — runs from this repo.
Point the scrapers at your theatres, then follow [Deploying](docs/deploying.md) and
[The Discord bot](docs/discord-bot.md).
