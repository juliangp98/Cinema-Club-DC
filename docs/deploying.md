# Deploying

The site runs as three Docker containers — `cinemaclub-backend` (Flask + Gunicorn, the scrapers),
`cinemaclub-frontend` (the React build on nginx, port 8080) and `cinemaclub-bot` (the Discord bot) —
from `docker-compose.yml`. Ours runs on a Synology NAS with Container Manager, reached through a
Cloudflare Tunnel; any machine with Docker and Compose works the same way.

## 1. Get the code onto the machine

Enable SSH on the NAS (Control Panel → Terminal & SNMP), then:

```bash
ssh your-nas-user@NAS-IP
cd /volume1/docker
git clone https://github.com/juliangp98/Cinema-Club-DC.git cinema-club-dc
cd cinema-club-dc
```

## 2. Settings

```bash
cp .env.production.example .env.production
vi .env.production
```

Fill in at least `SECRET_KEY`, `FRONTEND_URL`, `SMTP_EMAIL` / `SMTP_PASSWORD`, `INTERNAL_API_TOKEN` and, on
a fresh install, `ADMIN_EMAIL`. Every setting and where to get it: [configuration.md](configuration.md).
The bot's own steps: [discord-bot.md](discord-bot.md).

**DNS inside the containers.** `docker-compose.yml` points the backend and bot at `192.168.0.1` (our
router) for DNS, because Docker's built-in resolver stopped forwarding on our NAS. If your router has
another address, change both `dns:` entries — or delete them if your containers resolve names fine.

## 3. Build and start

```bash
sudo docker-compose up -d --build
```

The first build takes a few minutes. On start the backend brings the database up to date (tables,
migrations, one-time backfills, the theatres, the first admin) and prints any unset settings:

```bash
sudo docker-compose ps
sudo docker logs cinemaclub-backend      # look for "Settings not set" and what each means
sudo docker logs cinemaclub-bot
```

Open `http://NAS-IP:8080` and sign in with `ADMIN_EMAIL`; the link arrives by email.

## 4. Showtimes

The first scrape fills the calendar (10–15 minutes):

```bash
sudo docker exec cinemaclub-backend python scraper.py
```

Then schedule it — DSM → Control Panel → Task Scheduler → Create → Scheduled Task → User-defined
script, user `root`:

| Task | Repeat | Script |
|---|---|---|
| Cinema Club scraper | every 6 hours | `docker exec cinemaclub-backend python scraper.py >> /volume1/docker/cinema-club-dc/scraper.log 2>&1` |
| Cinema Club Suns | every 30 minutes | `docker exec cinemaclub-backend python scraper.py --only suns >> /volume1/docker/cinema-club-dc/scraper-suns.log 2>&1` |

Suns posts films a week before tickets go on sale, so the 30-minute run sends on-sale alerts quickly
(it also reads members' Letterboxd diaries when they're due). On any other machine, cron does the same.
How the scrapers pace themselves: [scrapers.md](scrapers.md).

## 5. After the first deploy

- **Film details for older films** — `sudo docker exec cinemaclub-backend python backfill_enrichment.py --refresh`
  adds OMDb ratings and genres to films already in the database. OMDb's free key allows 1,000 calls a
  day; re-run it daily until it reports nothing left (it resumes where it stopped).
- **Push alerts** — `sudo docker exec cinemaclub-backend python vapid_keys.py`, paste the two lines into
  `.env.production`, set `VAPID_SUBJECT`, and rebuild.
- **Someone can't sign in** — `sudo docker exec cinemaclub-backend python account_check.py person@example.com`
  shows their account (active? Discord linked? recent sign-in requests). Add `--send` to send a real
  sign-in email and see whether Gmail took it, `--link` to print a one-time link to pass on yourself, or
  run it with just `--smtp` to test the mail login; it says whether Gmail refused the password or
  couldn't be reached (DNS, below). If the site says it couldn't send the email, the backend log has the
  reason (`sudo docker logs cinemaclub-backend 2>&1 | grep "Email failed"`).
