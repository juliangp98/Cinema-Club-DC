"""✨ AI search (R6c): a plain-English request ("something spooky and short
this weekend near downtown") becomes Browse filters.

The Discover engine reads what it can first, for free (discover.parse_request:
shelves, moods, genres, decades, when, where). Only when words are left over
that it couldn't place does the shared AI (ai.py) read the request, with that
first reading as a hint. Whatever the AI returns is checked against the real
filter values, so it can only ever produce a valid Browse view.
"""

import json
import re

FILLER = set("""a an the some something anything any me us i we you to for of in on at with and or but
movie movies film films flick flicks show shows showing showings playing play see watch watching catch find
looking look want wanna would like good great nice please this that these those next what whats what's is
are be there here near around can could should get go going out tonight's maybe kind sort really very just
one ones new""".split())

SORTS = ('soonest', 'rarest', 'wanted', 'critics', 'title')
FIXED = {'format': ('film', 'big'), 'time': ('matinee', 'evening', 'late'), 'runtime': ('short', 'long'),
         'rarity': ('rare', 'repertory', 'wide'), 'sort': SORTS}

SYSTEM = """You turn a moviegoer's request into search filters for a Washington, DC film club's showtimes site.
Reply with ONE JSON object: {"params": {...}, "search": ""}.

Allowed params (leave out anything the request doesn't ask for):
- "shelf": one of {shelves}
- "mood": one of {moods}
- "genres": comma-separated, from: {genres}
- "when": one of tonight, tomorrow, weekend, week, 2weeks, month
- "regions": comma-separated, from: dc, maryland, virginia
- "theatres": comma-separated slugs, from: {theatres}
- "decade": a decade's first year, e.g. "1980"
- "format": "film" (35/16/70mm prints) or "big" (IMAX, 70mm, Dolby)
- "time": "matinee" (before 5pm), "evening" (5-9pm) or "late" (9:30pm or later)
- "runtime": "short" (under 95 min) or "long" (over 2.5 hours)
- "rarity": "rare", "repertory" (5+ years old) or "wide" (wide release)
- "sort": one of soonest, rarest, wanted, critics, title{club}
"search" is ONLY a film title or a person's name the request names (else ""). Never invent titles.
Prefer one shelf or mood over many genres. Downtown, Penn Quarter, Georgetown and the like are DC.
"""


def leftover_words(text, genres=()):
    """Words the plain reading didn't account for (filler removed)."""
    import discover as D
    t = D.normalize(text).replace('’', "'")
    for words in (D._SHELF_WORDS, D._MOOD_WORDS, D._WHEN_WORDS, D._REGION_WORDS, D._THEATRE_WORDS):
        for _, pattern in words:
            t = re.sub(pattern, ' ', t)
    for g in genres:
        t = re.sub(rf"\b{re.escape(g)}\b", ' ', t)
    t = D._DECADE.sub(' ', t)
    t = re.sub(r"\b(my watchlist|on my list)\b", ' ', t)
    return [w for w in re.findall(r"[a-z0-9']+", t) if w not in FILLER and len(w) > 1]


def clean(params, search, *, genres, theatres, group, viewer):
    """Keep only real filter values (the AI's answer is never trusted as-is)."""
    import discover as D
    p = params if isinstance(params, dict) else {}
    out = {}

    def listed(key, allowed):
        vals = [v.strip().lower() for v in str(p.get(key) or '').split(',') if v.strip()]
        vals = [v for v in vals if v in allowed]
        if vals:
            out[key] = ','.join(dict.fromkeys(vals))

    shelf = str(p.get('shelf') or '')
    if shelf in D.SHELF_TITLES and not (shelf in ('friends', 'most-wanted') and not group) \
            and not (shelf == 'for-you' and not viewer):
        out['shelf'] = shelf
    if p.get('mood') in D.MOODS:
        out['mood'] = p['mood']
    listed('genres', set(genres))
    if p.get('when') in D.WHEN:
        out['when'] = p['when']
    listed('regions', set(D.REGION_KEYS))
    listed('theatres', set(theatres))
    decade = str(p.get('decade') or '')
    if re.fullmatch(r'(19[0-9]|20[0-2])0', decade):
        out['decade'] = decade
    for key, allowed in FIXED.items():
        if p.get(key) in allowed:
            out[key] = p[key]
    club = p.get('club')
    if (club == 'mine' and viewer) or (club in ('going', 'wanted') and group):
        out['club'] = club
    s = re.sub(r'\s+', ' ', str(search or '')).strip()[:80]
    if s:
        out['q'] = s
    return out


def interpret(group, viewer, text, now=None):
    """{'params', 'ai': bool, 'note'} for a request. Raises nothing: if the AI
    can't help, the plain reading (or the words as a title search) is used."""
    import discover as D
    from app import Theatre
    films = D.catalog(group, *D.window('month', now))
    genres = sorted({g for f in films.values() for g in f.genres} | D.COMMON_GENRES)
    slugs = {t.strip() for t in ((group.theatres or '') if group else '').split(',') if t.strip()}
    theatres = {t.slug: t.short_name or t.name for t in Theatre.query.filter(Theatre.is_active.isnot(False))
                if not slugs or t.slug in slugs}
    plain = D.parse_request(text, genres)
    rest = leftover_words(text, genres)
    note = None
    if plain and not rest:
        params, used_ai = plain, False
    else:
        import ai
        fill = dict(
            shelves=', '.join(k for k in D.SHELF_TITLES if not (k in ('friends', 'most-wanted') and not group)),
            moods=', '.join(f"{k} ({v['label']})" for k, v in D.MOODS.items()),
            genres=', '.join(genres), theatres=', '.join(f'{k} ({v})' for k, v in sorted(theatres.items())),
            club=('\n- "club": "going" (friends are going), "wanted" (on club watchlists) or "mine" (your list)'
                  if group else '\n- "club": "mine" (your own list)' if viewer else ''))
        system = SYSTEM
        for k, v in fill.items():                  # (the template has JSON braces, so no str.format)
            system = system.replace('{' + k + '}', v)
        user = f"Request: {text}\nAlready read without you (keep unless wrong): {json.dumps(plain)}"
        try:
            raw = ai.chat([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                          max_tokens=300, json_mode=True)
            data = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or '').strip()))
            params = clean({**plain, **(data.get('params') or {})}, data.get('search'),
                           genres=genres, theatres=theatres, group=group, viewer=viewer)
            used_ai = True
        except (ai.RateLimited, ai.Unavailable):
            params, used_ai, note = plain, False, "The AI is busy right now, so this is a plain reading."
        except Exception:
            params, used_ai, note = plain, False, "The AI's answer didn't make sense, so this is a plain reading."
        if not params:
            params = {'q': ' '.join(rest)[:80]} if rest else {}
    params = dict(params)
    params.setdefault('when', 'month')            # a request without a when looks a month ahead
    return {'params': params, 'ai': used_ai, 'note': note}
