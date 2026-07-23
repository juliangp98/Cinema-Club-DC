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
# Primary is 70b-versatile for its nicer voice, but its free-tier daily token
# budget (100K TPD) is small and the chat kept exhausting it. FALLBACK is the 8b
# model, which has its own much larger daily budget: chat() automatically retries
# on it when the primary is rate-limited (429), so a spent primary self-heals
# instead of failing. Both are overridable via env; set GROQ_FALLBACK_MODEL='' to
# disable the fallback and surface the rate-limit to users instead.
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
GROQ_FALLBACK_MODEL = os.environ.get('GROQ_FALLBACK_MODEL', 'llama-3.1-8b-instant')

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


async def _complete(model, messages, max_tokens):
    resp = await _get_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
    )
    return (resp.choices[0].message.content or '').strip()


async def chat(messages, max_tokens=300):
    """messages is an OpenAI-style list of {role, content} dicts (system first).
    Returns the reply text from GROQ_MODEL. If that model is rate-limited (429),
    transparently retries once on GROQ_FALLBACK_MODEL (which has its own separate
    token budget). Raises RateLimited only if there's no distinct fallback or the
    fallback is also rate-limited; other API errors propagate raw so the caller
    can post a friendly fallback."""
    try:
        return await _complete(GROQ_MODEL, messages, max_tokens)
    except RateLimitError as e:
        fb = GROQ_FALLBACK_MODEL
        if not fb or fb == GROQ_MODEL:
            raise RateLimited(_retry_after_from(e), str(e)) from e
        # Primary's daily budget is spent — retry on the fallback model, which
        # has its own. (Visible in logs thanks to PYTHONUNBUFFERED.)
        print(f'llm: {GROQ_MODEL} rate-limited, falling back to {fb}')
        try:
            return await _complete(fb, messages, max_tokens)
        except RateLimitError as e2:
            raise RateLimited(_retry_after_from(e2), str(e2)) from e2
