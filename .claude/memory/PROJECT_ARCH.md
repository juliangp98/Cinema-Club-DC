---
name: Cinema Club DC Architecture
description: Tech stack, project structure, and key architectural decisions for the Cinema Club web app
type: project
---
 
## Tech Stack
- **Backend**: Python 3.12, Flask, SQLAlchemy, SQLite (`backend/cinemaclub.db`)
  - Virtual env at `backend/venv/` — run with `./venv/bin/python app.py`
  - Runs on port 5001 (port 5000 blocked by AirTunes on macOS)
  - Session-based auth with cookies
  - Email via Gmail SMTP (falls back to console if not configured)
- **Frontend**: React 18, Vite, react-router-dom v6
  - Runs on port 5173, proxies `/api` to backend
  - Single CSS file: `frontend/src/index.css` (no CSS modules/Tailwind)
  - Design system: dark cinema theme with amber/cream/muted palette, custom fonts (Bebas Neue, Playfair Display, DM Mono)
 
## Key Files
- `backend/app.py` — entire backend in one file (models, routes, migrations, seeding)
- `frontend/src/App.jsx` — router, auth state, group selection
- `frontend/src/pages/Calendar.jsx` — main calendar view
- `frontend/src/pages/GroupDiscovery.jsx` — groups browse/create/manage page
- `frontend/src/components/ShowtimeDrawer.jsx` — right-side drawer for showtime details
- `frontend/src/components/GroupAdmin.jsx` — admin panel for group management
- `frontend/src/components/GroupMembers.jsx` — members overlay with split-panel layout
- `frontend/src/components/UserProfileDrawer.jsx` — site-wide profile drawer (z-index 60)
- `frontend/src/components/ProfileMenu.jsx` — dropdown profile editor from avatar click
- `frontend/src/components/GroupSwitcher.jsx` — group dropdown in calendar header
- `frontend/src/components/ChatSection.jsx` — in-drawer chat for showtimes
 
## Database Migrations
- SQLite doesn't support ALTER TABLE DROP COLUMN — migrations are ADD COLUMN only
- `migrate()` function in app.py runs idempotent ALTER TABLE statements on startup
- When adding new columns, add the migration statement to `migrate()` function
- For breaking schema changes, delete `cinema.db` and let it recreate (dev only)
 
## Z-Index Stacking
- ShowtimeDrawer: 50
- GroupMembers overlay: 55
- UserProfileDrawer: 60
- ProfileMenu / dropdowns: 100