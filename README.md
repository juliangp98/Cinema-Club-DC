# DC Cinema Club

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

- **Suns Cinema**: Parses `sunscinema.com/upcoming-films-3/` HTML — extracts from `div.showtimes-description`, `li[data-date]`, `span.showtime`
- **AFI Silver**: Scrapes `silver.afi.com/now-playing/` listing page, then visits each individual film detail page to get showtimes from `div.show_wrap` / `span.select_show`
- **E Street Cinema**: Removed (permanently closed)
- Scraper fails gracefully — one broken source won't affect the other

### Run scraper on a schedule

```bash
crontab -e
# Add (runs every 6 hours):
0 */6 * * * cd /path/to/Cinema\ Club/backend && ./venv/bin/python scraper.py >> /var/log/dc-cinema-scraper.log 2>&1
```

---

## Deployment on Synology NAS (Docker)

The recommended way to self-host DC Cinema Club is via Docker on a Synology NAS using **Container Manager** (the built-in Docker UI). This gives you a persistent, auto-restarting deployment with a custom domain and HTTPS.

### Prerequisites

- Synology NAS with **Container Manager** installed (Package Center → Container Manager)
- SSH access enabled on your NAS (Control Panel → Terminal & SNMP → Enable SSH)
- A computer on the same network to SSH into the NAS
- (Optional) A custom domain name if you want external access

### Step 1: Copy the project to your NAS

Copy the entire `Cinema Club` folder to a shared folder on your NAS. You can use Finder (SMB), `scp`, or Synology Drive.

```bash
# Example:
scp -r "/Users/[user]/Documents/DC Cinema Club" your-nas-user@NAS-IP:/volume1/docker/dc-cinema-club
```

Or drag the folder into a shared folder via Finder → Connect to Server → `smb://NAS-IP`.

A good location is `/volume1/docker/cinema-club/`.

### Step 2: Create the production environment file

SSH into your NAS:

```bash
ssh your-nas-user@NAS-IP
```

Navigate to the project and create your production config:

```bash
cd /volume1/docker/cinema-club
cp .env.production.example .env.production
```

Edit `.env.production` with your values:

```bash
vi .env.production
```

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
cd /volume1/docker/cinema-club
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

You should see the DC Cinema Club login page. Log in with `sunscinemafanclub@gmail.com`.

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
docker exec cinemaclub-backend python scraper.py >> /volume1/docker/cinema-club/scraper.log 2>&1
```

5. Click **OK**

The scraper will now run automatically to keep showtimes up to date.

---

### Custom Domain Setup (Optional)

If you want to access DC Cinema Club from outside your home network with a custom domain like `cinema.yourdomain.com`:

#### Option A: Cloudflare Tunnel (Recommended — no port forwarding)

1. **Buy a domain** on Cloudflare or transfer an existing one to Cloudflare DNS
2. **Install `cloudflared`** on your NAS:
   - SSH into your NAS
   - Download the ARM64 or AMD64 binary from [Cloudflare Tunnel releases](https://github.com/cloudflare/cloudflared/releases)
   - Or run it as a Docker container (easiest on Synology):
     ```bash
     sudo docker run -d --name cloudflared --restart unless-stopped \
       cloudflare/cloudflared:latest tunnel --no-autoupdate run \
       --token YOUR_TUNNEL_TOKEN
     ```
3. **Create a tunnel** in the Cloudflare Zero Trust dashboard:
   - Go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com) → Networks → Tunnels
   - Create a tunnel, copy the token
   - Add a public hostname: `cinema.yourdomain.com` → `http://localhost:8080`
4. **Update `.env.production`**:
   ```env
   FRONTEND_URL=https://cinema.yourdomain.com
   ```
5. **Rebuild** to pick up the new FRONTEND_URL:
   ```bash
   cd /volume1/docker/cinema-club
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
     - Description: `DC Cinema Club`
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
cd /volume1/docker/cinema-club
sudo docker-compose restart
```

#### Rebuild after code changes

```bash
cd /volume1/docker/cinema-club
sudo docker-compose up -d --build
```

#### Stop everything

```bash
cd /volume1/docker/cinema-club
sudo docker-compose down
```

#### View database (debug)

```bash
# Find the volume location
sudo docker volume inspect cinema-club_db-data

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
cd /volume1/docker/cinema-club
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

---

## Tech Stack

- **Backend**: Flask, Flask-SQLAlchemy, SQLite (WAL mode), BeautifulSoup4, Gmail SMTP
- **Frontend**: React 18, Vite, react-router-dom v6
- **Styling**: Custom CSS dark theme with CSS variables
- **No external UI libraries** — everything is hand-crafted