- **DNS** — the router on the NAS fails about 1 name lookup in 6 ("Temporary failure in name
  resolution": sign-in emails, TMDB and OMDb, the AI). So the backend and bot look names up through the
  club's own caching resolver, the `dns` service (Dockerfile.dns, `dns/unbound.conf.in`): it asks the
  router and keeps the answers, and when the router fails, a name it has seen before is answered from the
  cache. If the resolver is ever down, the containers ask the router directly. Sign-in emails are also
  tried three times (over about 4 seconds). `account_check.py --smtp --repeat 50` shows how often a
  lookup still fails; `sudo docker logs cinemaclub-dns` shows the resolver's own log.
  The resolver sits at a fixed address (172.29.53.53) on the project's network (172.29.53.0/24). If
  Docker says that range overlaps another network on the NAS, pick another `/24` and change it in
  `docker-compose.yml` (the subnet, the resolver's `ipv4_address` and both `dns:` lists).
  The first deploy with it needs the network made again, once:
  `sudo docker-compose down && sudo docker-compose up -d --build` (the database is a volume: it stays).
- **Search engines** — in Google Search Console add a Domain property for your domain, verify it with the
  TXT record in your DNS, and submit `https://your-domain/sitemap.xml`. Private pages are `noindex` and
  `robots.txt` keeps crawlers out of them.
- **Other clubs' Discord servers** — Discord Developer Portal → your application → Bot → turn on **Public
  Bot**, so club admins can add it from Club settings → Discord. The bot registers its own (home) server
  when it starts; `docker logs cinemaclub-bot` says how many servers it's in.

## A domain through Cloudflare (no port forwarding)

1. **DNS on Cloudflare.** Add your site to a free Cloudflare account and point your registrar's
   nameservers at the two Cloudflare gives you.
2. **A tunnel.** Zero Trust → Networks → Tunnels → Create a tunnel; copy its token. Delete any A or AAAA
   records for the root domain first (they clash with the tunnel's CNAME). Add a public hostname:
   your domain → service **HTTP** → `cinemaclub-frontend:80`.
3. **Run cloudflared on the same Docker network:**

   ```bash
   sudo docker run -d --name cloudflared --restart unless-stopped \
     --network cinema-club-dc_default \
     cloudflare/cloudflared:latest tunnel --no-autoupdate --protocol http2 run --token YOUR_TUNNEL_TOKEN
   ```

   `--protocol http2` is needed on Synology (QUIC fails with `sendmsg: invalid argument`). The network
   name must match `sudo docker network ls`.
4. **SSL/TLS → Overview → Flexible.** nginx serves plain HTTP inside; "Full" gives Error 525.
5. **www.** Add a proxied CNAME `www` → your domain, and a redirect rule from `www.your-domain` to
   `https://your-domain/${http.request.uri.path}` (301, keep the query string).
6. Set `FRONTEND_URL` and `SITE_URL` to `https://your-domain` and rebuild.

(Without Cloudflare: Synology DDNS, forward port 443 to the NAS, and a DSM reverse proxy from
`https://your-domain` to `http://localhost:8080` with a Let's Encrypt certificate.)

## Updating

```bash
cd /volume1/docker/cinema-club-dc
git pull
sudo docker-compose up -d --build
```

The rebuild restarts all three containers; the bot re-registers its slash commands as it starts. Then
purge Cloudflare's cache (Caching → Configuration → Purge Everything) so visitors get the new frontend.
Database changes apply themselves on start.

## Backups

The database is one SQLite file in the `db-data` volume. Before a migration that rebuilds a table, the
backend saves a copy next to it (`*.bak`). To take your own:

```bash
sudo docker exec cinemaclub-backend python -c "import sqlite3; s=sqlite3.connect('instance/cinemaclub.db'); s.execute(\"VACUUM INTO 'instance/backup.db'\")"
sudo docker cp cinemaclub-backend:/app/instance/backup.db ./cinemaclub-backup.db
```

`sudo docker-compose down -v` deletes the volume — and the database with it.

## Troubleshooting

| Problem | What to do |
|---|---|
| A container won't start | `sudo docker logs cinemaclub-backend` (or `-bot`, `-frontend`) |
| "Settings not set" in the logs | Each line says what goes without it; see [configuration.md](configuration.md) |
| Scrapes or the bot fail with "Temporary failure in name resolution" | Docker's DNS: set the `dns:` entries in `docker-compose.yml` to your router's address |
| Port 8080 in use | Change `"8080:80"` in `docker-compose.yml` |
| The site loads but the API fails | `sudo docker-compose ps` — is the backend up? |
| Cloudflare Error 525 | SSL/TLS mode **Flexible** |
| Tunnel errors `sendmsg: invalid argument` | `--protocol http2` on cloudflared |
| "A, AAAA, or CNAME record already exists" | Delete the root domain's A/AAAA records before adding the tunnel hostname |
| `www.` shows a blank page | The `www` CNAME and redirect rule above |
| cloudflared can't reach the frontend | Same Docker network: `--network cinema-club-dc_default` |
| A theatre's showtimes stopped updating | The owner gets a DM about scraper errors (once a day per theatre); `scraper.log` has details; see [scrapers.md](scrapers.md) |
| Slash commands don't appear in a new server | Global commands can take up to an hour the first time |
| The bot (or the site) is slow or fails on the first try after a quiet spell | Turn off **HDD hibernation** (Synology: Control Panel → Hardware & Power): spinning the disks back up takes longer than Discord's 3 seconds. Then the bot's log says where time goes: `slow interaction: /x … reached the bot 2.4s after it was sent` (the bot itself was busy or the network slow), `api: GET /api/internal/… took 4.1s` (the backend was slow), `api: … failed` / `timed out` (it couldn't answer) |
