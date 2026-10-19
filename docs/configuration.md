# Configuration

Every setting is an environment variable. In production they live in `.env.production` at the repo
root (both the backend and the bot read it — start from `.env.production.example`); locally, in
`backend/.env.development` (start from `backend/.env.example`). Never commit either real file — `.gitignore`
keeps them out.

On start, the backend and the bot each print any setting that's unset and what goes without it; on the
real site (an `https://` `FRONTEND_URL`) the ones it needs are marked **NEEDED**. A test keeps both
templates in step with the code (`tests/backend/test_config.py`).

## The site

| Setting | Needed | What it's for | Where to get it |
|---|---|---|---|
| `SECRET_KEY` | yes | Signs sign-in sessions. Without it each server process makes its own, so people are signed out at random and on every restart. Changing it signs everyone out once. | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `FRONTEND_URL` | yes | The site's address: links in emails, CORS, and (when `https://`) the secure session cookie. | e.g. `https://cinemaclubdc.com`; locally `http://localhost:5173` |
| `DATABASE_URL` | — | Where the SQLite database is. In Docker it lives in the `db-data` volume. | `sqlite:///cinemaclub.db` (production), `sqlite:///instance/cinemaclub_dev.db` (local) |
| `SMTP_EMAIL`, `SMTP_PASSWORD` | yes | Sign-in links (and opt-in email alerts) go by email. Unset, emails print to the backend's console instead — fine locally. | A Gmail address and an **app password** for it: Google Account → Security → 2-Step Verification → App passwords |
| `ADMIN_EMAIL`, `ADMIN_NAME` | first start | A fresh database's first admin account and default club. An existing database already has them. | Your address |

## Film details

| Setting | Needed | What it's for | Where to get it |
|---|---|---|---|
| `TMDB_API_TOKEN` | recommended | Posters, cast, crew, genres, trailers and runtimes; trivia's film pool. | themoviedb.org → Settings → API → **API Read Access Token** (the long one) |
| `OMDB_API_KEY` | recommended | IMDb, Rotten Tomatoes and Metacritic ratings, awards, original language. The free key allows 1,000 requests a day. | omdbapi.com → API Key |

## The Discord bot

See [discord-bot.md](discord-bot.md) for setting the bot up.

| Setting | Needed | What it's for | Where to get it |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | for the bot | The bot's login. The bot won't start without it. | Discord Developer Portal → your application → Bot → Reset Token |
| `INTERNAL_API_TOKEN` | for the bot | A shared secret: the bot sends it with every call to the backend's internal API. Both containers read the same file. | Make one like `SECRET_KEY` |
| `DISCORD_CHANNEL_ID` | for the bot | The home server's channel (the bot's first server): drops, the digest, game posts and screening threads there. The bot registers that server for `DEFAULT_GROUP_ID` when it starts; other clubs connect their own servers from Club settings → Discord. | Discord → User Settings → Advanced → Developer Mode on, then right-click the channel → Copy Channel ID |
| `SITE_URL` | for the bot | The site's address in the links the bot posts. Usually the same as `FRONTEND_URL`. | |
| `DEFAULT_GROUP_ID` | — | The home server's club. `1` on a fresh install (the default club). | The club's id: `docker exec cinemaclub-backend python -c "from app import app, Group; app.app_context().push(); print([(g.id, g.name) for g in Group.query])"` |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | optional | "Sign in with Discord" on the site. Without them the button doesn't show. | Same application → OAuth2. Add the redirect `<FRONTEND_URL>/api/auth/discord/callback` there |

## AI

| Setting | Needed | What it's for | Where to get it |
|---|---|---|---|
| `GROQ_API_KEY` | optional | Help's ✨ Ask, ✨ search, AI poll drafts, the Emoji plot game and the bot's chat. Only club members can use them. | console.groq.com → API Keys (free tier) |
| `GROQ_MODEL`, `GROQ_FALLBACK_MODEL` | optional | Pin the models. Blank: chosen automatically from Groq's catalogue (checked daily, test-called before use). `none` turns the fallback off. A server admin can also change them with `/llm`. | |

## Push alerts

| Setting | Needed | What it's for | Where to get it |
|---|---|---|---|
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | optional | Phone and browser push alerts. Without them, push is simply not offered. | `docker exec cinemaclub-backend python vapid_keys.py` (or `python vapid_keys.py` in `backend/`) prints both lines |
| `VAPID_SUBJECT` | with push | Contact address push services can reach. | `mailto:you@example.com` |

## More theatres

| Setting | Needed | What it's for | Where to get it |
|---|---|---|---|
| `AMC_API_KEY` | optional | AMC's showtimes (AMC Georgetown 14, Hoffman Center 22). Then set `enabled=True` for the AMC entries in `backend/scrapers/__init__.py`. | developers.amctheatres.com (approval required) |

## Set by the Docker setup

You don't set these; they're listed so nothing in the code is a mystery.

| Setting | Set in | What it does |
|---|---|---|
| `TZ=America/New_York` | the Dockerfiles | The containers run on DC time (showtimes are stored in local time). |
| `WARM_PUBLIC_CACHE=1` | `backend/entrypoint.sh` | Each server process rebuilds the public pages every few minutes, so no visitor waits. |
| `BOT_API_BASE=http://backend:5001` | `docker-compose.yml` | Where the bot reaches the backend on the Docker network. |
| `HELP_JSON` | — | Where the backend finds Help's questions (the image copies `frontend/src/help.json` next to the app). |

## Settings that live in the site

Most choices aren't environment settings at all: each club's admins and organizers set its theatres,
games (each off until switched on), Discord posts (Never / Ask first / Always), theatre announcements and
whether the club is listed or invite-only in **Club → Settings**; each member sets their alerts, sharing
and connections in **Me → Settings**.
