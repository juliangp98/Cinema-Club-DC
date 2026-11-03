"""The bot's backend client (bot/api.py): autocompletes answer from a cache
within Discord's 3 seconds, a dropped connection is retried once, and DM
club lookups don't remember a failure."""
import asyncio
import time

import aiohttp
import pytest

import api as api_module


def run(coro):
    return asyncio.run(coro)


class Backend:
    """Stands in for _call: counts calls, answers after `delay` seconds."""
    def __init__(self, delay=0.0):
        self.calls, self.delay, self.answer = 0, delay, 1

    async def __call__(self, method, path, timeout=None, **kw):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return {'n': self.answer}


@pytest.fixture
def client(monkeypatch):
    c = api_module.InternalApi()
    c.backend = Backend()
    monkeypatch.setattr(c, '_call', c.backend)
    return c


def quick_get(c, path='/api/internal/theatres', **params):
    async def go():
        token = api_module.quick.set(True)
        try:
            return await c.get(path, **params)
        finally:
            api_module.quick.reset(token)
    return go()


def test_autocompletes_answer_from_a_cache(client):
    async def go():
        first = await quick_get(client, group_id=1)
        again = await quick_get(client, group_id=1)
        other = await quick_get(client, group_id=2)
        return first, again, other
    first, again, other = run(go())
    assert first == again == {'n': 1} and other == {'n': 1} and client.backend.calls == 2    # one per question


def test_an_older_answer_comes_at_once_and_is_refreshed_behind_the_scenes(client):
    async def go():
        await quick_get(client)
        key = next(iter(client._cache))
        client._cache[key] = (time.monotonic() - api_module.QUICK_FRESH - 1, {'n': 'old'})
        client.backend.answer, client.backend.delay = 2, 0.05
        started = time.monotonic()
        got = await quick_get(client)
        waited = time.monotonic() - started
        await asyncio.sleep(0.1)                                      # the refresh lands
        return got, waited, await quick_get(client)
    got, waited, later = run(go())
    assert got == {'n': 'old'} and waited < 0.04 and later == {'n': 2}


def test_a_first_ever_answer_waits_only_so_long(client, monkeypatch):
    monkeypatch.setattr(api_module, 'QUICK_WAIT', 0.05)
    client.backend.delay = 0.2

    async def go():
        with pytest.raises(asyncio.TimeoutError):                     # the autocomplete shows nothing this time…
            await quick_get(client)
        await asyncio.sleep(0.25)
        return await quick_get(client)                                # …and has it ready for the next keystroke
    assert run(go()) == {'n': 1} and client.backend.calls == 1


def test_ordinary_calls_never_use_the_cache(client):
    async def go():
        await client.get('/api/internal/theatres')
        await client.get('/api/internal/theatres')
    run(go())
    assert client.backend.calls == 2


class FlakySession:
    """aiohttp's session.request: drops the connection the first `drops` times."""
    closed = False

    def __init__(self, drops=1):
        self.drops, self.calls = drops, []

    def request(self, method, path, **kw):
        session = self

        class Ctx:
            async def __aenter__(self):
                session.calls.append(method)
                if len(session.calls) <= session.drops:
                    raise aiohttp.ServerDisconnectedError()
                return Resp()

            async def __aexit__(self, *a):
                return False
        return Ctx()


class Resp:
    status = 200

    async def text(self):
        return '{"ok": true}'


def test_a_dropped_connection_is_retried_once_for_reads():
    c = api_module.InternalApi()
    c._session = FlakySession()
    assert run(c.get('/api/internal/servers')) == {'ok': True} and c._session.calls == ['GET', 'GET']
    c._session = FlakySession()
    with pytest.raises(aiohttp.ServerDisconnectedError):
        run(c.post('/api/internal/rsvp', {'x': 1}))                    # a write might have landed: not repeated
    assert c._session.calls == ['POST']
    c._session = FlakySession(drops=2)
    with pytest.raises(aiohttp.ServerDisconnectedError):
        run(c.get('/api/internal/servers'))                           # once, not forever
    assert len(c._session.calls) == 2


def test_a_failed_dm_club_lookup_isnt_remembered(monkeypatch):
    from helpers import patch_bot_api, setup_db
    setup_db()
    patch_bot_api()
    from features import servers

    async def down(path, **params):
        raise aiohttp.ClientConnectorError(None, OSError('down'))
    monkeypatch.setattr(servers.api, 'get', down)
    assert run(servers.dm_clubs(4242)) == [] and 4242 not in servers._dm_clubs
