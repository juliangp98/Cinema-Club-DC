"""✨ Ask on the Help page (7f): a question in your own words, answered from
the Help guide only. help.json is the one copy of the guide (the site's
frontend/src/help.json; the backend image has its own copy, see
Dockerfile.backend).

  1. keyword retrieval picks the topics most likely to answer it (TOP_N);
  2. the shared AI sees every topic's question but only those answers in
     full, plus the places a link may go — and replies with the topics that
     answer it and, when it helps, a short answer in the guide's own link
     syntax ([words](place-id) or [words](help:topic-id));
  3. links to anything not in the guide are dropped to plain words.

Answers are cached by question, so a common one costs one call. With no AI
(down, rate-limited, a bad reply) it's the retrieval's best topics."""
import json
import os
import re
import time
from pathlib import Path

TOP_N = 8
CACHE_SECONDS = 24 * 3600
MAX_ANSWER = 700
LINK = re.compile(r'\[([^\]]+)\]\(([a-z0-9-]+(?::[a-z0-9-]+)?)\)')
_cache = {}
_guide = None


def _path():
    here = Path(__file__).resolve().parent
    for p in (os.environ.get('HELP_JSON'), here / 'help.json', here.parent / 'frontend' / 'src' / 'help.json'):
        if p and Path(p).exists():
            return Path(p)
    raise FileNotFoundError('help.json not found')


def guide():
    """{'places': {...}, 'sections': [...], 'topics': {id: item+section}} — read once."""
    global _guide
    if _guide is None:
        g = json.loads(_path().read_text())
        g['topics'] = {i['id']: {**i, 'section': s['title']} for s in g['sections'] for i in s['items']}
        _guide = g
    return _guide


def plain(text):
    return LINK.sub(r'\1', text or '')


def _stem(w):
    for end in ('ing', 'ed', 'es', 's'):
        if len(w) > len(end) + 3 and w.endswith(end):
            return w[:-len(end)]
    return w


def words(text):
    stop = set(guide()['stopwords'])
    return [_stem(w) for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) > 2 and w not in stop]


def retrieve(q, n=TOP_N):
    """Topic ids by keyword overlap: the question counts most, then the
    section's title, then the answer."""
    ws = set(words(q))
    if not ws:
        return []
    scored = []
    for tid, t in guide()['topics'].items():
        score = (3 * len(ws & set(words(t['q']))) + 2 * len(ws & set(words(t['section'])))
                 + len(ws & set(words(plain(t['a'])))))
        if score:
            scored.append((score, tid))
    return [tid for _, tid in sorted(scored, key=lambda x: -x[0])[:n]]


def clean_links(text):
    """Keep links to real places and topics; anything else becomes plain words."""
    g = guide()

    def keep(m):
        ref = m.group(2)
        ok = ref[5:] in g['topics'] if ref.startswith('help:') else ref in g['places']
        return m.group(0) if ok else m.group(1)
    return LINK.sub(keep, text or '')


def _cities():
    """The cities the site covers, as words ("Washington, DC")."""
    from flask import has_app_context
    import cities
    import places
    names = [c.name for c in (places.active_cities() if has_app_context() else cities.CITIES)]
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def _prompt(q, ids):
    from app import SITE_NAME
    g = guide()
    catalog = '\n'.join(f"- {tid}: {t['q']}" for tid, t in g['topics'].items())
    full = '\n\n'.join(f"[{tid}] {g['topics'][tid]['q']}\n{g['topics'][tid]['a']}" for tid in ids)
    places = '\n'.join(f"- {pid}: {p['label']}" for pid, p in g['places'].items())
    system = (
        f"You answer questions about the {SITE_NAME} website (a calendar of repertory screenings in "
        f"{_cities()}, with "
        "clubs, polls, games and kernels) using ONLY its Help guide below. Never invent features, settings or "
        "places; if the guide doesn't say, say you're not sure and point to the closest topic.\n"
        'Reply with JSON only: {"topics": [up to 3 topic ids that answer it, best first], "answer": "..."}.\n'
        "answer: at most 70 words, friendly and plain, in the guide's words. Link places exactly like the guide "
        "does — [words](place-id) with a place id from PLACES, or [words](help:topic-id) — and never any other "
        'URL. Leave answer "" when one topic answers it exactly as asked.\n\n'
        f"ALL TOPICS (id: question):\n{catalog}\n\nTHE LIKELIEST TOPICS IN FULL:\n{full}\n\nPLACES (id: what it is):\n{places}")
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': q[:300]}]


def cached(q, now=None):
    """The answer already given to this question (in other words or not), or None."""
    hit = _cache.get(' '.join(words(q)))
    if hit and (now or time.time()) - hit[0] < CACHE_SECONDS:
        return {**hit[1], 'cached': True}
    return None


def ask(q, now=None):
    """{'ai': bool, 'topics': [ids], 'answer': str|None, 'cached': bool}."""
    import ai
    now = now or time.time()
    key = ' '.join(words(q))
    if hit := cached(q, now):
        return hit
    ids = retrieve(q)
    fallback = {'ai': False, 'topics': ids[:3], 'answer': None, 'cached': False}
    try:
        raw = ai.chat(_prompt(q, ids), max_tokens=350, json_mode=True)
        data = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or '').strip()))
    except (ai.RateLimited, ai.Unavailable):
        return fallback
    except Exception as e:                      # a reply that isn't the JSON asked for
        print(f'help_ai: bad reply for {q!r}: {e}')
        return fallback
    topics = [t for t in (data.get('topics') or []) if isinstance(t, str) and t in guide()['topics']][:3]
    answer = clean_links(str(data.get('answer') or '').strip())[:MAX_ANSWER] or None
    result = {'ai': True, 'topics': topics or ids[:3], 'answer': answer}
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (now, result)
    return {**result, 'cached': False}
