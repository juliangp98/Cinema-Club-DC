# The Discord bot

The bot brings a club into its Discord server: everything on the site is a slash command, each
screening's discussion can be a thread mirrored with the site, and the club hears about schedule drops,
the weekly digest and games in one channel. Any club can connect its own server — one server, one club —
and the bot serves each for that club. It talks only to the backend's internal API (with
`INTERNAL_API_TOKEN`) and never touches the database itself.

Nobody needs a site account to use it: the first personal command a member uses in a connected server
makes them a Discord-only account in that server's club. "Sign in with Discord" on the site (or `/link`)
joins it to a site account later.

## What it does

- **Slash commands** — below; `/help` lists them in Discord.
- **The Monday digest** (Mondays at 10, the club's city's time) — who's going where, rare screenings, what each theatre added, open
  polls, and members whose watchlisted films are playing (only those who said yes to being tagged). Only
  for clubs that have it on (Club settings → Theatres: on for the home club, off for new ones); the site
  publishes the same picks in the Feed and the bell at the same time. With it off, `/digest` only previews.
- **Schedule drops** — "AFI just added 23 showtimes", only for theatres the club turned on
  (`/announcements` or Club → Settings). All start off.
- **Screening threads** — a card in the channel (poster, time, who's going, Going / Maybe buttons) with a
  thread mirrored both ways with the site's discussion: site comments appear under the commenter's name
  through a webhook, messages in the thread become site comments, edits and deletions follow.
- **Game posts** — the question of the day, bingo cards and wins, poll openings and results, as each club
  chooses (Never / Ask first, where an admin approves each by DM / Always).
- **What members share** — RSVPs, "who's in?" invites and polls, only for members who choose to share.
- **"Did you go?"** — after a screening someone was going to, a private DM (10 AM–9 PM their time, at most one a day)
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
| **Find something to see** | `/showtimes` what's playing (days, a date, a theatre, tickets; `going:True` for who's going; `city:` another city's) · `/movie` a film's details and showtimes · `/foryou` picks from Your taste · `/find` a kind of film (🔔 Alert me saves the search) · `/surprise` one random pick · `/theatre` where it is, what's on, members' notes |
| **Make plans** | `/rsvp` Going / Maybe / Can't go · `/discuss` open a screening's thread · `/watch` add to, remove from or show a watchlist · `/notifications` your alerts and where they go |
| **Play, polls & kernels** | `/play` the games hub, or `game:` straight into trivia, your bingo card, a quiz game or your kernels · `/poll` with `action:` the open polls, your private ballot, or make one (describe it and the AI drafts it; organizers) · `/leaderboard` with `period:` all time, this year or this month |
| **You and the club** | `/profile` yours or @someone's (history, watchlist, compare, give kernels) · `/club` the club at a glance · `/link` connect an existing site account |
| **Extras** | `/digest` this week's digest (if the club has it on), or a private preview · `/announcements` which theatres post drops · `/quote` a random line, or `action:` add, fix, remove and find quotes |
| **Server admins** | `/setup` connect this server to your club (with a code from Club settings), or move the bot's channel · `/llm` (`action:` show or set) the AI models — the whole site's, so only in the home server (Manage Server by default; grant them to other roles in Server Settings → Integrations) |

Filters depend on each other: pick a film and the date and theatre options narrow to where it's showing.

**Cities:** a club is in a city, and the bot keeps its clock (the digest, game posts, dates in its
menus). Theatre choices list the club's first; once the site has more than one city, other cities'
theatres carry their city's name, and `/showtimes`, `/find` and `/surprise` take `city:` to look at
another city. An unconnected server gets the site's first city.

**Which club a command is for:** its server's. In a server that isn't connected yet, only `/showtimes`,
`/movie`, `/find`, `/surprise`, `/theatre` and `/help` work (they're all public); the rest say how to
connect it, and the bot doesn't chat or drop quotes there. In a DM, someone in more than one connected club
gets a menu first ("Which club is this for?"); buttons in the DM then follow that pick for half an hour.

**Quotes:** every server gets the classic quotes; ones a club adds show only in its server. Members
correct and remove their club's quotes (removing someone else's takes Manage Server); the classics are
looked after from the home server.

## Add the bot to your club's server

For a club on this site (a club admin and a server admin — often the same person):

1. **Club → Settings → Discord → Add to Discord.** Discord asks which server; you need Manage Server there.
   The invite asks for what the bot needs: View Channel, Send Messages, Embed Links, Read Message History,
   Manage Webhooks, Create Public Threads and Send Messages in Threads.
2. **Make a code** in the same place (it works once, for 30 minutes), and in the channel the bot should post
   in, run `/setup code:…`. The page updates when it's connected.
3. **Choose what it posts** in Club settings: the Monday digest and which theatres' new showtimes
   (Theatres), and each game's posts (Games). Members choose what they share themselves. Everything starts off.

Move the bot to another channel: run `/setup` there (no code needed). Disconnect: Club settings → Discord
(the bot stays in the server, unconnected; your choices are kept). Removing the bot from the server also
disconnects it. If the bot loses a permission it needs, whoever connected the server gets a DM, and Club
settings shows what's missing.

## Run your own copy

For a club in another city (other theatres), run your own copy — site, scrapers and bot — from this repo
([deploying.md](deploying.md)), with your own Discord application. Your first server is the bot's
**home**: its channel is `DISCORD_CHANNEL_ID`, its club `DEFAULT_GROUP_ID`, and the bot registers it
when it starts; other clubs on your site then add the bot to their servers as above.

1. **Create the application.** discord.com/developers/applications → New Application. Under **Bot**,
   reset and copy the token (`DISCORD_BOT_TOKEN`).
2. **Turn on two privileged intents** (Bot → Privileged Gateway Intents):
   - **Message Content** — the typed `what is thy wisdom` trigger, ambient quotes, and threads' messages
     reaching the site.
   - **Server Members** — who's in the server, so the site only ever names or pings members who are.

   No verification is needed under 100 servers; past that, Discord requires verifying the bot and approving
   both intents.
3. **Make it public** (Bot → Public Bot), so your clubs' admins can add it to their servers, and **invite
   it to your home server** (OAuth2 → URL Generator): scopes `bot` and `applications.commands`; permissions
   — at least in its channel — View Channel, Send Messages, Embed Links, Read Message History, **Manage
   Webhooks**, **Create Public Threads** and **Send Messages in Threads** (the last three are for screening
   threads; without them the bot DMs its owner once to say what's missing). Once the bot has started, Club
   settings → Discord shows the same invite for everyone else.
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

## How it's built

```
bot/
├── bot.py           # starts the bot; gathers every feature's names (for the tests)
├── features/
│   ├── shared.py    # settings, the client and command tree, the API, failure messages, helpers,
│   │                #   shared autocompletes, the server → club map (club_of, channel_for, club()) —
│   │                #   and the registry of buttons and loops
│   ├── servers.py   # which club a command is for (the DM menu), /setup, joining and leaving servers
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

The backend side is `backend/routes/internal/` (posts, schedule, threads, people, games, admin, servers)
and `backend/discord_servers.py` (codes, connecting, the home server, status).

**Every Discord question is about one club.** In the backend, `on_discord(user, group_id)`,
`present_user_ids(group_id)`, `split_present(users, group_id)` and `can_share(user, group_id)` all take
the club: being in one server never names you in another club's. In the bot, a command's club is `club()`
(set before it runs), and loops go `for group_id, _ in connected_clubs()` with `use_club(group_id)` and
`channel_for(group_id)`.

**Adding a command:** put it in the feature it belongs to. One command per thing, with its choices
as options (`action:`, `game:`, `period:` — like `/showtimes`), never sub-commands (`/quote add`):
Discord lists sub-commands apart, and a test fails on one. Buttons that must keep working after a restart
are `DynamicItem`s; list them (and any `tasks.loop`) in that module's `register(...)` call — a test fails
if one is missed. Add the command to `embeds.HELP_SECTIONS` (its test checks every command is listed) and,
if it changes what members can do, to the site's Help (`frontend/src/help.json`). Tests drive commands
against the real backend with no Discord connection (`tests/bot/`, `helpers.patch_bot_api`; swap a bot
name such as the channel lookup with `helpers.patch_bot`).
