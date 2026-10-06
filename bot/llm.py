"""Tiny async LLM client for the @-mention chatbot.

Uses Groq (free tier, OpenAI-shaped API). This module is the ONLY place that
knows which provider/model we talk to — to switch models or providers later,
change it here and keep chat()'s signature the same.
"""

import os
import re

from groq import AsyncGroq, BadRequestError, NotFoundError, RateLimitError

# Groq rotates its hosted models occasionally (the llama-3.x pair this bot used
# was retired in 2026). Current options: https://console.groq.com/docs/models
#
# Primary is Qwen: fast, cheap per reply, stays in voice, and answers directly.
# FALLBACK is gpt-oss-120b, which has its own separate token budget. chat()
# retries on it when the primary is rate-limited (429) OR has been retired
# (model_not_found / model_decommissioned), so either failure self-heals instead
# of every reply hitting the '*snoozes*' catch-all. Both are overridable via env;
# set GROQ_FALLBACK_MODEL='' to disable the fallback.
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'qwen/qwen3.8-27b')
GROQ_FALLBACK_MODEL = os.environ.get('GROQ_FALLBACK_MODEL', 'openai/gpt-oss-120b')

# gpt-oss models spend hidden "reasoning" tokens before answering. At the bot's
# 150-token reply cap, default reasoning eats the whole budget and returns an
# empty reply, so they always run with low reasoning effort.
_LOW_REASONING_PREFIXES = ('openai/gpt-oss',)

# Error codes meaning "this model is gone", worth retrying on the fallback.
_MODEL_GONE_CODES = ('model_not_found', 'model_decommissioned')

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


def _model_gone(err):
    """True when Groq says the requested model doesn't exist / was retired."""
    return any(code in str(err) for code in _MODEL_GONE_CODES)


async def _complete(model, messages, max_tokens):
    extra = {}
    if model.startswith(_LOW_REASONING_PREFIXES):
        extra['extra_body'] = {'reasoning_effort': 'low'}
    resp = await _get_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        **extra,
    )
    return (resp.choices[0].message.content or '').strip()


async def chat(messages, max_tokens=300):
    """messages is an OpenAI-style list of {role, content} dicts (system first).
    Returns the reply text from GROQ_MODEL. If that model is rate-limited (429)
    or retired, transparently retries once on GROQ_FALLBACK_MODEL. Raises
    RateLimited only for a 429 with no distinct fallback, or when the fallback is
    also rate-limited; other API errors propagate raw so the caller can post a
    friendly fallback."""
    fb = GROQ_FALLBACK_MODEL
    has_fallback = bool(fb) and fb != GROQ_MODEL
    try:
        return await _complete(GROQ_MODEL, messages, max_tokens)
    except RateLimitError as e:
        if not has_fallback:
            raise RateLimited(_retry_after_from(e), str(e)) from e
        # Primary's daily budget is spent — retry on the fallback model, which
        # has its own. (Visible in logs thanks to PYTHONUNBUFFERED.)
        print(f'llm: {GROQ_MODEL} rate-limited, falling back to {fb}')
    except (NotFoundError, BadRequestError) as e:
        if not (has_fallback and _model_gone(e)):
            raise
        # Loud on purpose: the primary needs replacing (update GROQ_MODEL).
        print(f'llm: {GROQ_MODEL} is unavailable ({e}); falling back to {fb}. '
              f'Pick a current model: https://console.groq.com/docs/models')
    try:
        return await _complete(fb, messages, max_tokens)
    except RateLimitError as e2:
        raise RateLimited(_retry_after_from(e2), str(e2)) from e2
