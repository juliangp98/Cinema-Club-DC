"""Thin async client for the backend's /api/internal/* endpoints.

Discord gives the bot 3 seconds to answer an autocomplete (and it can't ask
for more), so while one is running (`quick`, set by the command tree's check)
GETs come from a short-lived cache: a fresh answer as it is, an older one
straight away while it's refreshed in the background, and only a first-ever
lookup waits — at most QUICK_WAIT. A dropped connection is retried once, and
slow calls are logged with how long they took.
"""

import asyncio
import contextvars
import json
import os
import time

import aiohttp

BOT_API_BASE = os.environ.get('BOT_API_BASE', 'http://backend:5001')
INTERNAL_API_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')

TIMEOUT = 20              # seconds for a call (the AI chat asks for more)
# Idle connections are dropped before the backend drops them (gunicorn
# --keep-alive 30, entrypoint.sh), so a reused one is never already closed.
KEEPALIVE = 15
SLOW = 2.0                # calls slower than this are logged
QUICK_WAIT = 2.0          # an autocomplete waits at most this long for a first-ever answer
QUICK_FRESH = 60          # cached answers younger than this are used as they are…
QUICK_KEEP = 30 * 60      # …older ones (up to this) straight away, refreshed behind the scenes
QUICK_MAX = 500           # cached answers kept

# Set while an autocomplete runs (servers.interaction_check).
quick = contextvars.ContextVar('api_quick', default=False)


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f'API {status}: {body}')
        self.status = status
        self.body = body


class InternalApi:
    def __init__(self):
        self._session = None
        self._cache = {}          # (path, params) → (when, answer)
        self._pending = {}        # (path, params) → the task refreshing it

    async def _ensure(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=BOT_API_BASE,
                headers={'X-Internal-Token': INTERNAL_API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                connector=aiohttp.TCPConnector(keepalive_timeout=KEEPALIVE),
            )
        return self._session

    async def _call(self, method, path, timeout=None, **kw):
        """One request, retried once if the connection dropped (GETs always;
        anything when it never got through)."""
        session = await self._ensure()
        started = time.monotonic()
        for attempt in (1, 2):
            try:
                async with session.request(method, path, timeout=aiohttp.ClientTimeout(total=timeout or TIMEOUT), **kw) as r:
                    body = await r.text()
                    status = r.status
                break
            except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, aiohttp.ClientOSError) as e:
                sent = not isinstance(e, aiohttp.ClientConnectorError)
                if attempt == 2 or (sent and method != 'GET'):
                    print(f'api: {method} {path} failed after {time.monotonic() - started:.1f}s: {e!r}')
                    raise
                print(f'api: {method} {path}: {type(e).__name__}, retrying')
            except asyncio.TimeoutError:
                print(f'api: {method} {path} timed out after {time.monotonic() - started:.1f}s')
                raise
        took = time.monotonic() - started
        if took > SLOW:
            print(f'api: {method} {path} took {took:.1f}s')
        if status >= 400:
            raise ApiError(status, body)
        return json.loads(body) if body else None

    async def get(self, path, **params):
        clean = {k: v for k, v in params.items() if v is not None}
        if quick.get():
            return await self._quick_get(path, clean)
        return await self._call('GET', path, params=clean)

    async def _quick_get(self, path, params):
        key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
        hit = self._cache.get(key)
        age = time.monotonic() - hit[0] if hit else None
        if hit and age < QUICK_FRESH:
            return hit[1]
        task = self._pending.get(key)
        if task is None:
            task = self._pending[key] = asyncio.create_task(self._fill(key, path, params))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())   # a failed refresh is only logged
        if hit and age < QUICK_KEEP:
            return hit[1]
        return await asyncio.wait_for(asyncio.shield(task), QUICK_WAIT)

    async def _fill(self, key, path, params):
        try:
            data = await self._call('GET', path, params=params)
            if len(self._cache) >= QUICK_MAX:
                for old in sorted(self._cache, key=lambda k: self._cache[k][0])[:QUICK_MAX // 5]:
                    del self._cache[old]
            self._cache[key] = (time.monotonic(), data)
            return data
        finally:
            self._pending.pop(key, None)

    async def _send(self, method, path, payload=None, timeout=None):
        return await self._call(method, path, timeout=timeout, json=payload or {})

    async def post(self, path, payload=None, timeout=None):
        return await self._send('POST', path, payload, timeout=timeout)

    async def put(self, path, payload=None):
        return await self._send('PUT', path, payload)

    async def delete(self, path, payload=None):
        return await self._send('DELETE', path, payload)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
