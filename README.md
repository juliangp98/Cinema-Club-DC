# Cinema Club DC

A private calendar app for tracking DC arthouse film showtimes at **Suns Cinema** and **AFI Silver Theatre**. Groups of friends can RSVP to screenings, react with emojis, chat about movies, and get smart genre-based recommendations.

---

## Features

- **Monthly calendar view** with color-coded theatre pills (orange = Suns, red = AFI)
- **Merged showtimes** — multiple screenings of the same movie on the same day appear as one calendar entry with comma-separated times
- **Showtime drawer** — click any entry to see movie poster, description, director, runtime, cast, trailer link, and per-screening RSVP/tickets/calendar export
- **Per-screening RSVP** — Going / Maybe / Can't Go for each individual showtime, independent across screenings
- **Calendar export** — add screenings to Google Calendar or download .ics for Apple Calendar
- **Emoji reactions** — 24 curated emojis per showtime (group-scoped)
- **Group chat** — real-time discussion threads per showtime (10s polling)
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
│   │   │   ├── Calendar.jsx      # Monthly calendar with filter bar
│   │   │   ├── Login.jsx         # Login / Signup / Invite acceptance
│   │   │   └── GroupDiscovery.jsx # Browse, search, join, create groups
│   │   └── components/
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

The seed creates an admin account: `sunscinemafanclub@gmail.com` (name: Julian) as admin of "Chuds Cinema" group. Log in with this email to access the calendar.

New users can sign up with any email + name — they'll be redirected to the Groups page to find and join a group.

---

## Environment Variables

```env
SECRET_KEY=your-random-secret-here
DATABASE_URL=sqlite:///cinemaclub.db
FRONTEND_URL=http://localhost:5173

# Gmail SMTP (optional — falls back to console printing if not set)
SMTP_EMAIL=SunsCinemaFanClub@gmail.com
SMTP_PASSWORD=your-gmail-app-password

# Movie metadata enrichment
TMDB_API_TOKEN=...        # themoviedb.org v4 read token
OMDB_API_KEY=...          # omdbapi.com

# Discord bot / internal API
INTERNAL_API_TOKEN=...    # shared secret between backend and bot (any random hex)
DISCORD_BOT_TOKEN=...     # from discord.com/developers/applications
DISCORD_GUILD_ID=...      # your server id (right-click server → Copy Server ID)
DISCORD_CHANNEL_ID=...    # the #movies channel id
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

- **Login**: Email-only (no password) — `POST /api/auth/login`
- **Signup**: Email + name — `POST /api/auth/signup` (creates account, no group required)
- **Invite**: Admin enters email in group management → creates inactive user with invite token → sends email with acceptance link
- **Accept invite**: User visits `/invite/<token>` → enters name → account activated, added to group
- **No-group handling**: Users without groups are redirected to `/groups` to browse and join

---

## Group System

- **Public groups** are always visible on the Groups page in a paginated list (10 per page)
- **Join requests** require admin approval (admins are emailed)
- **Admin panel** lets you invite by email, approve/deny requests, remove members
- **Group-scoped data**: RSVPs, reactions, and chat messages are all scoped to the active group

---

## Calendar Features

- **Showtime merging**: Multiple screenings of the same movie at the same theatre on the same day are grouped into a single calendar pill showing all times
- **Scrollable day cells**: Days with many events scroll within the cell (max-height: 220px)
- **Theatre filters**: Toggle Suns / AFI visibility in the header
- **Showtime drawer**: Shows movie info once, with each screening having independent RSVP, tickets, and calendar export
- **Attendee dots**: Colored dots on calendar pills showing who's going (deduplicated across screenings)

---

## API Routes

### Auth
- `POST /api/auth/login` — email login
- `POST /api/auth/signup` — create account (email + name)
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
- `GET /api/showtimes?start=&end=&group_id=` — showtimes for date range
- `POST /api/rsvp` — create/update RSVP (going/maybe/not_going)
- `GET /api/showtimes/:id/ical` — iCal export
- `GET /api/showtimes/:id/gcal-url` — Google Calendar URL

### Reactions & Chat
- `POST /api/reactions` — toggle emoji reaction
- `GET /api/messages?showtime_id=&group_id=` — get messages
- `POST /api/messages` — send message

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
- Sync dedupes movies by exact title → TMDB id → normalized title + year.
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

- **Announcements**: polls for unannounced `ScrapeEvent`s every 60s and posts
  rich embeds to `DISCORD_CHANNEL_ID` (#movies) — e.g. "Suns just dropped 23
  new showtimes", with top titles, poster, and a deep link.
- **Watchlist pings**: when a drop includes a movie someone watchlisted, the
  bot @-mentions them (unlinked members get an email instead).
- **Weekly digest**: Mondays 10:00 ET — who's going, what's playing, open polls.
- **Slash commands**: `/showtimes`, `/movie`, `/rsvp`, `/whosgoing`, `/watch`,
  `/polls`, `/leaderboard`, `/digest`, `/link`.
- **Account linking**: profile menu on the site → "Link Discord" → 6-char code
  → `/link <code>` in Discord. RSVPs from Discord then post publicly.

Bot setup (one-time):
1. Create an application + bot at https://discord.com/developers/applications.
2. Enable no privileged intents (defaults are fine); copy the bot token.
3. Invite it to the server with the `bot` + `applications.commands` scopes and
   Send Messages / Embed Links permissions.
4. Set `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` (server id), `DISCORD_CHANNEL_ID`
   (#movies channel id) in `.env.production`, then `docker-compose up -d --build bot`.

Deep links: `https://cinemaclubdc.com/?showtime=<id>` opens that screening's
drawer; `/?theatre=<slug>` pre-filters the calendar.

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

# Gmail SMTP (optional — emails print to console if not configured)
SMTP_EMAIL=sunscinemafanclub@gmail.com
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

You should see the Cinema Club DC login page. Log in with `sunscinemafanclub@gmail.com`.

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
