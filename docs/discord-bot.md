# The Discord bot

The bot brings the club into its Discord server: everything on the site is a slash command, each
screening's discussion can be a thread mirrored with the site, and the club hears about schedule drops,
the weekly digest and games in one channel. It talks only to the backend's internal API (with
`INTERNAL_API_TOKEN`) and never touches the database itself.

Nobody needs a site account to use it: the first personal command a member uses in the club's server
makes them a Discord-only account in the club. "Sign in with Discord" on the site (or `/link`) joins it
to a site account later.

## What it does

- **Slash commands** — below; `/help` lists them in Discord.
- **The Monday digest** (10:00 ET) — who's going where, rare screenings, what each theatre added, open
  polls, and members whose watchlisted films are playing (only those who said yes to being tagged).
- **Schedule drops** — "AFI just added 23 showtimes", only for theatres the club turned on
  (`/announcements` or Club → Settings). All start off.
- **Screening threads** — a card in the channel (poster, time, who's going, Going / Maybe buttons) with a
  thread mirrored both ways with the site's discussion: site comments appear under the commenter's name
  through a webhook, messages in the thread become site comments, edits and deletions follow.
- **Game posts** — the question of the day, bingo cards and wins, poll openings and results, as each club
  chooses (Never / Ask first, where an admin approves each by DM / Always).
- **What members share** — RSVPs, "who's in?" invites and polls, only for members who choose to share.
- **"Did you go?"** — after a screening someone was going to, a private DM (10 AM–9 PM, at most one a day)
  with Went / Didn't go. Closed DMs: it asks after their next command instead.
- **Alerts by DM** — for members who chose Discord for their alerts (watchlist, saved searches, favorites).
- **Chat** — `@CinemaBot what should I see this weekend?`: recommendations grounded in the club's data
  (club members, needs `GROQ_API_KEY`); typing `what is thy wisdom CinemaBot` gets a movie quote, and
  movie talk in the channel sometimes does too. Never inside screening threads.
- **Owner DMs** — scraper failures (once a day per theatre) and AI model changes go to the application's
  owner, not the channel.

## Commands

| | |
|---|---|
| **Find something to see** | `/showtimes` what's playing (days, a date, a theatre, tickets; `going:True` for who's going) · `/movie` a film's details and showtimes · `/foryou` picks from Your taste · `/find` a kind of film (🔔 Alert me saves the search) · `/surprise` one random pick · `/theatre` where it is, what's on, members' notes |
| **Make plans** | `/rsvp` Going / Maybe / Can't go · `/discuss` open a screening's thread · `/watch` add to, remove from or show a watchlist · `/notifications` your alerts and where they go |
| **Play, polls & kernels** | `/play` the games hub · `/poll list` · `/poll vote` your private ballot · `/poll make` describe a poll and the AI drafts it (organizers) · `/leaderboard` |
| **You and the club** | `/profile` yours or @someone's (history, watchlist, compare, give kernels) · `/club` the club at a glance · `/link` connect an existing site account |
| **Extras** | `/digest` this week's digest (or a private preview) · `/announcements` which theatres post drops · `/quote` a random line, or add, fix and find quotes |
| **Server admins** | `/llm show` / `/llm set` the AI models (Manage Server by default; grant it to other roles in Server Settings → Integrations) |

Filters depend on each other: pick a film and the date and theatre options narrow to where it's showing.

## Run your own

One install of the site serves one Discord server: the bot posts to one channel (`DISCORD_CHANNEL_ID`)
for one club (`DEFAULT_GROUP_ID`). To run a club of your own, run your own copy — site, scrapers and bot
— from this repo ([deploying.md](deploying.md)), with your own Discord application:

1. **Create the application.** discord.com/developers/applications → New Application. Under **Bot**,
   reset and copy the token (`DISCORD_BOT_TOKEN`).
2. **Turn on two privileged intents** (Bot → Privileged Gateway Intents):
   - **Message Content** — the typed `what is thy wisdom` trigger, ambient quotes, and threads' messages
     reaching the site.
   - **Server Members** — who's in the server, so the site only ever names or pings members who are.

   No verification is needed under 100 servers.
3. **Invite it** (OAuth2 → URL Generator): scopes `bot` and `applications.commands`; permissions — at least
   in your club's channel — View Channel, Send Messages, Embed Links, Read Message History, **Manage
   Webhooks**, **Create Public Threads** and **Send Messages in Threads** (the last three are for
   screening threads; without them the bot DMs its owner once to say what's missing).
4. **Settings** in `.env.production`: `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` (Developer Mode on, then
   right-click the channel → Copy Channel ID), `INTERNAL_API_TOKEN` (the same file feeds the backend),
   `DEFAULT_GROUP_ID` (`1` for a fresh install's club), `SITE_URL`, and optionally `GROQ_API_KEY`.
   All of them: [configuration.md](configuration.md).
5. **Start it:** `sudo docker-compose up -d --build bot`. The log names any setting it's missing. Slash
   commands are global: the first time, they can take up to an hour to appear in a server; changes after
   that show within a minute or two.
6. **Optional — Sign in with Discord** on the site: in the same application's OAuth2 tab copy the Client ID
   and Secret (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`) and add the redirect
   `<FRONTEND_URL>/api/auth/discord/callback`.

Then, on the site, your club's admins choose which theatres announce drops, which games post (and how),
and members choose what they share — all off until someone turns it on.

**Developing:** make a second application for a test server and use its token locally. Never run a local
bot with the live server's token — two bots on one token fight over the connection and post twice.

*Adding the bot to other servers, each linked to its own club, is on the roadmap — it needs per-server
club and channel settings.*

## How it's built

```
bot/
├── bot.py           # starts the bot; gathers every feature's names (for the tests)
├── features/
│   ├── shared.py    # settings, the client and command tree, the API, failure messages, helpers,
│   │                #   shared autocompletes — and the registry of buttons and loops
│   ├── chat.py      # quotes, the @-mention chatbot and its rate limits, /quote
│   ├── alerts.py    # schedule drops, the digest, "did you go?", alerts by DM
│   ├── schedule.py  # /link /showtimes /movie /rsvp /watch /find /surprise /foryou /theatre
│   ├── threads.py   # screening threads and what members share from the site
│   ├── profile.py   # /profile and giving kernels
│   ├── polls.py     # /poll
│   ├── games.py     # trivia, bingo, quiz games, /play, /leaderboard, game posts
│   ├── club.py      # /club, /help, who's in the server
│   └── admin.py     # /llm
├── api.py           # the backend's internal API client
├── embeds.py        # every message and embed the bot builds (and HELP_SECTIONS for /help)
├── llm.py           # the chatbot's model choice (lives in the backend; shared with the site)
└── quotes.py        # the original quote list (seeds an empty database)
```

The backend side is `backend/routes/internal/` (posts, schedule, threads, people, games, admin).

**Adding a command:** put it in the feature it belongs to. Buttons that must keep working after a restart
are `DynamicItem`s; list them (and any `tasks.loop`) in that module's `register(...)` call — a test fails
if one is missed. Add the command to `embeds.HELP_SECTIONS` (its test checks every command is listed) and,
if it changes what members can do, to the site's Help (`frontend/src/help.json`). Tests drive commands
against the real backend with no Discord connection (`tests/bot/`, `helpers.patch_bot_api`; swap a bot
name such as the channel lookup with `helpers.patch_bot`).
