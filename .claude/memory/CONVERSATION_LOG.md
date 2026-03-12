# Cinema Club DC — Conversation Log

This log captures the full history of building and iterating on the Cinema Club DC project across multiple Claude sessions. Use this to resume work in a new chat.

---

## Session 1: Initial Setup & Scraper Fixes

### Work Done

1. **Flask import error**: The venv used Python 3.8 instead of 3.12. Fixed by running `./venv/bin/python app.py` directly instead of `python app.py`.

2. **Backend port**: Changed from 5000 to 5001 (port 5000 was in use). Updated `.claude/launch.json` with `autoPort: false`.

3. **Login error**: "No active account" — needed to seed the admin user. Admin email set to `juliangperez98@gmail.com` initially, later changed to `sunscinemafanclub@gmail.com`.

4. **Scraper fixes**:
   - **Suns Cinema**: Rewritten to parse HTML: `div.showtimes-description` → `li[data-date]` → `span.showtime`. Gets 24-25 movies.
   - **AFI Silver**: Rewritten to scrape `silver.afi.com/now-playing/` listing, then visit each `/movies/detail/` page to extract showtimes from `div.show_wrap` / `a.select_show` elements. Gets 70 movies.
   - **E Street Cinema**: Removed entirely (permanently closed).

5. **Title bug**: "CINEMA CLUB" header only showed "CLUB" — fixed in Calendar.jsx.

6. **HTML entity**: `&nearr;` didn't render in ShowtimeDrawer — changed to literal `↗` character.

---

## Session 2: Major Feature Expansion

### Features Added

1. **Profile Menu** (`ProfileMenu.jsx`):
   - Dropdown from user avatar in header
   - Edit display name, avatar color (10 swatches), bio, favorite genres (chip selector)
   - Save updates via `PUT /api/auth/profile`
   - Logout button

2. **Emoji Reactions** (`ReactionBar.jsx`):
   - 24 curated emojis per showtime
   - Toggle reactions via `POST /api/reactions`
   - Group-scoped (unique per user+showtime+group+emoji)

3. **Chat** (`ChatSection.jsx`):
   - Per-showtime message threads
   - 10-second polling for new messages
   - Auto-scroll to bottom, max 2000 chars per message

4. **Group System**:
   - `Group` model with name, slug, description, is_public, created_by
   - `GroupMembership` model with role (admin/member) and status (active/pending)
   - Group CRUD, discover (search public groups), join requests, approve/deny
   - `GroupSwitcher.jsx` — header dropdown to switch active group
   - `GroupDiscovery.jsx` — search, join, create groups
   - `GroupAdmin.jsx` — invite by email, approve/deny pending, manage members
   - Default group: "Chuds Cinema"

5. **Calendar Export** (`ShowtimeDrawer.jsx`):
   - Google Calendar — generates URL via `GET /api/showtimes/:id/gcal-url`
   - Apple Calendar — downloads .ics via `GET /api/showtimes/:id/ical`

6. **Smart Recommendations**: User sets favorite genres in ProfileMenu, backend matches against movie genres, calendar shows star icon on recommended showtimes.

---

## Session 3: Auth/Invite Flow Overhaul + Email

### Fixes Implemented

1. **`POST /api/auth/signup` route** — create account with email + name, no group required.

2. **`POST /api/admin/invite` fixed** — handles all edge cases (existing active user, existing inactive, new user). Never returns 409.

3. **Gmail SMTP email system** (`send_email()` helper):
   - Uses stdlib `smtplib` + `email.mime`
   - Config: `SMTP_EMAIL` and `SMTP_PASSWORD` env vars
   - 4 email templates: invite, added-to-group, join-request (to admins), approved

4. **Frontend signup flow** (`Login.jsx`): Toggle between Login and Signup modes.

5. **No-group handling** (`App.jsx`): Redirects to `/groups` if user has 0 groups.

---

## Session 4: Rename, Calendar Merge, Group Pagination

### Changes Made

1. **Renamed "Cinema Club" → "Cinema Club DC"** everywhere (frontend, backend, emails, package.json).

