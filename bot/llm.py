"""Async LLM client for the @-mention chatbot, with self-healing model choice.

Uses Groq (free tier, OpenAI-shaped API); this is the only module that knows
the provider. Groq retires hosted models every few months — sometimes a whole
family at once, as with the Llama 3.x pair in 2026 — so the models are chosen
from Groq's live catalogue instead of being hard-coded:

  * refresh() lists Groq's models (free, no tokens), keeps text-chat models and
    ranks them by MODEL_PREFERENCE. It runs at bot startup, again once a day on
    the next chat, and immediately when a model turns out to be retired.
  * Primary and fallback come from different model families, so one retirement
    wave can't take out both.
  * A model is test-called with the bot's real prompt before it's adopted.
    Reasoning models that spend the whole reply budget "thinking" get reasoning
    turned down; anything that still returns nothing is skipped.
  * Precedence: an /llm override (persisted by the bot), then the GROQ_MODEL /
    GROQ_FALLBACK_MODEL env pins, then the ranking — each only while Groq still
    serves it. A fallback pinned to "none" disables the fallback.
  * on_switch (set by the bot) receives a message whenever the choice changes,
    so the owner hears about it.
"""

import asyncio
import os
import re
import time

from groq import AsyncGroq, BadRequestError, NotFoundError, RateLimitError

ENV_PRIMARY = os.environ.get('GROQ_MODEL', '').strip()
ENV_FALLBACK = os.environ.get('GROQ_FALLBACK_MODEL', '').strip()

# Model families in order of preference (regex on the model id). Models from an
# unknown future family rank after these, largest context window first.
MODEL_PREFERENCE = [
    ('qwen', r'qwen'),
    ('gpt-oss', r'gpt-oss-120b'),
    ('llama', r'llama'),
    ('gpt-oss', r'gpt-oss'),
    ('kimi', r'kimi'),
    ('deepseek', r'deepseek'),
    ('mistral', r'mistral|mixtral'),
    ('gemma', r'gemma'),
]
# Text-in/text-out models that aren't chat models (moderation, classifiers).
_NOT_CHAT = re.compile(r'guard|whisper|tts|orpheus|playai', re.I)
MIN_CONTEXT = 8192            # the system prompt alone is ~2k tokens
REFRESH_EVERY_SEC = 24 * 3600

# gpt-oss models spend hidden reasoning tokens before answering; at the bot's
# 150-token reply cap, default reasoning returns an empty reply.
_LOW_REASONING_PREFIXES = ('openai/gpt-oss',)
_LOW_REASONING = {'extra_body': {'reasoning_effort': 'low'}}
_MODEL_GONE_CODES = ('model_not_found', 'model_decommissioned')

_client = None
_lock = asyncio.Lock()
_state = {'primary': None, 'fallback': None, 'how': {}, 'available': [], 'checked_at': 0.0}
_overrides = {'primary': '', 'fallback': ''}
_extras = {}      # per-model request settings learned while probing
_config = {
    'probe_messages': [{'role': 'user', 'content': 'In one short sentence: what makes a movie great?'}],
    'on_switch': None,
}


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


def configure(probe_messages=None, on_switch=None):
    """probe_messages: the prompt candidates must answer (use the real system
    prompt — it's what exposes reasoning models that return nothing).
    on_switch: async callable(message) told whenever the model choice changes."""
    if probe_messages:
        _config['probe_messages'] = probe_messages
    if on_switch:
        _config['on_switch'] = on_switch


def set_overrides(primary=None, fallback=None):
    """Admin overrides from /llm ('' clears one, 'none' disables the fallback).
    Takes effect on the next refresh()."""
    if primary is not None:
        _overrides['primary'] = primary.strip()
    if fallback is not None:
        _overrides['fallback'] = fallback.strip()


def family(model_id):
    for name, rx in MODEL_PREFERENCE:
        if re.search(rx, model_id or '', re.I):
            return name
    return (model_id or '').split('/')[0]


def _usable(m):
    return (getattr(m, 'active', True) is not False
            and 'text' in (getattr(m, 'input_modalities', None) or ['text'])
            and 'text' in (getattr(m, 'output_modalities', None) or ['text'])
            and (getattr(m, 'context_window', 0) or 0) >= MIN_CONTEXT
            and not _NOT_CHAT.search(m.id))


def _rank(m):
    rank = next((i for i, (_, rx) in enumerate(MODEL_PREFERENCE) if re.search(rx, m.id, re.I)),
                len(MODEL_PREFERENCE))
    return rank, -(getattr(m, 'context_window', 0) or 0), m.id


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


async def _complete(model, messages, max_tokens, extra=None):
    if extra is None:
        extra = _extras.get(model, _LOW_REASONING if model.startswith(_LOW_REASONING_PREFIXES) else {})
    resp = await _get_client().chat.completions.create(
        model=model, max_tokens=max_tokens, messages=messages, **extra)
    return (resp.choices[0].message.content or '').strip()


