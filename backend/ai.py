"""The site's shared AI (R6a): one place that talks to the model provider, used
by the site (poll drafts, …) and by the bot's @-mention chatbot (through
/api/internal/ai/*). Moved here from bot/llm.py so every feature shares the
same model choice, fallbacks and rate-limit handling.

Uses Groq (free tier, OpenAI-shaped API); this is the only module that knows
the provider. Groq retires hosted models every few months — sometimes a whole
family at once — so models are chosen from Groq's live catalogue instead of
being hard-coded:

  * refresh() lists Groq's models (free, no tokens), keeps text-chat models and
    ranks them by MODEL_PREFERENCE. It runs on first use, again once a day,
    and immediately when a model turns out to be retired.
  * Primary and fallback come from different model families, so one retirement
    wave can't take out both.
  * A model is test-called before it's adopted. Reasoning models that spend
    the whole reply budget "thinking" get reasoning turned down; anything that
    still returns nothing is skipped.
  * Precedence: an /llm override (saved as a setting), then the GROQ_MODEL /
    GROQ_FALLBACK_MODEL env pins, then the ranking — each only while Groq
    still serves it. A fallback pinned to "none" disables the fallback.
  * configure(on_switch=…) is told whenever the choice changes, so the owner
    hears about it.

Each server process keeps its own choice (they agree: same catalogue, same
ranking); calls are thread-safe.
"""

import os
import re
import threading
import time

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
MIN_CONTEXT = 8192            # the chatbot's system prompt alone is ~2k tokens
REFRESH_EVERY_SEC = 24 * 3600

# gpt-oss models spend hidden reasoning tokens before answering; at short reply
# caps, default reasoning returns an empty reply.
_LOW_REASONING_PREFIXES = ('openai/gpt-oss',)
_LOW_REASONING = {'extra_body': {'reasoning_effort': 'low'}}
_MODEL_GONE_CODES = ('model_not_found', 'model_decommissioned')

# A test prompt shaped like the chatbot's (persona + a casual ask), short reply
# cap: it exposes reasoning models that return nothing.
PROBE_MESSAGES = [
    {'role': 'system', 'content': "You're CinemaBot, a movie-obsessed member of a DC film club's Discord. "
                                  'Reply in one or two short, casual sentences.'},
    {'role': 'user', 'content': 'what should i see this weekend?'},
]

_client = None
_lock = threading.RLock()
_state = {'primary': None, 'fallback': None, 'how': {}, 'available': [], 'checked_at': 0.0}
_extras = {}      # per-model request settings learned while probing
_config = {'on_switch': None, 'load_overrides': None}


class RateLimited(Exception):
    """Groq returned 429 — the free tier's per-day (or per-minute) token cap is
    spent. Carries retry_after_sec (best-effort) so callers can say when it'll
    be back instead of a generic error."""
    def __init__(self, retry_after_sec=None, message=''):
        super().__init__(message or 'rate limited')
        self.retry_after_sec = retry_after_sec


class Unavailable(Exception):
    """No model could answer (no API key, Groq down, nothing usable)."""


def _get_client():
    global _client
    if _client is None:
        from groq import Groq
        if not os.environ.get('GROQ_API_KEY'):
            raise Unavailable('GROQ_API_KEY is not set')
        _client = Groq()
    return _client


def configure(on_switch=None, load_overrides=None):
    """on_switch(message): told whenever the model choice changes.
    load_overrides(): {'primary': str, 'fallback': str} saved by /llm."""
    if on_switch:
        _config['on_switch'] = on_switch
    if load_overrides:
        _config['load_overrides'] = load_overrides


def _overrides():
    try:
        o = (_config['load_overrides'] or (lambda: {}))() or {}
    except Exception as e:
        print(f'ai: loading overrides failed: {e}')
        o = {}
    return {'primary': (o.get('primary') or '').strip(), 'fallback': (o.get('fallback') or '').strip()}


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
    """Seconds to wait from a Groq 429: the Retry-After header, else the
    '...try again in 11m12.192s' hint in the message."""
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
    return any(code in str(err) for code in _MODEL_GONE_CODES)


def _complete(model, messages, max_tokens, extra=None, json_mode=False):
    if extra is None:
        extra = _extras.get(model, _LOW_REASONING if model.startswith(_LOW_REASONING_PREFIXES) else {})
    kwargs = dict(extra)
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    resp = _get_client().chat.completions.create(model=model, max_tokens=max_tokens, messages=messages, **kwargs)
    return (resp.choices[0].message.content or '').strip()