2. **Calendar showtime merging**: `getGroupedShowtimes(date)` groups by `movie_id + theatre_id`. Single calendar pill per movie-per-theatre-per-day with comma-separated times. Attendee dots deduplicated.

3. **ShowtimeDrawer multi-screening support**: Accepts `showtimes` array, movie info rendered once, "Screenings (N)" section with independent RSVP per screening.

4. **Calendar pill layout**: Changed to vertical flex (time on top, title below). Title clamp reduced to 1 line.

5. **Scrollable day cells**: `.cal-day` max-height 220px with overflow-y auto.

6. **Group discovery pagination**: Backend supports `page`/`per_page` params, frontend shows Previous/Next.

---

## Session 5: Group Admin UX, Theatre Selection, Mobile

### Features Implemented

1. **Group Name/Description Editing** — Admin can edit via PUT `/api/groups/<slug>`

2. **Group Deletion** — `DELETE /api/groups/<slug>` with cascading delete (Messages, Reactions, RSVPs, GroupMemberships, then Group). Frontend "Danger Zone" with confirm.

3. **Group Members Viewing** (`GroupMembers.jsx`) — modal overlay (z-index 55) with split-panel layout. Left: scrollable member list. Right: selected member's profile preview.

4. **User Profile Drawer** (`UserProfileDrawer.jsx`) — right-side sliding drawer (z-index 60). Fetches `/api/users/<id>/profile` with privacy check (must share an active group). Accessible from attendee chips, chat avatars, GroupMembers, GroupAdmin.

5. **User Menu on Groups Page** — avatar + ProfileMenu added to GroupDiscovery header.

6. **Theatre Selection Per Group**:
   - Backend: `theatres` column on Group model (comma-separated slugs)
   - `GET /api/theatres`, `GET /api/groups/by-id/<int:group_id>`
   - Frontend: toggleable theatre pills in create/edit group forms
   - Calendar dynamically filters by group's selected theatres

7. **Mobile Responsive CSS**:
   - `@media (max-width: 768px)`: header wraps, calendar single-column day list, drawers full-width, group members full-screen stacked
   - `@media (max-width: 480px)`: smaller fonts/spacing throughout

---

## Session 6 (2026-03-12): Scraper Overhaul, Filter Bar, E Street Removal

### Scraper Work

1. **Suns Cinema scraper updated** — now also scrapes the "Coming Soon" / upcoming films page (`/upcoming-films-3/`). Previously was missing several movies on dates like the 15th, 18th, 22nd, etc.

2. **AFI Silver scraper rewritten** — the old scraper looked for `/Browsing/Films/` URLs that no longer exist. The site migrated to a Vista Cinema platform. New scraper:
   - Discovers film links from `/now-playing/` (finds `movies/detail/{ID}` links)
   - Visits each detail page and parses `div.show_wrap` elements containing `<p>` date headers and `<a class="select_show">` time links
   - Handles times in "a.m./p.m." format
   - Cap raised from 40 to 80 (sorted for deterministic order) — now scrapes all 70 films
   - Poster URLs from Vista CDN: `FilmPosterGraphic/f-{ID}`

3. **E Street Cinema removed** from scraper entirely (theatre permanently closed).

4. **Database synced**: 70 AFI movies + 23 Suns movies with full showtimes.

### Filter Bar Feature (Calendar.jsx + index.css)

Replaced the old theatre pill buttons in the header with a new **filter bar** below the header:

1. **Theatre Dropdown** — compact dropdown button with colored dots (AFI red, SUNS amber). Uses shorthand names via `THEATRE_SHORT = { suns: "SUNS", afi: "AFI", estreet: "E ST" }`. Multi-select with checkboxes.

2. **Movie Search** — text input with diacritic-insensitive matching (`normalize()` strips accents, e.g. "sirat" matches "SIRÂT"). Dropdown shows matching movies with checkboxes for multi-select. Badge shows count of selected movies.

3. **Time-of-Day Pills** — Morning (before 12pm), Afternoon (12–5pm), Evening (5pm+). Three toggle buttons with icons (☀, ⛅, 🌙). Multi-select.

4. **Clear Button** (✕) — appears when any movie or time-of-day filters are active.

