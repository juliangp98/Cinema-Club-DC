"""The bot's door to the site's shared AI (R6a).

The model choice, fallbacks and rate-limit handling live in the backend
(backend/ai.py) so the site and the bot share one AI; this module keeps the
interface the bot already used — chat(), RateLimited, status(), refresh() — and
calls /api/internal/ai/*. /llm overrides are saved as backend settings (as
before), and model changes still reach the owner by DM (via the announce loop).
"""

import json

from api import ApiError

_api = None


class RateLimited(Exception):
    """The free tier's token cap is spent; retry_after_sec says (roughly) when
    it'll be back, so the bot can say so instead of a generic error."""
    def __init__(self, retry_after_sec=None, message=''):
        super().__init__(message or 'rate limited')
        self.retry_after_sec = retry_after_sec


def configure(api):
    global _api
    _api = api


async def chat(messages, max_tokens=300):
    """messages: OpenAI-style [{role, content}] (system first) → reply text."""
    try:
        r = await _api.post('/api/internal/ai/chat', {'messages': messages, 'max_tokens': max_tokens})
    except ApiError as e:
        if e.status == 429:
            try:
                retry = json.loads(e.body or '{}').get('retry_after')
            except ValueError:
                retry = None
            raise RateLimited(retry, e.body) from e
        raise
    return r.get('text') or ''


async def status():
    return await _api.get('/api/internal/ai/status')


async def refresh(reason='requested'):
    return await _api.post('/api/internal/ai/refresh', {'reason': reason})