async def _probe(model):
    """Adopt a model only if it actually answers the bot's prompt; if it returns
    nothing (all reasoning), retry once with reasoning turned down."""
    attempts = ([_LOW_REASONING] if model.startswith(_LOW_REASONING_PREFIXES)
                else [{}, _LOW_REASONING])
    for extra in attempts:
        try:
            text = await _complete(model, _config['probe_messages'], 150, extra)
        except Exception as e:
            print(f'llm: probe of {model} failed: {e}')
            return False
        if text:
            _extras[model] = extra
            return True
    print(f'llm: {model} returned no text — skipping it')
    return False


async def _choose(pins, ranked, available, notes, exclude=()):
    """First pinned model that's still served and answers, else the best-ranked."""
    for model, how in pins:
        if not model or model in exclude:
            continue
        if model not in available:
            notes.append(f'the {how} model `{model}` is no longer served by Groq')
            continue
        if await _probe(model):
            return model, how
        notes.append(f'the {how} model `{model}` gave no reply in a test call')
    for model in ranked:
        if model not in exclude and await _probe(model):
            return model, 'auto'
    return None, None


async def refresh(reason='scheduled'):
    """Re-select primary + fallback from Groq's current catalogue."""
    async with _lock:
        old = (_state['primary'], _state['fallback'])
        try:
            listing = await _get_client().models.list()
        except Exception as e:
            print(f'llm: listing Groq models failed: {e}')
            _state['checked_at'] = time.monotonic()
            if not _state['primary']:    # Groq unreachable on first run: trust the pins
                _state['primary'] = _overrides['primary'] or ENV_PRIMARY or None
                _state['fallback'] = _overrides['fallback'] or ENV_FALLBACK or None
            return status()

        available = [m.id for m in sorted(filter(_usable, listing.data), key=_rank)]
        notes = []
        primary, how_p = await _choose(
            [(_overrides['primary'], 'override'), (ENV_PRIMARY, 'env')], available, available, notes)
        fallback = how_f = None
        disabled = (_overrides['fallback'] or ENV_FALLBACK) == 'none'
        if primary and not disabled:
            other_family = [m for m in available if family(m) != family(primary)]
            same_family = [m for m in available if family(m) == family(primary)]
            fallback, how_f = await _choose(
                [(_overrides['fallback'], 'override'), (ENV_FALLBACK, 'env')],
                other_family + same_family, available, notes, exclude={primary})

        _state['available'] = available
        _state['checked_at'] = time.monotonic()
        if primary:
            _state.update(primary=primary, fallback=fallback,
                          how={'primary': how_p, 'fallback': how_f})
        new = (_state['primary'], _state['fallback'])
        print(f'llm: refresh ({reason}) → primary={new[0]} fallback={new[1]}')

        # Tell the owner when the choice changes, or at startup if a pin is stale.
        if (old[0] and new != old) or (not old[0] and notes):
            lines = [f'🤖 **Chatbot models** ({reason}): primary `{new[0]}`, fallback `{new[1]}`']
            if old[0] and new != old:
                lines.append(f'Previously: primary `{old[0]}`, fallback `{old[1]}`.')
            lines += [f'• Note: {n}.' for n in notes]
            if notes:
                lines.append('Use `/llm` to pick models, or update the env pins.')
            if _config['on_switch']:
                try:
                    await _config['on_switch']('\n'.join(lines))
                except Exception as e:
                    print(f'llm: on_switch notify failed: {e}')
        return status()


def status():
    return {
        'primary': _state['primary'],
        'fallback': _state['fallback'],
        'how': dict(_state['how']),
        'available': list(_state['available']),
        'overrides': dict(_overrides),
        'env': {'primary': ENV_PRIMARY, 'fallback': ENV_FALLBACK},
    }


async def chat(messages, max_tokens=300):
    """messages is an OpenAI-style list of {role, content} dicts (system first).
    Uses the primary model; on a 429 or a retired model it moves to the fallback
    (re-selecting models first when one was retired). Raises RateLimited when
    every model tried is rate-limited; other API errors propagate so the caller
    can post its friendly fallback line."""
    if not _state['primary'] or time.monotonic() - _state['checked_at'] > REFRESH_EVERY_SEC:
        await refresh('daily check' if _state['primary'] else 'first use')

    tried, rate_limited = set(), None
    for _ in range(3):
        model = next((m for m in (_state['primary'], _state['fallback']) if m and m not in tried), None)
        if model is None:
            break
        tried.add(model)
        try:
            return await _complete(model, messages, max_tokens)
        except RateLimitError as e:
            rate_limited = e
            print(f'llm: {model} is rate-limited; trying the fallback')
        except (NotFoundError, BadRequestError) as e:
            if not _model_gone(e):
                raise
            print(f'llm: {model} is no longer served; re-selecting models')
            await refresh(f'`{model}` was retired')
    if rate_limited:
        raise RateLimited(_retry_after_from(rate_limited), str(rate_limited)) from rate_limited
    raise RuntimeError('no Groq chat model is available')
