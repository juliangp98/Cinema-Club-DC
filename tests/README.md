# Tests

The whole site and bot, tested together: the real backend (Flask, on a copy of
an old database) and the real bot code (its calls go to the backend in-process,
so there's no server, no network and no Discord connection).

```bash
tests/run.sh                         # everything (~5 seconds)
tests/run.sh -k discord              # tests whose names match
tests/run.sh backend/test_search.py  # one file
tests/run.sh -x -s                   # stop at the first failure, show prints
```

`run.sh` builds its own environment (`tests/.venv`, from `requirements.txt`) the
first time.

## Layout

| | |
|---|---|
| `backend/` | the site's API, by feature (`test_basics.py`, `test_search.py`, …) |
| `bot/` | the Discord bot's commands, buttons and loops |
| `fixtures/base.db` | an old database (real films and showtimes, fake accounts) every test starts from, so migrations are exercised too |
| `conftest.py` | per-test setup: a fresh database copy, a private uploads folder, cleared caches, module settings put back afterwards |
| `helpers.py` | `client(uid)` (signed-in test client), `H` (internal API header), `setup_db()`, `all_linked_present()`, `film_id()`, `patch_bot_api()`, `FakeInteraction`, `items_of()`, `seed_compare_pair()` |
| `fake_groq.py` | a stand-in for the AI provider (scripted replies, real error types) |

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
