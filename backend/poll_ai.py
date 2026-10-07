"""Poll drafts from a plain-English ask (R6a): "spookiest Halloween movies",
"the 99th Oscar winners". The shared AI (ai.py) drafts a title, categories and
options; organizers edit the draft before it becomes a poll.

The organizer says what it's based on (`scope`):
  * "playing": local showings — options come from films playing at the club's
    theatres (the Discover engine puts the ones that fit the ask first).
  * "all": films in general — the AI's own knowledge, not tied to what's on.
Either way, options that name a film in our database are linked to it
(poster, year, film page). For awards that haven't been announced yet, the AI
drafts likely contenders and says so in `notes`.
"""

import json
import re
from datetime import datetime, timedelta

MAX_CATEGORIES = 25
MAX_OPTIONS = 15
MAX_FILMS = 80          # playing films offered to the AI (keeps the prompt small)
WINDOW_DAYS = 45

SCOPES = ('playing', 'all')

SYSTEM = """You draft polls for a film club's website (Washington, DC). Reply with ONE JSON object and nothing else:
{"title": str, "description": str, "poll_type": "standard" | "prediction", "scoring_mode": "none" | "single" | "ranked" | "confidence",
 "categories": [{"title": str, "options": [str, ...]}], "notes": str}

Rules:
- "standard" polls are opinions (favorites, what to watch): scoring_mode "none" for plain votes, "ranked" for top-3 style.
- "prediction" polls have right answers decided later (awards, box office): scoring_mode "single" (or "confidence"/"ranked" if asked).
- 1 to 25 categories; 2 to 12 options each (award categories: the nominees). Short titles; options are film titles or names.
- {scope_rule}
- For awards: use the real nominees if they are known to you. If nominations aren't announced yet, use likely contenders
  and say in "notes" that they're predicted and should be updated when nominations come out.
- Never invent showtimes. "notes" is one short sentence for the organizer (or "").
"""


class DraftError(Exception):
    """Couldn't produce a usable draft (the message is safe to show)."""


def _norm(text):
    import discover
    t = discover.normalize(text or '')
    t = re.sub(r'\s*\((19|20)\d\d\)\s*$', '', t)            # "Title (1999)"
    t = re.sub(r'^the\s+', '', t)
    return re.sub(r'[^a-z0-9]+', ' ', t).strip()


def playing_films(group, prompt, now=None):
    """[(Film, line)] for the prompt: films that fit the ask first (Discover's
    own reading of it), then the club's most wanted and rarest."""
    import discover
    now = now or datetime.now()
    start, end = now, now + timedelta(days=WINDOW_DAYS)
    films = discover.catalog(group, start, end)
    if not films:
        return []
    genres = {g for f in films.values() for g in f.genres}
    asked = {k: v for k, v in discover.parse_request(prompt, genres).items() if k in ('shelf', 'mood', 'genres', 'decade')}
    first = []
    if asked:
        try:
            first, *_ = discover.select(group, None, {**asked, 'from': start.date().isoformat(),
                                                      'to': end.date().isoformat()}, now)
        except Exception:
            first = []
    seen, ordered = set(), []
    rest = sorted(films.values(), key=lambda f: (-f.wanted, -f.rare_score, f.next.start_time))
    for f in [*first, *rest]:
        if f.movie.id not in seen:
            seen.add(f.movie.id)
            ordered.append(f)
    out = []
    for f in ordered[:MAX_FILMS]:
        bits = [f"{f.movie.title}" + (f" ({f.year})" if f.year else '')]
        if f.genres:
            bits.append(', '.join(sorted(f.genres)[:3]))
        if f.rare_score >= 4:
            bits.append('rare screening')
        out.append((f, ' — '.join(bits)))
    return out


