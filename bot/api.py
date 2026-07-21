"""Thin async client for the backend's /api/internal/* endpoints."""

import os

import aiohttp

BOT_API_BASE = os.environ.get('BOT_API_BASE', 'http://backend:5001')
INTERNAL_API_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f'API {status}: {body}')
        self.status = status
        self.body = body


class InternalApi:
    def __init__(self):
        self._session = None

    async def _ensure(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=BOT_API_BASE,
                headers={'X-Internal-Token': INTERNAL_API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def get(self, path, **params):
        session = await self._ensure()
        clean = {k: v for k, v in params.items() if v is not None}
        async with session.get(path, params=clean) as r:
            if r.status >= 400:
                raise ApiError(r.status, await r.text())
            return await r.json()

    async def post(self, path, payload=None):
        session = await self._ensure()
        async with session.post(path, json=payload or {}) as r:
            if r.status >= 400:
                raise ApiError(r.status, await r.text())
            return await r.json()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
