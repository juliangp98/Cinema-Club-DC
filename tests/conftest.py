"""Shared test setup.

Every test gets a fresh copy of the base database (fixtures/base.db: an old
production snapshot, which also exercises the migrations), a private instance
folder for uploads, and cleared in-memory caches, so tests never depend on
each other's leftovers. Everything runs in one process: the app is imported
once, the database file is swapped underneath it.
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DB = os.path.join(HERE, 'fixtures', 'base.db')
WORK = tempfile.mkdtemp(prefix='cinemaclub-tests-')
DB_PATH = os.path.join(WORK, 'test.db')
shutil.copy(BASE_DB, DB_PATH)

# Before the app is imported: a test database and no real outside services.
os.environ.update({
    'DATABASE_URL': f'sqlite:///{DB_PATH}', 'INTERNAL_API_TOKEN': 'test-token', 'SECRET_KEY': 'test-secret',
    'GROQ_API_KEY': 'fake', 'GROQ_MODEL': '', 'GROQ_FALLBACK_MODEL': '', 'SMTP_EMAIL': '', 'SMTP_PASSWORD': '',
    'TMDB_API_KEY': '', 'TMDB_API_TOKEN': '', 'OMDB_API_KEY': '', 'DEFAULT_GROUP_ID': '1', 'FRONTEND_URL': 'https://cinemaclubdc.com',
    'DISCORD_CLIENT_SECRET': '', 'WARM_PUBLIC_CACHE': '0', 'CINEMACLUB_TEST_WORK': WORK,
})

import pytest  # noqa: E402


def _reset_state(instance_dir):
    import app as A
    A.app.config['PROPAGATE_EXCEPTIONS'] = True      # a server error fails the test with its traceback
    import discover
    import ai
    with A.app.app_context():
        A.db.session.remove()
        A.db.engine.dispose()
    for suffix in ('', '-wal', '-shm', '.pre-discord-accounts.bak'):
        try:
            os.remove(DB_PATH + suffix)
        except FileNotFoundError:
            pass
    shutil.copy(BASE_DB, DB_PATH)
    A.app.instance_path = instance_dir
    for cache in (A._public_cache, A._uploads, A._ai_searches, discover._suggest_index):
        cache.clear()
    ai._client = None
    ai._extras.clear()
    ai._state.update(primary=None, fallback=None, how={}, available=[], checked_at=0.0)


# Module-level settings a test may swap (e.g. the Discord group, the bot's
# channel lookup) are put back afterwards.
SNAPSHOT_MODULES = ('app', 'discover', 'ai', 'poll_ai', 'search_ai', 'media', 'bot', 'embeds', 'llm', 'api',
                    'scrapers.base', 'scrapers.sync')


@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    _reset_state(str(tmp_path / 'instance'))
    saved = {m: dict(vars(sys.modules[m])) for m in SNAPSHOT_MODULES if m in sys.modules}
    yield
    for name, before in saved.items():
        mod = vars(sys.modules[name])
        for key in [k for k in mod if k not in before]:
            del mod[key]
        for key, value in before.items():
            if mod.get(key) is not value:
                mod[key] = value
