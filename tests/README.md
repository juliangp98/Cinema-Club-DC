# Tests

The whole site and bot, tested together: the real backend (Flask, on a copy of
an old database) and the real bot code (its calls go to the backend in-process,
so there's no server, no network and no Discord connection) — then the site's
own components (React, in a simulated browser, with the server faked).

```bash
tests/run.sh                         # everything (~5 seconds)
tests/run.sh -k discord              # tests whose names match
tests/run.sh backend/test_search.py  # one file
tests/run.sh -x -s                   # stop at the first failure, show prints
tests/run.sh frontend                # only the component tests
```

With no arguments it runs everything and exits non-zero if anything failed.

`run.sh` builds its own environment (`tests/.venv`, from `requirements.txt`) the
first time.

## Layout

| | |
|---|---|
| `backend/` | the site's API, by feature (`test_basics.py`, `test_search.py`, …) |
| `bot/` | the Discord bot's commands, buttons and loops |
| `fixtures/base.db` | an old database (real films and showtimes, fake accounts) every test starts from, so migrations are exercised too |
| `fixtures/scrapers/` | each venue's page or feed as it was served (trimmed to a few films, contact details removed), for `test_scraper_pages.py`. When a site changes, save a fresh copy here and update its test |
| `conftest.py` | per-test setup: a fresh database copy, a private uploads folder, cleared caches, module settings put back afterwards |
| `helpers.py` | `client(uid)` (signed-in test client), `H` (internal API header), `setup_db()`, `all_linked_present()`, `film_id()`, `patch_bot_api()`, `FakeInteraction`, `items_of()`, `seed_compare_pair()` |
| `fake_groq.py` | a stand-in for the AI provider (scripted replies, real error types) |
| `../frontend/tests/` | component tests (Vitest + React Testing Library): a component renders, gets clicked like a person would, and what's on screen is checked. `support.jsx` has `mockApi(routes)` (a fake server; returns the calls made), `reply(status, json)` and `renderPage(ui, {route, shell})` |

## Writing a test

Prefer small tests with plain `assert`s and a fixture for shared setup; see
`backend/test_basics.py` and `bot/test_bot_find_surprise.py`:

```python
from helpers import client, setup_db

def test_something(world):            # a fixture that seeds what you need
    r = client(world['member']).get('/api/...')
    assert r.status_code == 200
```

Every test starts from a fresh copy of `fixtures/base.db`, so tests never depend
on each other. Call `setup_db()` (or a fixture that does) before using the
database.

When later steps build on earlier ones, layer fixtures (`club` → `posted` →
…) rather than writing one long test; `backend/test_discord_sharing.py` and
`bot/test_bot_threads.py` show the pattern. Patch module settings and outside
calls with `monkeypatch` so nothing leaks into the next test.

## Writing a component test

New screens and changed ones get one alongside the backend test, in
`frontend/tests/<feature>.test.jsx` (see `saveSearch.test.jsx`):

```jsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderPage } from "./support";

test("saving a search", async () => {
  const calls = mockApi({ "GET /api/searches": [], "POST /api/searches": { search: { id: 9 } } });
  renderPage(<SaveSearch apiBase="" groupId={1} query={{ format: "35mm" }} />);
  await userEvent.click(await screen.findByRole("button", { name: "🔔 Alert me" }));
  expect(calls.at(-1).method).toBe("POST");
});
```

Find things the way a person would (role and name, visible text), not by CSS class.