def _probe(model):
    """Adopt a model only if it actually answers; if it returns nothing (all
    reasoning), retry once with reasoning turned down."""
    attempts = [_LOW_REASONING] if model.startswith(_LOW_REASONING_PREFIXES) else [{}, _LOW_REASONING]
    for extra in attempts:
        try:
            text = _complete(model, PROBE_MESSAGES, 150, extra)
        except Exception as e:
            print(f'ai: probe of {model} failed: {e}')
            return False
        if text:
            _extras[model] = extra
            return True
    print(f'ai: {model} returned no text — skipping it')
    return False


def _choose(pins, ranked, available, notes, exclude=()):
    """First pinned model that's still served and answers, else the best-ranked."""
    for model, how in pins:
        if not model or model in exclude:
            continue
        if model not in available:
            notes.append(f'the {how} model `{model}` is no longer served by Groq')
            continue
        if _probe(model):
            return model, how
        notes.append(f'the {how} model `{model}` gave no reply in a test call')
    for model in ranked:
        if model not in exclude and _probe(model):
            return model, 'auto'
    return None, None


def refresh(reason='scheduled'):
    """Re-select primary + fallback from Groq's current catalogue."""
    with _lock:
        old = (_state['primary'], _state['fallback'])
        overrides = _overrides()
        try:
            listing = _get_client().models.list()
        except Exception as e:
            print(f'ai: listing Groq models failed: {e}')
            _state['checked_at'] = time.monotonic()
            if not _state['primary']:    # Groq unreachable on first run: trust the pins
                _state['primary'] = overrides['primary'] or ENV_PRIMARY or None
                _state['fallback'] = overrides['fallback'] or ENV_FALLBACK or None
            return status()

        available = [m.id for m in sorted(filter(_usable, listing.data), key=_rank)]
        notes = []
        primary, how_p = _choose([(overrides['primary'], 'override'), (ENV_PRIMARY, 'env')], available, available, notes)
        fallback = how_f = None
        disabled = (overrides['fallback'] or ENV_FALLBACK) == 'none'
        if primary and not disabled:
            other_family = [m for m in available if family(m) != family(primary)]
            same_family = [m for m in available if family(m) == family(primary)]
            fallback, how_f = _choose([(overrides['fallback'], 'override'), (ENV_FALLBACK, 'env')],
                                      other_family + same_family, available, notes, exclude={primary})

        _state['available'] = available
        _state['checked_at'] = time.monotonic()
        if primary:
            _state.update(primary=primary, fallback=fallback, how={'primary': how_p, 'fallback': how_f})
        new = (_state['primary'], _state['fallback'])
        print(f'ai: refresh ({reason}) → primary={new[0]} fallback={new[1]}')

        if _config['on_switch'] and (new != old or notes):
            lines = [f'🤖 **AI models** ({reason}): primary `{new[0]}`, fallback `{new[1]}`']
            lines += [f'• Note: {n}.' for n in notes]
            if notes:
                lines.append('Use `/llm` to pick models, or update the env pins.')
            try:
                _config['on_switch'](new, '\n'.join(lines))
            except Exception as e:
                print(f'ai: on_switch notify failed: {e}')
        return status()


def status():
    return {
        'primary': _state['primary'],
        'fallback': _state['fallback'],
        'how': dict(_state['how']),
        'available': list(_state['available']),
        'overrides': _overrides(),
        'env': {'primary': ENV_PRIMARY, 'fallback': ENV_FALLBACK},
    }


def chat(messages, max_tokens=300, json_mode=False):
    """messages: OpenAI-style [{role, content}] (system first). Uses the primary
    model; on a 429 or a retired model it moves to the fallback (re-selecting
    first when one was retired). Raises RateLimited when every model tried is
    rate-limited, Unavailable when none can answer."""
    from groq import BadRequestError, NotFoundError, RateLimitError
    if not _state['primary'] or time.monotonic() - _state['checked_at'] > REFRESH_EVERY_SEC:
        refresh('daily check' if _state['primary'] else 'first use')

    tried, rate_limited = set(), None
    for _ in range(3):
        model = next((m for m in (_state['primary'], _state['fallback']) if m and m not in tried), None)
        if model is None:
            break
        tried.add(model)
        try:
            return _complete(model, messages, max_tokens, json_mode=json_mode)
        except RateLimitError as e:
            rate_limited = e
            print(f'ai: {model} is rate-limited; trying the fallback')
        except (NotFoundError, BadRequestError) as e:
            if json_mode and not _model_gone(e):
                # Some models reject JSON mode: one plain retry on the same model.
                try:
                    return _complete(model, messages, max_tokens)
                except Exception:
                    pass
            if not _model_gone(e):
                raise
            print(f'ai: {model} is no longer served; re-selecting models')
            refresh(f'`{model}` was retired')
    if rate_limited:
        raise RateLimited(_retry_after_from(rate_limited), str(rate_limited)) from rate_limited
    raise Unavailable('no Groq chat model is available')
