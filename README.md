# Cinema Club DC

A private calendar app for tracking DC arthouse film showtimes at **Suns Cinema** and **AFI Silver Theatre**. Groups of friends can RSVP to screenings, react with emojis, chat about movies, and get smart genre-based recommendations.

---

## Features

- **Feed (home page)** — the group's recent activity: who's going where, check-ins, discussion, watchlist adds, polls and new members
- **Monthly calendar view** with color-coded theatre pills (orange = Suns, red = AFI)
- **Merged showtimes** — multiple screenings of the same movie on the same day appear as one calendar entry with comma-separated times
- **Showtime drawer** — click any entry to see movie poster, description, director, runtime, cast, trailer link, and per-screening RSVP/tickets/calendar export
- **Per-screening RSVP** — Going / Maybe / Can't Go for each individual showtime, independent across screenings
- **Calendar export** — add screenings to Google Calendar or download .ics for Apple Calendar
- **Emoji reactions** — 24 curated emojis per showtime (group-scoped)
- **Group chat** — a discussion per showtime (10s polling), mirrored with a thread in the club's Discord #movies channel
- **Group system** — create/join public groups, admin approval for join requests, invite by email
- **Profile menu** — edit display name, avatar color, bio, favorite genres
- **Smart recommendations** — star icon on showtimes matching your favorite genres
- **Email notifications** — Gmail SMTP for invite, join request, approval emails (console fallback when not configured)
- **Web scraping** — automated scraping of Suns Cinema and AFI Silver showtimes

---

## Architecture

```
Cinema Club/
├── docker-compose.yml            # Production orchestration (Synology NAS)
├── Dockerfile.backend            # Python 3.12 + Gunicorn
├── Dockerfile.frontend           # Node build → nginx
├── .dockerignore
├── .env.production.example       # Template for production secrets
├── backend/
│   ├── app.py                    # Flask API server (models, routes, email, seed)
│   ├── scraper.py                # Theatre scraper (Suns Cinema + AFI Silver)
│   ├── entrypoint.sh             # Docker startup (migrate + seed + gunicorn)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx               # Router, auth guard, group state
│   │   ├── main.jsx              # Entry point
│   │   ├── index.css             # Full dark theme (~1780 lines)
│   │   ├── pages/
│   │   │   ├── Feed.jsx          # Home page: group activity cards
│   │   │   ├── Calendar.jsx      # Monthly calendar with filter bar (/calendar)
│   │   │   ├── Login.jsx         # Login / Signup / Invite acceptance
│   │   │   └── GroupDiscovery.jsx # Browse, search, join, create groups
│   │   └── components/
│   │       ├── MainNav.jsx       # Feed / Calendar switch in the header
│   │       ├── ShowtimeDrawer.jsx # Multi-screening detail drawer
│   │       ├── GroupAdmin.jsx     # Invite, approve/deny, manage members
│   │       ├── GroupSwitcher.jsx  # Header group dropdown
│   │       ├── GroupMembers.jsx   # Members overlay with profile previews
│   │       ├── UserProfileDrawer.jsx # Site-wide user profile drawer
│   │       ├── ProfileMenu.jsx   # User profile editor
│   │       ├── ReactionBar.jsx   # Emoji reaction picker
│   │       └── ChatSection.jsx   # Per-showtime chat
│   ├── nginx.conf                # Production nginx (SPA + API proxy)
│   ├── index.html
│   ├── package.json
│   └── vite.config.js            # Dev proxy /api → :5001
└── .claude/
    └── launch.json               # Dev server configs
```

---

## Setup

### 1. Backend

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the server (seeds admin user + Chuds Cinema group on first run)
./venv/bin/python app.py
```

**Important**: Use `./venv/bin/python app.py` directly to avoid system Python version conflicts.

The server runs on **port 5001** by default.

### 2. Scrape initial data

```bash
cd backend
./venv/bin/python scraper.py
```

This scrapes both Suns Cinema and AFI Silver, populating the database with current showtimes.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev       # dev server at http://localhost:5173
```

### 4. Login

The seed creates an admin account for the club's email address as admin of the default group. Sign in by entering that address — a one-time sign-in link is emailed to it. Locally, without SMTP configured, the email (and its link) is printed in the backend console instead.

New users can sign up with any email + name — they confirm via an emailed link, then land on the Groups page to find and join a group.

---

## Environment Variables

