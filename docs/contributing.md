# Contributing

How the code is laid out is in the [README](../README.md#how-its-built); how to run it locally is under
[Running it locally](../README.md#running-it-locally). This page is how work gets done here.

## Tests

```bash
tests/run.sh                         # everything: pytest (backend + bot), then vitest (frontend)
tests/run.sh -k scraper              # Python tests whose names match
tests/run.sh backend/test_search.py  # one file
tests/run.sh frontend                # only the component tests
```

It makes its own environments the first time. Every Python test starts from a fresh copy of
`tests/fixtures/base.db` (real films, fake accounts), so migrations run on every test too. The bot's
tests drive real commands against the real backend with no Discord connection. More:
[tests/README.md](../tests/README.md).

Check the exit code of `tests/run.sh` before calling something done — and for anything you can see in the
browser, look at it too, on a **copy** of a database (`DATABASE_URL=sqlite:////path/to/copy.db`), never the
one you work in.

## House rules

**Every feature ships whole.** Not "the feature now, tidy it up later" — in the same change:

- **One definition per thing.** A list, label or rule used in two places lives in one (the backend's
  domain modules, `notify.TYPE_GROUPS`, `TICKET_OPTIONS`, `soldOutLabel`…); the frontend calls the API
  through `api.js` (`getJson`, `useJson`, `send`); the bot's failures go through `api_failure` /
  `reply_failure`.
- **The UI kit first.** Build from `frontend/src/ui` (Panel, PageHeader, SectionTitle, Settings rows,
  SearchField, Segmented, TicketRow, Sheet, StatTiles…) and the tokens in `index.css` — no new colors, no
  inline static styles. Admins see every piece live at `/styleguide`; a new kit piece goes there too.
- **Tests** — pytest for the backend and bot, Vitest for components.
- **The page tour** — `frontend/src/shell/pageTours.js` gets a step for anything new on a page.
- **Help** — `frontend/src/help.json` gets the answer (links are `[words](place-id)` or
  `[words](help:topic)`; ✨ Ask reads the same file).
- **The bot's `/help`** — `bot/embeds.py` `HELP_SECTIONS`, whenever a command changes.

**Notifications are opt-in.** Nothing emails, DMs, pushes or pings anyone until they've said yes; ask once,
at the moment it first matters. **New games and features start switched off** (a club setting) until a
club's admins turn them on. **What members see stays in their clubs** — only theatres, films and showtimes
are public (and indexed); everything personal is `noindex` and behind membership.

**Writing.** Plain words, short sentences, sentence case, "you". Say what something does, not how it
works. The same goes for code comments: a line on *why*, where it isn't obvious.

## The Discord bot

Develop with your own test application and server ([discord-bot.md](discord-bot.md)); never run a local
bot with the live server's token. A command lives in its feature module in `bot/features/`, registers any
persistent buttons and loops, and is listed in `/help`.

Every Discord question is about one club — each club can have its own server. Pass the club to the
backend helpers (`on_discord(user, group_id)`, `present_user_ids(group_id)`, `split_present(…, group_id)`,
`can_share`, `watch_shared`); in the bot, send `club()` (or `discord_identity`, which includes it) and
post with `channel_for(group_id)`; a loop goes through `connected_clubs()`, calling `use_club` for each.

## Scrapers

Be a good guest: one pooled connection, pauses between requests, `Retry-After` honored, nothing that gets
around a bot check. Every scraper is tested against a saved copy of its site's page — when a site changes,
update both. [scrapers.md](scrapers.md) has the details.

## Settings

A new environment setting goes in both templates (`.env.production.example`, `backend/.env.example`) and
in [configuration.md](configuration.md); `tests/backend/test_config.py` fails if the code reads one the
templates don't list. If the site can't do without it, add it to `backend/config_check.py`.
