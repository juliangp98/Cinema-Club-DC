"""The site's shared AI (R6a): one place that talks to the model provider, used
by the site (poll drafts, …) and by the bot's @-mention chatbot (through
/api/internal/ai/*). Moved here from bot/llm.py so every feature shares the
same model choice, fallbacks and rate-limit handling.

Uses Groq (free tier, OpenAI-shaped API); this is the only module that knows
the provider. Groq retires hosted models every few months — sometimes a whole
family at once — so models are chosen from Groq's live catalogue instead of
being hard-coded:

  * refresh() lists Groq's models (free, no tokens), keeps text-chat models and
    ranks them by MODEL_PREFERENCE. It runs in the background — when a server
    process starts with no choice made yet, and once a day — and immediately
    when a model turns out to be retired. A request never waits for it unless
    no model has ever been chosen (and none is pinned).
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

The choice is shared by every server process (configure(load_shared=…,
save_shared=…), a setting in the database): a process re-reads it every
SHARED_RELOAD_SEC, so a check or an /llm change in one reaches the others,
and only one process checks at a time (claim_check). Calls are thread-safe.
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
SHARED_RELOAD_SEC = 30        # how often a process re-reads the shared choice
BACKGROUND = True             # checks run on their own thread (tests run them inline)

# gpt-oss models spend hidden reasoning tokens before answering; at short reply
# caps, default reasoning returns an empty reply.
_LOW_REASONING_PREFIXES = ('openai/gpt-oss',)
_LOW_REASONING = {'extra_body': {'reasoning_effort': 'low'}}
_MODEL_GONE_CODES = ('model_not_found', 'model_decommissioned')

# A test prompt shaped like the chatbot's (persona + a casual ask), short reply
# cap: it exposes reasoning models that return nothing.
PROBE_MESSAGES = [
    {'role': 'system', 'content': "You're CinemaBot, a movie-obsessed member of a film club's Discord. "
                                  'Reply in one or two short, casual sentences.'},
    {'role': 'user', 'content': 'what should i see this weekend?'},
]

_client = None
_lock = threading.RLock()
_checking = threading.Lock()  # one background check at a time in this process
# checked_at / loaded_at: wall-clock seconds (shared between processes)
_state = {'primary': None, 'fallback': None, 'how': {}, 'available': [], 'checked_at': 0.0, 'loaded_at': 0.0}
_extras = {}      # per-model request settings learned while probing
_config = {'on_switch': None, 'load_overrides': None, 'load_shared': None, 'save_shared': None, 'claim_check': None,
           'in_context': None}


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
        # A slow Groq shouldn't outlast the bot's patience: 20 s a call, one retry.
        _client = Groq(timeout=20.0, max_retries=1)
    return _client


def configure(on_switch=None, load_overrides=None, load_shared=None, save_shared=None, claim_check=None,
              in_context=None):
    """on_switch(message): told whenever the model choice changes.
    load_overrides(): {'primary': str, 'fallback': str} saved by /llm.
    load_shared() / save_shared(dict): the choice every server process uses.
    claim_check(): True if this process may run the background check now.
    in_context(fn): fn wrapped to run on another thread (the app's context)."""
    for key, fn in (('on_switch', on_switch), ('load_overrides', load_overrides), ('load_shared', load_shared),
                    ('save_shared', save_shared), ('claim_check', claim_check), ('in_context', in_context)):
        if fn:
            _config[key] = fn


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
            _state['checked_at'] = time.time()
            if not _state['primary']:    # Groq unreachable on first run: trust the pins
                _use_pins(overrides)
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
        _state['checked_at'] = time.time()
        if primary:
            _state.update(primary=primary, fallback=fallback, how={'primary': how_p, 'fallback': how_f})
        new = (_state['primary'], _state['fallback'])
        print(f'ai: refresh ({reason}) → primary={new[0]} fallback={new[1]}')
        _save_shared()

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


def _use_pins(overrides=None):
    """No choice yet: the /llm override or env pin, if there is one."""
    o = overrides or _overrides()
    primary = o['primary'] or ENV_PRIMARY or None
    fallback = o['fallback'] or ENV_FALLBACK or None
    _state.update(primary=primary, fallback=None if fallback == 'none' else fallback,
                  how={'primary': 'pinned', 'fallback': 'pinned' if fallback else None})
    return primary


def _load_shared():
    """Adopt the choice another process (or this one, earlier) saved, if it's newer."""
    _state['loaded_at'] = time.time()
    try:
        got = (_config['load_shared'] or (lambda: None))()
    except Exception as e:
        print(f'ai: loading the shared choice failed: {e}')
        return
    if got and got.get('primary') and got.get('checked_at', 0) >= _state['checked_at']:
        _state.update(primary=got['primary'], fallback=got.get('fallback'), how=got.get('how') or {},
                      available=got.get('available') or [], checked_at=got['checked_at'])
        _extras.update(got.get('extras') or {})


def _save_shared():
    try:
        (_config['save_shared'] or (lambda s: None))({
            'primary': _state['primary'], 'fallback': _state['fallback'], 'how': _state['how'],
            'available': _state['available'], 'checked_at': _state['checked_at'], 'extras': dict(_extras)})
        _state['loaded_at'] = time.time()
    except Exception as e:
        print(f'ai: saving the shared choice failed: {e}')


def current():
    """The models to use now. Only waits on Groq when no model was ever chosen
    — not by this process, not by another, and none pinned; otherwise a missing
    or day-old choice is checked in the background."""
    if time.time() - _state['loaded_at'] > SHARED_RELOAD_SEC:
        _load_shared()
    if not _state['primary']:
        if _use_pins():
            check_soon('first use')
        else:
            with _lock:                  # a check already running (prepare) chooses for us: wait for it
                if not _state['primary']:
                    refresh('first use')
    elif time.time() - _state['checked_at'] > REFRESH_EVERY_SEC:
        check_soon('daily check')
    return status()


def check_soon(reason):
    """Re-check the models in the background — one process at a time
    (claim_check), one check at a time in this one."""
    if not _checking.acquire(blocking=False):
        return

    def run():
        try:
            claim = _config['claim_check']
            if claim is None or claim():
                refresh(reason)
        except Exception as e:
            print(f'ai: background check failed: {e}')
        finally:
            _checking.release()
    if BACKGROUND:
        wrap = _config['in_context'] or (lambda fn: fn)
        threading.Thread(target=wrap(run), name='ai-check', daemon=True).start()
    else:
        run()


def prepare():
    """A server process starting: adopt the shared choice, and check it in
    the background if there's none or it's a day old — so the first chat
    never waits."""
    _load_shared()
    if not _state['primary'] or time.time() - _state['checked_at'] > REFRESH_EVERY_SEC:
        if not _state['primary']:
            _use_pins()
        check_soon('first use' if not _state['checked_at'] else 'daily check')


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
    current()

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
