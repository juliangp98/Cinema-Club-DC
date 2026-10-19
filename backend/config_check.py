"""What the backend needs from its environment, checked once at start.

A setting that's missing doesn't stop the server (a local copy runs on very
little); it's named in one warning with what goes without it. The full list,
with how to get each value, is docs/configuration.md and the env templates
(.env.production.example, backend/.env.example).
"""
import os

# (name, what goes without it, needed in production?)
SETTINGS = (
    ('SECRET_KEY', 'sign-ins last only until the server restarts', True),
    ('FRONTEND_URL', 'links in emails and the secure session cookie', True),
    ('SMTP_EMAIL', 'sign-in links can only be printed to this console, not emailed', True),
    ('SMTP_PASSWORD', 'sign-in links can only be printed to this console, not emailed', True),
    ('INTERNAL_API_TOKEN', 'the Discord bot can\'t reach the backend', True),
    ('TMDB_API_TOKEN', 'films get no posters, cast or details from TMDB', False),
    ('OMDB_API_KEY', 'no IMDb / Rotten Tomatoes / Metacritic ratings or awards', False),
    ('GROQ_API_KEY', 'no ✨ Ask in Help, ✨ search or the bot\'s chat', False),
    ('VAPID_PUBLIC_KEY', 'no phone / browser push alerts', False),
    ('VAPID_PRIVATE_KEY', 'no phone / browser push alerts', False),
)


def production(env=os.environ):
    """Served over https: the real site, not a laptop."""
    return env.get('FRONTEND_URL', '').startswith('https://')


def missing(env=os.environ):
    """[(name, what goes without it, needed)] for each setting that's unset."""
    return [(name, why, needed) for name, why, needed in SETTINGS if not env.get(name, '').strip()]


def report(env=os.environ, out=print):
    """Warn about missing settings, once. Production says which are needed."""
    gaps = missing(env)
    if not gaps:
        return gaps
    live = production(env)
    lines = ['⚠️  Settings not set (see docs/configuration.md):']
    for name, why, needed in gaps:
        flag = '  NEEDED' if needed and live else ''
        lines.append(f'   {name:<20} {why}{flag}')
    out('\n'.join(lines))
    return gaps