def _parse(raw):
    text = (raw or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    raise DraftError("The AI's draft didn't come back in a usable shape. Try rewording it, or build the poll by hand.")


def clean(data, films=(), prompt=''):
    """A validated draft: {title, description, poll_type, scoring_mode,
    categories: [{title, options: [{text, extra?}]}], notes}."""
    if not isinstance(data, dict):
        raise DraftError("The AI's draft didn't come back in a usable shape. Try rewording it, or build the poll by hand.")
    by_title = {}
    for f in films:
        by_title.setdefault(_norm(f.movie.title), f)

    def option(o):
        text = (o.get('text') if isinstance(o, dict) else o)
        text = re.sub(r'\s+', ' ', str(text or '')).strip()[:200]
        if not text:
            return None
        out = {'text': text}
        f = by_title.get(_norm(text))
        if f:
            out['extra'] = {'movie_id': f.movie.id, 'poster_url': f.movie.poster_url, 'year': f.year}
        return out

    categories = []
    for c in (data.get('categories') or [])[:MAX_CATEGORIES]:
        if not isinstance(c, dict):
            continue
        title = re.sub(r'\s+', ' ', str(c.get('title') or '')).strip()[:200]
        opts, seen = [], set()
        for o in (c.get('options') or [])[:MAX_OPTIONS]:
            o = option(o)
            if o and o['text'].casefold() not in seen:
                seen.add(o['text'].casefold())
                opts.append(o)
        if title and len(opts) >= 2:
            categories.append({'title': title, 'options': opts})
    if not categories:
        raise DraftError("The AI couldn't draft categories for that. Try being more specific, or build the poll by hand.")
    poll_type = data.get('poll_type') if data.get('poll_type') in ('standard', 'prediction') else 'standard'
    mode = data.get('scoring_mode') if data.get('scoring_mode') in ('none', 'single', 'ranked', 'confidence') else None
    if mode is None or (poll_type == 'prediction' and mode == 'none'):
        mode = 'single' if poll_type == 'prediction' else 'none'
    return {
        'title': re.sub(r'\s+', ' ', str(data.get('title') or prompt or 'New poll')).strip()[:120],
        'description': str(data.get('description') or '').strip()[:400],
        'poll_type': poll_type, 'scoring_mode': mode, 'categories': categories,
        'notes': str(data.get('notes') or '').strip()[:300],
    }


SCOPE_RULES = {
    'playing': ("This poll is about LOCAL SHOWINGS: film options must come from the PLAYING list, written exactly as "
                "listed (categories about people, e.g. Best Actor, may name people in those films)."),
    'all': ("This poll is about FILMS IN GENERAL: use any films (your own knowledge), not only what's playing. "
            "Write titles as they're commonly known."),
}


class _Linked:
    """A database film to link an option to (same shape playing_films gives)."""
    def __init__(self, movie):
        self.movie = movie
        y = (movie.release_year or '')[:4]
        self.year = int(y) if y.isdigit() else None


def _library_films(texts):
    """Films in our database whose titles match these option texts (for
    "all films" drafts): posters and years for whatever we know."""
    from app import db, Movie
    variants = set()
    for t in texts:
        base = re.sub(r'\s*\((19|20)\d\d\)\s*$', '', (t or '').strip()).lower()
        if base:
            variants.update({base, f'the {base}', base[4:] if base.startswith('the ') else base})
    if not variants:
        return []
    wanted = {_norm(t) for t in texts if t}
    best = {}
    for m in Movie.query.filter(db.func.lower(Movie.title).in_(variants)).limit(500):
        key = _norm(m.title)
        if key in wanted and (key not in best or (m.poster_url and not best[key].movie.poster_url)):
            best[key] = _Linked(m)
    return list(best.values())


def draft(group, prompt, now=None, scope='playing'):
    """Draft a poll for `prompt`, based on local showings ("playing") or films
    in general ("all"). Raises ai.RateLimited, ai.Unavailable or DraftError."""
    import ai
    now = now or datetime.now()
    scope = scope if scope in SCOPES else 'playing'
    today = f"Today is {now.strftime('%A, %B %-d, %Y')}. Club: {group.name}.\n"
    if scope == 'playing':
        playing = playing_films(group, prompt, now)
        listing = '\n'.join(f'- {line}' for _, line in playing) or '(nothing listed right now)'
        user = f"{today}PLAYING at the club's theatres in the next {WINDOW_DAYS} days:\n{listing}\n\nRequest: {prompt}"
    else:
        playing = []
        user = f"{today}Request: {prompt}"
    messages = [{'role': 'system', 'content': SYSTEM.replace('{scope_rule}', SCOPE_RULES[scope])},
                {'role': 'user', 'content': user}]
    data = _parse(ai.chat(messages, max_tokens=2000, json_mode=True))
    if scope == 'all':
        texts = [o.get('text') if isinstance(o, dict) else o
                 for c in (data.get('categories') or []) if isinstance(c, dict) for o in (c.get('options') or [])]
        playing = _library_films([str(t) for t in texts])
        return {**clean(data, playing, prompt), 'scope': scope}
    return {**clean(data, [f for f, _ in playing], prompt), 'scope': scope}
