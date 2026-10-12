"""Every route's access rule (R9d): only the routes listed in PUBLIC answer a
visitor who isn't signed in; every /api/internal route refuses without the
bot's token. A new route that forgets its check fails here — add it to
PUBLIC only if anyone on the internet should get it."""
import re

import pytest

from helpers import H, client, setup_db

# Open to everyone: what's playing (public mode), link previews, and the
# sign-in machinery itself.
PUBLIC = {
    ('POST', '/api/auth/guest'), ('POST', '/api/auth/logout'), ('GET', '/api/auth/me'),
    ('GET', '/api/auth/providers'), ('GET', '/api/auth/discord/start'), ('GET', '/api/auth/discord/callback'),
    ('POST', '/api/auth/login'), ('POST', '/api/auth/signup'), ('POST', '/api/auth/verify'),
    ('POST', '/api/auth/accept-invite'),
    ('GET', '/api/discover'), ('GET', '/api/discover/browse'), ('GET', '/api/discover/calendar'),
    ('GET', '/api/discover/doubles'), ('GET', '/api/discover/spotlights'), ('GET', '/api/discover/surprise'),
    ('GET', '/api/films/<int:movie_id>'), ('GET', '/api/search/suggest'),
    ('GET', '/api/showtimes'), ('GET', '/api/showtimes/<int:showtime_id>'),
    ('GET', '/api/showtimes/<int:sid>/gcal-url'), ('GET', '/api/showtimes/<int:sid>/ical'),
    ('GET', '/api/theatres'), ('GET', '/api/theatres-overview'), ('GET', '/api/theatres/<slug>'),
    ('GET', '/api/og/films/<int:movie_id>'), ('GET', '/api/og/showtimes/<int:showtime_id>'),
    ('GET', '/api/og/theatres/<slug>'), ('GET', '/api/sitemap.xml'), ('GET', '/api/push/key'),
    ('GET', '/api/media/<name>'),
    # Calendar subscriptions: the secret token in the link is the key.
    ('GET', '/api/calendar/<token>.ics'), ('GET', '/api/calendar/club/<token>.ics'),
    ('GET', '/api/groups/discover'),
}
FILL = {'slug': 'suns', 'name': 'x.webp', 'token': 'not-a-real-token', 'thread_id': '1'}


def routes():
    from app import app
    for r in app.url_map.iter_rules():
        if r.endpoint == 'static':
            continue
        url = re.sub(r'<(?:(\w+):)?(\w+)>', lambda m: FILL.get(m.group(2), '1'), r.rule)
        for method in sorted(r.methods - {'HEAD', 'OPTIONS'}):
            yield method, r.rule, url


@pytest.fixture
def every_route():
    setup_db()
    return list(routes())


def test_the_public_list_names_real_routes(every_route):
    known = {(m, rule) for m, rule, _ in every_route}
    assert PUBLIC <= known, PUBLIC - known


def test_only_public_routes_answer_visitors(every_route):
    c = client()
    leaks = []
    for method, rule, url in every_route:
        if (method, rule) in PUBLIC or rule.startswith('/api/internal/'):
            continue
        r = c.open(url, method=method, json={} if method != 'GET' else None)
        if r.status_code < 400:
            leaks.append((method, rule, r.status_code))
    assert leaks == []


def test_the_bot_api_needs_its_token(every_route):
    c = client()
    for method, rule, url in every_route:
        if rule.startswith('/api/internal/'):
            assert c.open(url, method=method, json={}).status_code == 403, (method, rule)
            assert c.open(url, method=method, json={}, headers={'X-Internal-Token': 'wrong'}).status_code == 403
    assert client().get('/api/internal/theatres', headers=H).status_code == 200      # the real token works


@pytest.mark.parametrize('nxt, lands', [
    ('/films/3', '/films/3'), ('.evil.com', '/'), ('//evil.com', '/'), ('https://evil.com', '/'),
    ('/\\evil.com', '/'), ('@evil.com', '/'),
])
def test_sign_in_with_discord_only_returns_to_this_site(nxt, lands):
    import app as A
    setup_db()
    A.DISCORD_CLIENT_ID, A.DISCORD_CLIENT_SECRET = 'cid', 'secret'
    c = client()
    c.get('/api/auth/discord/start', query_string={'next': nxt})
    with c.session_transaction() as s:
        state = s['discord_oauth']['state']
    r = c.get('/api/auth/discord/callback', query_string={'state': state, 'error': 'access_denied'})
    assert r.headers['Location'].startswith(f"https://cinemaclubdc.com{lands}?")
