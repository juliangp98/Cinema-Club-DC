"""Tiny async LLM client for the @-mention chatbot.

Uses Groq (free tier, OpenAI-shaped API). This module is the ONLY place that
knows which provider/model we talk to — to switch models or providers later,
change it here and keep chat()'s signature the same.
"""

import os
import re

from groq import AsyncGroq, RateLimitError

# Groq rotates its hosted models occasionally — if calls start 400ing with a
# "model_decommissioned" error, pick a current one from https://console.groq.com/docs/models
#
# Default is the 8b model: the free tier gives it a much larger per-day token
# budget than llama-3.3-70b-versatile (100K TPD), which the chat kept exhausting.
# To trade headroom back for a wittier model, set GROQ_MODEL=llama-3.3-70b-versatile
# in the env — no code change needed.
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

_client = None


class RateLimited(Exception):
    """Groq returned 429 — the free tier's per-day (or per-minute) token cap is
    spent. Carries retry_after_sec (best-effort) so the bot can tell people when
    it'll be back instead of posting a generic error."""
    def __init__(self, retry_after_sec=None, message=''):
        super().__init__(message or 'rate limited')
        self.retry_after_sec = retry_after_sec


def _get_client():
    global _client
    if _client is None:
        _client = AsyncGroq()  # reads GROQ_API_KEY from the environment
    return _client


def _retry_after_from(err):
    """Pull a seconds-to-wait out of a Groq 429 — prefer the Retry-After header,
    fall back to parsing the '...try again in 11m12.192s' hint in the message."""
    try:
        ra = err.response.headers.get('retry-after')
        if ra:
            return float(ra)
    except Exception:
        pass
    m = re.search(r'try again in (?:(\d+)m)?([\d.]+)s', str(err))
    if m:
        return (int(m.group(1) or 0) * 60) + float(m.group(2))
    return None


async def chat(messages, max_tokens=300):
    """messages is an OpenAI-style list of {role, content} dicts (system first).
    Returns the reply text. Raises RateLimited on a 429, or the raw error
    otherwise, so the caller can post a friendly fallback."""
    try:
        resp = await _get_client().chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=max_tokens,
            messages=messages,
        )
    except RateLimitError as e:
        raise RateLimited(_retry_after_from(e), str(e)) from e
    return (resp.choices[0].message.content or '').strip()