5. **Filter Logic** in `getGroupedShowtimes()`:
   - Theatre filter: `activeTheatres` Set (unchanged)
   - Movie filter: `selectedMovies` Set — if non-empty, only show matching `movie.id`
   - Time filter: `timeOfDay` Set — checks hour against `TIME_BUCKETS` test functions

6. **New State Variables**: `searchText`, `selectedMovies` (Set), `timeOfDay` (Set), `showTheatreDD`, `showMovieDD`. Uses `useRef` for outside-click detection, `useMemo` for `availableMovies` and `filteredMovies`.

7. **Mobile Responsive**: Filter bar wraps — theatre dropdown + time icons on first row, full-width search on second row. Time pill labels hidden on mobile (icon-only).

8. **Scrollbar styling**: Calendar grid scrollbar inset from right edge with transparent track gap.

### CSS Changes
- Removed `.theatre-filters`, `.theatre-pill` styles
- Added `.filter-bar`, `.filter-dd`, `.filter-dd-btn`, `.filter-dd-menu`, `.filter-dd-item`, `.filter-dot`, `.filter-search-*`, `.filter-time-*`, `.filter-badge`, `.filter-clear` styles
- Filter dropdown menu z-index: 60
- Calendar grid: `scrollbar-gutter: stable`, scrollbar track/thumb with 4px right border for inset effect

---

## Session 7 (2026-03-12): Rename to Cinema Club DC, Custom Domain Planning

### Changes Made

1. **Renamed "DC Cinema Club" → "Cinema Club DC"** everywhere — backend emails, app.py fallback name, iCal PRODID, frontend headers/logos (App.jsx, Calendar.jsx, Login.jsx, GroupDiscovery.jsx), HTML title, package.json name, docker-compose comment, .env files, README, and Claude memory files.

2. **Rationale**: Putting the location (DC) at the end allows for expandability to other cities (Cinema Club NYC, Cinema Club LA, etc.).

3. **Custom domain planned**: `cinemaclubdc.com` via Namecheap, to be configured with Cloudflare DNS + Tunnel pointing to the self-hosted Synology NAS.

4. **Project published on GitHub** and fully self-hosted on Synology NAS via Docker.

---

## Current State (as of 2026-03-12)

### What's Working
- Full auth flow (register, login, logout) from both Calendar and Groups pages
- Group CRUD: create (with theatre selection), edit (name, description, theatres), delete
- Group membership: join requests, admin approve/deny, remove members
- Calendar: monthly view with showtimes, filter bar (theatre dropdown, movie search, time-of-day), RSVP, chat, reactions
- Profile system: edit own profile, view others' profiles via drawer
- Scrapers: Suns Cinema (now-showing + coming-soon) and AFI Silver (70 films from Vista platform)
- Mobile responsive: all pages usable at 375px width

### Theatre Data
- Suns Cinema (slug: "suns", color: #e8a838 / var(--suns))
- AFI Silver Theatre (slug: "afi", color: #c45c3a / var(--afi))
- E Street Cinema removed from scraper but CSS var `--estreet: #4a7c6f` still exists

### Key Technical Details
- Python 3.12 venv at `backend/venv/` — always use `./venv/bin/python`
- SQLite DB at `backend/cinemaclub.db` — delete to reset
- Session-based auth with Flask's `session` object
- All API calls use `credentials: "include"` for cookies
- Group ID stored in `localStorage` as `cinemaclub_group_id`
- Showtime unique constraint: `(movie_id, theatre_id, start_time)`
- RSVP unique constraint: `(user_id, showtime_id, group_id)`
- `.claude/launch.json` — backend (port 5001) + frontend (port 5173)
- `frontend/vite.config.js` — proxy `/api` → `http://127.0.0.1:5001`
- index.css is ~1780 lines, single global stylesheet

### Known Issues / Future Work
1. **Email delivery**: Only prints to console until `SMTP_EMAIL`/`SMTP_PASSWORD` env vars set
2. **No password auth**: Login is email-only. Consider magic links or OAuth for production.
3. **Scraper fragility**: Depends on specific HTML structures — will break if theatres redesign
4. **No real-time updates**: Chat uses 10s polling. Could upgrade to WebSockets.