```env
SECRET_KEY=your-random-secret-here
DATABASE_URL=sqlite:///cinemaclub.db
FRONTEND_URL=http://localhost:5173

# Gmail SMTP — REQUIRED in production: sign-in links are delivered by email.
# (Unset locally, emails print to the backend console instead.)
SMTP_EMAIL=your-club@gmail.com
SMTP_PASSWORD=your-gmail-app-password

# Movie metadata enrichment
TMDB_API_TOKEN=...        # themoviedb.org v4 read token
OMDB_API_KEY=...          # omdbapi.com

# Discord bot / internal API
INTERNAL_API_TOKEN=...    # shared secret between backend and bot (any random hex)
DISCORD_BOT_TOKEN=...     # from discord.com/developers/applications
DISCORD_CHANNEL_ID=...    # the #movies channel id (announcements, RSVP callouts, digest)
DISCORD_CLIENT_ID=...     # optional: "Sign in with Discord" (same application → OAuth2 tab)
DISCORD_CLIENT_SECRET=... # optional: pair with DISCORD_CLIENT_ID
GROQ_API_KEY=...          # free key from console.groq.com — powers the @-mention chatbot
GROQ_MODEL=               # optional pin; models are otherwise chosen automatically
GROQ_FALLBACK_MODEL=      # optional pin; "none" disables the fallback
SITE_URL=https://cinemaclubdc.com
DEFAULT_GROUP_ID=1

# AMC (only once your developer key is approved — then set enabled=True
# for the AMC entries in backend/scrapers/__init__.py)
AMC_API_KEY=
```

To send real emails, create a Gmail App Password:
1. Go to Google Account → Security → 2-Step Verification → App Passwords
2. Generate a password for "Mail"
3. Set `SMTP_PASSWORD` to that value

---

## Auth Flow

- **Login**: passwordless sign-in links. `POST /api/auth/login` emails a one-time link (single use, expires in 15 min, rate-limited per address and per client); opening it lands on `/auth/verify`, which redeems it via `POST /api/auth/verify`. Only a SHA-256 hash of each token is stored. Sessions last 30 days.
- **Signup**: Email + name — `POST /api/auth/signup` emails a confirmation link; the account is created when it's opened (no group required)
- **Sign in with Discord** (when `DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET` are set): OAuth2 with only the `identify` scope. It signs into the account linked to that Discord user, or creates a Discord-only account, which then joins groups the normal way. Signed-in site users can **Connect Discord** from the profile menu the same way; the `/link <code>` command remains as a fallback.
- **Discord-only accounts**: server members never need to sign up. The first time someone uses a personal bot command (`/rsvp`, `/watch`, `/profile`) in the club's server (the one containing `DISCORD_CHANNEL_ID`), they get an account with no email and join that server's group. It follows their Discord name and shows on the site as "@handle on Discord". Connecting Discord to a site account later merges everything into it; where both accounts have the same row (e.g. an RSVP to one screening), the site account's own wins.
- **Invite**: Admin enters email in group management → creates inactive user with invite token → sends email with acceptance link
- **Accept invite**: User visits `/invite/<token>` → enters name → account activated, added to group
- **No-group handling**: Users without groups are redirected to `/groups` to browse and join

---

## Group System

- **Public groups** are always visible on the Groups page in a paginated list (10 per page)
- **Join requests** require admin approval (admins are emailed)
- **Admin panel** lets you invite by email, approve/deny requests, remove members
- **Group-scoped data**: RSVPs, reactions, and chat messages are all scoped to the active group, and the server checks you're an active member of that group on every request
- **Invites** can only be sent by the group's admins

---

## Feed

The home page (`/`) shows what the group has been up to over the last 90 days,
newest activity first, 20 cards at a time:

- **Screenings**: one card per screening, gathering going/maybe RSVPs, "went"
  check-ins, comments and reactions ("You and Bo are going · Cy maybe"). It
  shows the latest comment and reaction counts. **Discuss** opens the full
  reactions and chat inline (one card at a time); posting goes to that
  screening's own discussion. **Open screening** opens the usual drawer.
