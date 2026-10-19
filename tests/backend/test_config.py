"""The settings: every one the code reads is in both env templates, and the
startup check names what's missing (and what's needed on the real site)."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
READ = re.compile(r"""os\.(?:environ\.get|getenv)\(\s*['"]([A-Z][A-Z0-9_]+)['"]|os\.environ\[['"]([A-Z][A-Z0-9_]+)['"]\]""")
# Set by the Docker setup itself, not by whoever installs the site
INTERNAL = {'WARM_PUBLIC_CACHE', 'BOT_API_BASE', 'HELP_JSON'}


def code_settings():
    names = set()
    for top in ('backend', 'bot'):
        for here, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ('venv', '__pycache__', 'instance')]
            for f in files:
                if f.endswith('.py'):
                    with open(os.path.join(here, f)) as fh:
                        names |= {a or b for a, b in READ.findall(fh.read())}
    return names - INTERNAL


def template(path):
    with open(os.path.join(ROOT, path)) as fh:
        return {line.split('=', 1)[0].strip() for line in fh if re.match(r'^[A-Z][A-Z0-9_]*=', line)}


def test_every_setting_is_in_both_templates():
    used = code_settings()
    assert {'SECRET_KEY', 'DISCORD_BOT_TOKEN', 'TMDB_API_TOKEN'} <= used
    for path in ('.env.production.example', 'backend/.env.example'):
        listed = template(path)
        assert used - listed == set(), f'{path} is missing {sorted(used - listed)}'
        assert listed - used == set(), f'{path} lists unused {sorted(listed - used)}'


def test_startup_check_names_whats_missing():
    import config_check
    said = []
    gaps = config_check.report({'FRONTEND_URL': 'https://cinemaclubdc.com', 'SECRET_KEY': 'x'}, out=said.append)
    names = {g[0] for g in gaps}
    assert 'SECRET_KEY' not in names and {'SMTP_EMAIL', 'INTERNAL_API_TOKEN', 'GROQ_API_KEY'} <= names
    assert 'SMTP_EMAIL' in said[0] and 'NEEDED' in said[0]               # the real site needs email
    said.clear()
    config_check.report({'FRONTEND_URL': 'http://localhost:5173'}, out=said.append)
    assert 'NEEDED' not in said[0]                                       # a laptop needs nothing
    full = {name: 'x' for name, _, _ in config_check.SETTINGS}
    assert config_check.report(full, out=said.append) == []


def test_bot_names_its_missing_settings():
    import bot
    said = []
    assert [g[0] for g in bot.report_settings({'INTERNAL_API_TOKEN': 'x'}, out=said.append)] == ['DISCORD_CHANNEL_ID', 'GROQ_API_KEY']
    assert 'docs/discord-bot.md' in said[0]