- **Watchlist adds**: one card per film ("Ana and Cy added this to their
  watchlists"), with its next showing and how many members want it.
- **Polls**: opened, closed, and results scored, with a nudge if you haven't voted.
- **New members**: joins grouped by day, including people whose account was
  created by using the bot.

It's built from the source tables, not a copied log: un-RSVPing or removing a
watchlist film drops it from the feed, and activity from Discord appears like
anything else. Any new activity (a comment, a reaction, Maybe → Going) moves a
card back to the top. Only group members can see it, and RSVPs and check-ins
only show in the group they were made in. The calendar lives at `/calendar`;
old `/?showtime=` and `/?theatre=` links are redirected there.

---

## Calendar Features

- **Showtime merging**: Multiple screenings of the same movie at the same theatre on the same day are grouped into a single calendar pill showing all times
- **Scrollable day cells**: Days with many events scroll within the cell (max-height: 220px)
- **Theatre filters**: Toggle Suns / AFI visibility in the header
- **Showtime drawer**: Shows movie info once, with each screening having independent RSVP, tickets, and calendar export
- **Attendee dots**: Colored dots on calendar pills showing who's going (deduplicated across screenings)
- **"Did you make it?"**: after a screening you RSVP'd *going* to has been over
  2 hours (looking back up to a week), a card above the calendar asks Went /
  Didn't go. "Went" offers a jump into that screening's discussion. Once a
  screening has started, its drawer swaps Going/Maybe/Can't go for Went / Didn't
  go, so you can also log one you never RSVP'd to.
- **Watch history**: every profile lists the screenings that member saw, newest
  first. On your own you can correct any entry; ones you marked "didn't go" stay
  listed (struck through) so you can undo them. Attendance is its own record
  (`attendance` table), separate from the RSVP. "Attended" (leaderboard, chatbot)
  = confirmed went + unanswered going RSVPs − didn't go.
- **Profile lists**: every profile has Watchlist (each film with its next
  showing), Going (upcoming going/maybe RSVPs) and History tabs. Other members'
  profiles open on **Compare**: films you both want to see, screenings you're
  both going to, screenings one of you is going to that's on the other's
  watchlist, and what you've seen together. Any screening in a list opens its
  drawer. **My lists** in the group menu opens your own profile
  (`/members?profile=me`). You only see another member's RSVPs from groups you
  share.

---

## API Routes

### Auth
- `POST /api/auth/login` — email a one-time sign-in link
- `POST /api/auth/signup` — email a confirmation link (email + name)
- `POST /api/auth/verify` — redeem a sign-in/confirmation link and start the session
- `GET /api/auth/providers` — which sign-in options are configured (`{discord: bool}`)
- `GET /api/auth/discord/start[?mode=connect]` → Discord → `GET /api/auth/discord/callback` — Sign in with / Connect Discord
- `POST /api/auth/accept-invite` — accept invite token
- `POST /api/auth/logout` — clear session
- `GET /api/auth/me` — current user
- `PUT /api/auth/profile` — update name, bio, avatar_color, favorite_genres

### Groups
- `GET /api/groups` — user's groups
- `POST /api/groups` — create group
- `GET /api/groups/discover?q=&page=&per_page=` — browse public groups (paginated)
- `POST /api/groups/:slug/join` — request to join
- `POST /api/groups/:slug/members/:uid/approve` — approve member
- `POST /api/groups/:slug/members/:uid/deny` — deny request
- `DELETE /api/groups/:slug/members/:uid` — remove member

### Showtimes & RSVPs
- `GET /api/feed?group_id=&offset=` — the group's activity cards (20 per page, last 90 days)
- `GET /api/showtimes?start=&end=&group_id=` — showtimes for date range
- `POST /api/rsvp` — create/update RSVP (going/maybe/not_going)
- `GET /api/users/:id/watchlist` — a member's watchlist, each film with its next showing
- `GET /api/users/:id/rsvps` — a member's upcoming going/maybe RSVPs (shared groups only)
- `GET /api/users/:id/compare` — where you and a member line up (not yourself)
- `GET /api/showtimes/:id/ical` — iCal export
- `GET /api/showtimes/:id/gcal-url` — Google Calendar URL

### Polls
- `POST /api/polls/:id/vote` — `{votes: [{category_id, option_id, confidence?, rank?}], clear: [category_id]}`;
  each category mentioned is replaced (the same rules as Discord's `/vote`)
- `GET /api/polls/:id` — a category's vote split is included once you've picked in it, or voting has closed

### Reactions & Chat
- `POST /api/reactions` — toggle emoji reaction
- `GET /api/messages?showtime_id=&group_id=` — get messages (each with `via_discord`, `can_delete`)
- `POST /api/messages` — send message (queued for the screening's Discord thread)
- `DELETE /api/messages/:id` — delete your own comment (and its Discord copy); not for comments typed in Discord
- Showtime objects carry `discord_thread_url` once the screening has a thread

### Admin
- `POST /api/admin/invite` — invite user to group by email

---

## Scraper Notes

Scrapers live in `backend/scrapers/` as a pluggable registry (`THEATRE_REGISTRY`
in `scrapers/__init__.py`). Each venue is a `TheatreConfig` (name, slug, color,
scrape function, announce thresholds); `scraper.py` is a thin runner that
iterates enabled venues and syncs via `scrapers/sync.py`. Adding a venue =
one scraper module + one registry entry (theatres are seeded from the registry
on backend start).

| Venue | Source | Technique |
|---|---|---|
| Suns Cinema | sunscinema.com | static HTML |
| AFI Silver | silver.afi.com | two-stage HTML crawl |
| Alamo DC + Crystal City | drafthouse.com market feed | public JSON |
| Regal Gallery Place | regmovies.com/api/getShowtimes | JSON via curl_cffi (Cloudflare) |
| Lockheed Martin + Airbus IMAX | si.edu/theaters movie pages | HTML via curl_cffi |
| Avalon | Agile Ticketing feed.ashx | public JSON |
| National Gallery of Art | nga.gov film-programs (evd params) | HTML via curl_cffi |
| Angelika Mosaic + Union Market | production-api.readingcinemas.com | JSON (anon bearer from /settings/6) |
| AMC Georgetown + Hoffman | official API (Showtime v2) | **disabled** until `AMC_API_KEY` approved |

Useful commands:

```bash
python scraper.py                 # all enabled venues
python scraper.py --only suns     # one venue (works even if disabled)
python scraper.py --list          # show the registry
python scraper.py --emit-test-event suns   # synthetic drop event (bot testing)
```

Other behaviors:
- **Film identity.** Every venue label ever seen is remembered (`movie_alias`), so known labels need no TMDB lookup. New labels resolve by TMDB id, then by clean title + agreeing year.
- **Messy venue titles.** Format tags, embedded years and trailing series names are stripped (`LICORICE PIZZA in 70mm`, `HIS GIRL FRIDAY (1940)`, `Planes (2013) - NASM 50th Film Series`). A year written in the label beats the scraped one, which is often a re-release date. Program prefixes (`EPIC SUNDAY: BATMAN BEGINS`, `X presents THE FLY`) are tried as a fallback search after the full title, so real colon titles still win. Implemented in `scrapers/base.py` and `enrich.py`.
- **Formats and billings.** Each screening keeps its format (`70mm`, `IMAX`, `Digital`…) as a badge, plus the venue's own billing when it says more than the film title (`EPIC SUNDAY: BATMAN BEGINS`, `… (Chapters 1-3)`). So a film shown in 70mm and Digital is one calendar entry with both badges.
- **API budget.** Films TMDB can't identify (shorts programs, trivia nights) are retried at most weekly instead of on every scrape. OMDb is only called once a film is identified.
- **Catalog maintenance.** `python backfill_enrichment.py [--force]` cleans titles, merges duplicate films, labels screenings with their format, and looks up unmatched films (`--force` ignores the weekly retry window). It's safe to re-run and never triggers Discord posts.
- Future showtimes that disappear from a venue's calendar are soft-cancelled
  (`is_cancelled`), never deleted — RSVPs/chat survive.
- Each run records a `ScrapeRun`; bursts of new showtimes emit a `ScrapeEvent`
  (`new_drop`) that the Discord bot announces. Scrape failures emit rate-limited
  `scrape_error` events.
- One broken venue never affects the others.

## Discord Bot

`bot/` is a discord.py client (third Docker service, `cinemaclub-bot`) that
talks to the backend's `/api/internal/*` endpoints over the Docker network
(shared secret: `INTERNAL_API_TOKEN`). It never touches the database directly.

- **Weekly digest (the main notification)**: Mondays 10:00 ET in
  `DISCORD_CHANNEL_ID` (#movies). It covers who's going, rare screenings
  (repertory films and 35/70mm prints), the titles each theatre added this week,
  open polls, and **watchlist tags**. Anyone with a watchlisted film playing
  that week is @-tagged in the message text, at most once per film per two
  weeks. Members without Discord get the same news by email.
- **Theatre announcements (opt-in)**: schedule drops ("AFI just dropped 23 new
  showtimes") post as they happen only for theatres someone turned on with
  `/alerts`. All theatres start off.
- **Screening threads (mirrored discussions)**: each screening's discussion can
  have a thread in #movies, hanging off a card post (poster, time, theatre,
  who's going, with **Going** / **Maybe** buttons that RSVP privately and an
  **Open on the site** link; the card's RSVP list refreshes within a few
  minutes of a change). A thread is created on the first comment from either
  side: a site comment, `/discuss`, or the 💬 **Discuss** button on `/rsvp`
  confirmations and the "did you go?" follow-up (which opens a comment box —
  leave it empty to just open the thread). A new thread starts with the last
  10 site comments, under their authors' names with their real dates.
  - Site → Discord: comments post through a #movies webhook (named
    "Cinema Club") under the commenter's name — and Discord avatar, if linked —
    within ~5 seconds. Discord marks these with an APP tag; @mentions never ping.
  - Discord → site: messages typed in the thread become that member's comments
    (Discord-only members included; attachments become links); edits follow.
  - Deleting: the site has a delete button on your own comments (removing the
    Discord copy too); deleting in Discord — your own message, or a moderator
    removing one — removes the site copy. Comments typed in Discord are deleted
    in Discord.
  - The bot ignores its own webhook posts (no loops), drops no ambient quotes
    in screening threads, and replaces a thread that's deleted in Discord on the
    next comment. Threads archive after a week of quiet and reopen when someone
    comments. If it lacks permissions it DMs the owner once (see setup step 3).
- **Poll posts**: when an admin opens a poll on the site, #movies gets one post
  with a **Vote** button; when it's scored, the top 3 with their kernels.
- **Owner DMs**: scraper errors and chatbot model changes go to the bot owner's
  DMs, not the channel.
- **Slash commands**: `/showtimes`, `/movie`, `/whosgoing`, `/polls`, `/vote`, `/discuss`,
  `/leaderboard`, `/digest`, `/wisdom`, `/alerts`, `/rsvp`, `/watch`,
  `/history`, `/compare`, `/profile`, `/quote`, `/link`, `/llm`. Everything works with no site account. Personal
  commands set one up automatically on first use in the club's server (see
  Discord-only accounts above). Date/theatre filters are dependent:
  pick a movie and the date/theatre options narrow to where it's actually
  showing.
  - `/alerts`: anyone can see which theatres announce drops (private reply) or
    turn one on or off; changes are noted publicly in the channel.
  - `/digest`: anyone can post this week's digest to the current channel (no
    tags; 30-minute cooldown per channel), or `preview:True` to see it privately.
  - `/vote [poll]`: a private ballot, one category per page: a nominee
    dropdown (plus a 1–10 stake for confidence polls, or 1st/2nd/3rd dropdowns
    for ranked ones), Prev / Next / Next unanswered, and a jump list. Picks save
    as you go, so you can finish later here or on the site; single-pick polls
    move on to the next unanswered category automatically. How everyone voted
    shows once you've picked. Closed polls are read-only; scored ones show the
    winners, ✅/❌ on your picks, your kernels and your place. Ballots keep
    working after bot restarts. `/polls` has Vote buttons too. Creating,
    closing and scoring polls stays on the site (group admins).
  - `/discuss [date] [theatre] showtime [comment]`: open a screening's thread
    (creating it if needed), optionally posting your comment there; the reply
    with the link is private.
  - `/llm` (server admins only, by default those with Manage Server; grant it
    to roles in Server Settings → Integrations): see the chatbot's models and
    pin or unpin them.
- **@-mention chatbot**: `@CinemaBot what should I see this weekend?` — a light
  LLM (Groq free tier) grounded in the site's data (your genres, watchlist,
  attendance, standing + what's playing). Recommends, answers "where can I catch
  X", and judges your taste. Needs `GROQ_API_KEY`; no privileged intent required.
  Unlinked users can still chat (just less personalized).
  Models pick themselves from Groq's live catalogue: they're checked at startup,
  daily, and whenever one is retired. Each is test-called before use, and
  primary and fallback come from different model families. `/llm` overrides
  win, then the optional `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` env pins (`none`
  disables the fallback), then the automatic ranking in `bot/llm.py`.
- **Cinematic wisdom**: `/wisdom`, or `what is thy wisdom CinemaBot` (any form —
  a real @mention, a typed `@CinemaBot`, or just the name, any casing) — a random
  movie quote. Works for anyone, with no account needed. Only the line is
  ever shown, never its source.
- **`/quote add | edit | remove | find`**: manage that quote list from Discord.
  Adding or editing opens a short form: the quote, the movie (required) and the
  character (optional). The movie and character are the line's *silent
  source*: stored for accuracy and visible only here, in private replies.
  Anyone in the server can add or correct quotes. Only whoever added a quote,
  or a server admin (Manage Server), can remove it, and removals are soft
  (recoverable in the database). The list lives in the backend (`quote`
  table); `bot/quotes.py` is the original 302-line list, imported once into an
  empty database with each `# Movie (Character)` comment parsed into fields,
  and used as a fallback if the backend is unreachable.
- **Ambient quotes**: any message with movie-ish words (movie, theatre, IMAX,
  70mm, Dolby, cinema, film…) has a ~1-in-5 chance (rate-limited per channel) of
  making the bot drop a random quote. Requires the Message Content intent below.
- **"Did you go?" DMs**: after a screening someone RSVP'd *going* to, the bot asks
  privately by DM with Went / Didn't-go buttons. It only sends between 10 AM and
  9 PM ET, at most once a day per person with up to 5 screenings, and never asks
  about the same screening twice. Buttons keep working after bot restarts. If
  someone's DMs are closed, the same prompt appears privately after their next
  command.
- **`/history [member]`**: screenings you (or a member) saw with the club. ✅ means
  confirmed; 🎟️ means RSVP'd going and never answered.
- **`/compare member:@someone`**: privately, where you and a member line up:
  films you both want to see, screenings you're both going to, overlaps with
  each other's watchlists, and what you've seen together.
- **`/profile`**: your favorite genres (which the chatbot uses for recommendations), bio
  and Letterboxd, edited in place with a genre picker and a short form. Everything is
  private to you. `/profile member:@someone` shows another member's card.
- **Site connection (optional)**: "Sign in with Discord" on the site, or
  "Connect Discord" in the profile menu, puts the same account on the web
  calendar. The `/link <code>` command still works as a fallback.

Bot setup (one-time):
1. Create an application + bot at https://discord.com/developers/applications.
2. Copy the bot token. **Enable the "Message Content Intent"** under Bot →
   Privileged Gateway Intents — required for the ambient quotes and the
   typed-name `what is thy wisdom` trigger to read messages that don't ping the
   bot. (No verification needed under ~100 servers. Without it the bot still
   runs, but those two features stay dark and slash commands/@mention chat work.)
3. Invite it to the server with the `bot` + `applications.commands` scopes and
   these permissions, at least in #movies: View Channel, Send Messages, Embed
   Links, Read Message History, **Manage Webhooks**, **Create Public Threads**
   and **Send Messages in Threads** (the last three are for screening threads).
4. Set `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` (#movies channel id) in
   `.env.production`, then `docker-compose up -d --build bot`. Slash commands
   sync globally (every server the bot is in) — first appearance in a new
   server can take up to ~1h; updates after that apply within a minute or two.
5. Optional, for "Sign in with Discord" on the site: in the same application's
   **OAuth2** tab, copy the Client ID and reset/copy the Client Secret, and add the
   redirect `https://cinemaclubdc.com/api/auth/discord/callback` (it must match
   `FRONTEND_URL` + `/api/auth/discord/callback` exactly). Set
   `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` in `.env.production` and rebuild.
   Without them, the site simply doesn't show the Discord button.

Deep links: `https://cinemaclubdc.com/calendar?showtime=<id>` opens that
screening's drawer; `/calendar?theatre=<slug>` pre-filters the calendar. Older
`/?showtime=` / `/?theatre=` links still work (redirected).

### Run scraper on a schedule

```bash
crontab -e
# Add (runs every 6 hours):
0 */6 * * * cd /path/to/Cinema\ Club/backend && ./venv/bin/python scraper.py >> /var/log/cinema-club-dc-scraper.log 2>&1
```

---

## Deployment on Synology NAS (Docker)

The recommended way to self-host Cinema Club DC is via Docker on a Synology NAS using **Container Manager** (the built-in Docker UI). This gives you a persistent, auto-restarting deployment with a custom domain and HTTPS.

### Prerequisites

- Synology NAS with **Container Manager** installed (Package Center → Container Manager)
- SSH access enabled on your NAS (Control Panel → Terminal & SNMP → Enable SSH)
- A computer on the same network to SSH into the NAS
- (Optional) A custom domain name if you want external access

### Step 1: Copy the project to your NAS

Copy the entire `Cinema Club` folder to a shared folder on your NAS. You can use Finder (SMB), `scp`, or Synology Drive.

```bash
# Example:
scp -r "/Users/[user]/Documents/Cinema Club DC" your-nas-user@NAS-IP:/volume1/docker/cinema-club-dc
```

Or drag the folder into a shared folder via Finder → Connect to Server → `smb://NAS-IP`.

A good location is `/volume1/docker/cinema-club-dc/`.

### Step 2: Create the production environment file

SSH into your NAS:

```bash
ssh your-nas-user@NAS-IP
```

Navigate to the project and create your production config:

```bash
cd /volume1/docker/cinema-club-dc
cp .env.production.example .env.production
```

Edit `.env.production` with your values:

```bash
vi .env.production
```
Press Esc and type :wq to save.

```env
# Generate a secret key (run this on your Mac or NAS):
#   python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=paste-your-generated-key-here

DATABASE_URL=sqlite:///cinemaclub.db

# Set this to your NAS IP for local access, or your custom domain for external
FRONTEND_URL=http://YOUR-NAS-IP:8080

# Gmail SMTP — required: sign-in links are delivered by email
SMTP_EMAIL=your-club@gmail.com
SMTP_PASSWORD=your-gmail-app-password
```

### Step 3: Build and start the containers

Still via SSH on your NAS:

```bash
cd /volume1/docker/cinema-club-dc
sudo docker-compose up -d --build
```

This will:
1. Build the Python backend image (Flask + Gunicorn)
2. Build the frontend image (React build → nginx)
3. Start both containers
4. Run database migrations and seed the admin account
5. Create a persistent volume for the SQLite database

**First build takes 3-5 minutes.** Subsequent rebuilds are faster due to Docker layer caching.

### Step 4: Verify it's running

Open a browser and go to:

```
http://YOUR-NAS-IP:8080
```

You should see the Cinema Club DC login page. Enter the admin account's email and open the sign-in link that arrives in that inbox.

To check container status:

```bash
sudo docker-compose ps
```

To view logs:

```bash
# Backend logs
sudo docker logs cinemaclub-backend

# Frontend/nginx logs
sudo docker logs cinemaclub-frontend

# Follow logs in real-time
sudo docker logs -f cinemaclub-backend
```

### Step 5: Scrape initial showtime data

```bash
sudo docker exec cinemaclub-backend python scraper.py
```

This populates the database with current showtimes from Suns Cinema and AFI Silver.

### Step 6: Set up scheduled scraping

Open **Synology DSM** in your browser → **Control Panel** → **Task Scheduler**.

1. Click **Create** → **Scheduled Task** → **User-defined script**
2. **General tab**:
   - Task name: `Cinema Club Scraper`
   - User: `root`
3. **Schedule tab**:
   - Run every day, repeat every 6 hours (or your preferred interval)
4. **Task Settings tab** → paste this script:

```bash
docker exec cinemaclub-backend python scraper.py >> /volume1/docker/cinema-club-dc/scraper.log 2>&1
```

5. Click **OK**

The scraper will now run automatically to keep showtimes up to date.

---

### Custom Domain Setup (Optional)

If you want to access Cinema Club DC from outside your home network with a custom domain like `cinema.yourdomain.com`:

#### Option A: Cloudflare Tunnel (Recommended — no port forwarding)

##### Step 1: Move DNS to Cloudflare

1. Create a free [Cloudflare account](https://dash.cloudflare.com)
2. Click **Add a Site** → enter your domain (e.g., `cinemaclubdc.com`)
3. Select the **Free plan**
4. Cloudflare will give you two nameservers (e.g., `anna.ns.cloudflare.com`, `bob.ns.cloudflare.com`)
5. At your registrar (e.g., Namecheap → Domain List → your domain → Nameservers), change from default DNS to **Custom DNS** → paste the two Cloudflare nameservers
6. Wait for propagation (usually 15-30 minutes, can take up to 24 hours)

##### Step 2: Create a Cloudflare Tunnel

1. In Cloudflare dashboard → **Zero Trust** → **Networks** → **Tunnels**
2. Click **Create a tunnel** → name it (e.g., `cinema-club-nas`)
3. Copy the tunnel token
4. **Important**: Delete any existing A or AAAA DNS records for your root domain (`cinemaclubdc.com`) in **Cloudflare → DNS → Records**. These conflict with the tunnel's CNAME record and will cause errors.
5. In the tunnel's **Public Hostname** tab, add:

   | Setting | Value |
   |---------|-------|
   | Public hostname | `cinemaclubdc.com` |
   | Service Type | **HTTP** |
   | Service URL | `cinemaclub-frontend:80` |

   The service URL uses the Docker container name (not `localhost`) because cloudflared runs on the same Docker network.

##### Step 3: Run cloudflared on your NAS

SSH into your NAS and run cloudflared as a Docker container:

```bash
sudo docker run -d --name cloudflared \
  --restart unless-stopped \
  --network cinema-club-dc_default \
  cloudflare/cloudflared:latest tunnel --no-autoupdate --protocol http2 run \
  --token YOUR_TUNNEL_TOKEN
```

**Critical flags:**
- `--network cinema-club-dc_default` — must match the Docker network your app containers use (check with `sudo docker network ls`)
- `--protocol http2` — **required on Synology NAS**. The default QUIC protocol fails with `sendmsg: invalid argument` errors due to UDP issues on Synology's kernel. HTTP/2 works reliably.

##### Step 4: Set SSL/TLS mode

In **Cloudflare dashboard → SSL/TLS → Overview**, set the mode to **"Flexible"**.

This is required because the nginx container serves HTTP (not HTTPS). The tunnel itself provides the secure transport. Using "Full" mode will cause **Error 525: SSL Handshake Failed**.

##### Step 5: Set up www redirect

Browsers often default to `www.yourdomain.com`. Without this, visitors will get a blank page.

1. **Add a DNS record**: Cloudflare → DNS → Records → Add Record:
   - Type: **CNAME**, Name: `www`, Target: `cinemaclubdc.com`, Proxy: **Proxied** (orange cloud)
2. **Add a redirect rule**: Cloudflare → Rules → Redirect Rules → Create Rule:
   - Rule name: `www to root`
   - When: Hostname equals `www.cinemaclubdc.com`
   - Then: Dynamic redirect to `https://cinemaclubdc.com/${http.request.uri.path}`, status **301**, preserve query string

##### Step 6: Update `.env.production` and rebuild

```env
FRONTEND_URL=https://cinemaclubdc.com
```

```bash
cd /volume1/docker/cinema-club-dc
sudo docker-compose up -d --build
```

#### Option B: Synology DDNS + Reverse Proxy

1. **Enable Synology DDNS**:
   - DSM → Control Panel → External Access → DDNS
   - Add a Synology-provided hostname (e.g., `yourname.synology.me`)
   - Or use a custom domain with your own DDNS provider
2. **Set up port forwarding** on your router:
   - Forward port 443 (HTTPS) to your NAS IP
3. **Set up Synology Reverse Proxy**:
   - DSM → Control Panel → Login Portal → Advanced tab → Reverse Proxy
   - Click **Create**:
     - Description: `Cinema Club DC`
     - Source: Protocol `HTTPS`, Hostname `cinema.yourdomain.com`, Port `443`
     - Destination: Protocol `HTTP`, Hostname `localhost`, Port `8080`
4. **Set up SSL certificate**:
   - DSM → Control Panel → Security → Certificate
   - Add a new certificate via Let's Encrypt for your domain
   - Assign it to the reverse proxy entry in the Settings tab

---

### Managing the Deployment

#### Restart containers

```bash
cd /volume1/docker/cinema-club-dc
sudo docker-compose restart
```

#### Rebuild after code changes

```bash
cd /volume1/docker/cinema-club-dc
sudo docker-compose up -d --build
```

#### Stop everything

```bash
cd /volume1/docker/cinema-club-dc
sudo docker-compose down
```

#### View database (debug)

```bash
# Find the volume location
sudo docker volume inspect cinema-club-dc_db-data

# Open with sqlite3
sudo docker exec cinemaclub-backend python -c "
from app import app, db, Movie, Showtime
with app.app_context():
    print(f'Movies: {Movie.query.count()}')
    print(f'Showtimes: {Showtime.query.count()}')
"
```

#### Backup the database

```bash
# Copy the SQLite file out of the container
sudo docker cp cinemaclub-backend:/app/instance/cinemaclub.db ./cinemaclub-backup.db
```

#### Reset everything (fresh start)

```bash
cd /volume1/docker/cinema-club-dc
sudo docker-compose down -v   # -v removes the database volume
sudo docker-compose up -d --build
sudo docker exec cinemaclub-backend python scraper.py
```

---

### Troubleshooting

| Problem | Solution |
|---------|----------|
| Port 8080 already in use | Change the port in `docker-compose.yml`: `"8090:80"` instead of `"8080:80"` |
| Container won't start | Check logs: `sudo docker logs cinemaclub-backend` |
| Frontend loads but API fails | Verify backend is running: `sudo docker-compose ps` |
| Database empty after restart | Ensure the `db-data` volume wasn't removed. Run scraper again. |
| Permission denied on NAS | Use `sudo` for all docker commands, or add your user to the `docker` group |
| Can't SSH into NAS | Enable SSH: DSM → Control Panel → Terminal & SNMP → Enable SSH service |
| Build fails on ARM NAS | The Dockerfiles use standard images that support ARM64 (DS220+, DS920+, etc.) |
| Cloudflare Error 525 (SSL Handshake Failed) | Set SSL/TLS mode to **Flexible** (not Full). The origin nginx serves HTTP only. |
| Cloudflare tunnel QUIC/UDP errors (`sendmsg: invalid argument`) | Add `--protocol http2` flag to the cloudflared Docker run command. QUIC doesn't work on Synology NAS. |
| Tunnel DNS error: "A, AAAA, or CNAME record already exists" | Delete existing A/AAAA records for the domain in Cloudflare DNS before configuring the tunnel hostname. |
| `www.domain.com` shows blank page | Add a CNAME record for `www` + a Cloudflare redirect rule to the root domain. |
| Cloudflared can't reach frontend container | Ensure cloudflared is on the same Docker network: `--network cinema-club-dc_default`. Verify with `sudo docker inspect cloudflared --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'` |
| `.DS_Store` conflicts on `git pull` | Run `git stash && git pull && git stash drop`. Add `.DS_Store` to `.gitignore`. |

---

## Tech Stack

- **Backend**: Flask, Flask-SQLAlchemy, SQLite (WAL mode), BeautifulSoup4, Gmail SMTP
- **Frontend**: React 18, Vite, react-router-dom v6
- **Styling**: Custom CSS dark theme with CSS variables
- **No external UI libraries** — everything is hand-crafted
