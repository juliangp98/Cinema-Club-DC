"""Small helpers the tests share."""
import os

H = {'X-Internal-Token': os.environ['INTERNAL_API_TOKEN']}      # the bot's internal API header


def client(uid=None):
    """A test client, signed in as `uid` (or a visitor)."""
    from app import app
    c = app.test_client()
    if uid:
        with c.session_transaction() as s:
            s['user_id'] = uid
    return c


def setup_db():
    """Create tables and run migrations on the fresh copy (what the server does on start)."""
    from app import app, db, migrate
    with app.app_context():
        db.create_all()
        migrate()


def patch_bot_api():
    """Route the bot's calls to the backend through the Flask test client:
    the real bot code against the real backend, no network, no Discord."""
    from app import app
    import bot
    from api import ApiError
    flask = app.test_client()

    def _resp(r):
        if r.status_code >= 400:
            raise ApiError(r.status_code, r.get_data(as_text=True))
        return r.get_json()

    async def get(path, **params):
        return _resp(flask.get(path, query_string={k: v for k, v in params.items() if v is not None}, headers=H))

    async def send(method, path, payload=None):
        return _resp(flask.open(path, method=method, json=payload or {}, headers=H))

    bot.api.get = get
    bot.api._send = send
    # The test server (FakeInteraction's guild 900) is the home club's, as the
    # bot registers its own server at start; other guild ids stay unconnected.
    from features import chat, schedule, servers, shared, threads
    shared._servers.clear()
    shared._servers[900] = {'group_id': shared.DEFAULT_GROUP_ID, 'channel_id': None, 'home': True}
    # Caches the bot keeps for a run (each test is its own run)
    for cache in (threads._webhooks, threads._perm_warned, shared._dm_last, shared._theatre_cache,
                  servers._dm_clubs, chat._quote_cache, schedule._find_options_cache):
        cache.clear()
    shared._club.set(shared._UNSET)          # no club carried over from another test's interaction
    return bot


BOT_MODULES = ('bot', 'features.shared', 'features.chat', 'features.alerts', 'features.schedule', 'features.threads',
               'features.profile', 'features.polls', 'features.admin', 'features.games', 'features.club', 'features.servers')


def patch_bot(**names):
    """Swap module-level names in the bot — the channel lookup, the owner DM,
    the clock. The bot is split by feature, so a name like movies_channel lives
    in each module that uses it; this swaps it in all of them (conftest puts
    them back after each test)."""
    import sys
    import bot  # noqa: F401 — loads every module
    for m in BOT_MODULES:
        mod = sys.modules.get(m)
        for name, value in names.items():
            if mod is not None and hasattr(mod, name):
                setattr(mod, name, value)


def all_linked_present():
    """Everyone with Discord linked is in the club's server, as the bot reports
    after its member sync (only they ever appear in Discord, R6a.1)."""
    from app import app, User
    with app.app_context():
        ids = [u.discord_user_id for u in User.query.filter(User.discord_user_id.isnot(None))]
    r = app.test_client().post('/api/internal/discord/members', json={'full': True, 'ids': ids}, headers=H)
    assert r.status_code == 200, r.get_data(as_text=True)


def film_id(title, **fields):
    """A film by title from the base data, made if this snapshot lacks it (call inside an app context)."""
    from app import db, Movie
    m = Movie.query.filter_by(title=title).first()
    if not m:
        m = Movie(title=title, **fields)
        db.session.add(m)
        db.session.flush()
    return m.id


class FakeInteraction:
    """A Discord interaction stand-in for calling bot commands directly: it
    records everything the bot sends. `sent` items: (kind, content, kwargs)."""
    def __init__(self, uid=500, name='tester', guild_id=900, data=None):
        from types import SimpleNamespace
        self.user = SimpleNamespace(id=uid, name=name, display_name=name.title(), mention=f'<@{uid}>', bot=False,
                                    display_avatar=None)
        self.guild_id, self.channel_id, self.data, self.sent, self.message = guild_id, 1, data or {}, [], None
        outer = self

        class Response:
            def is_done(self):
                return any(k in ('defer', 'message', 'edit') for k, *_ in outer.sent)

            async def defer(self, **kw):
                outer.sent.append(('defer', None, kw))

            async def send_message(self, content=None, **kw):
                outer.sent.append(('message', content, kw))

            async def edit_message(self, content=None, **kw):
                outer.sent.append(('edit', content, kw))

            async def send_modal(self, modal):
                outer.sent.append(('modal', modal, {}))

        class Followup:
            async def send(self, content=None, **kw):
                outer.sent.append(('followup', content, kw))

        self.response, self.followup = Response(), Followup()

    async def edit_original_response(self, content=None, **kw):     # the edit after a defer
        self.sent.append(('edit', content, kw))

    @property
    def last(self):
        return self.sent[-1]


def items_of(view):
    """A view's components (DynamicItems unwrapped)."""
    return [getattr(c, 'item', c) for c in (view.children if view else [])]


def press(cls, custom_id, it, item=None, values=None):
    """Press a bot button (or pick in a select) by its custom id, as Discord
    would after a restart: rebuild the DynamicItem `cls` from the id, then
    run its callback with `it` (a FakeInteraction). Returns `it`."""
    import asyncio
    import re
    m = re.fullmatch(cls.__discord_ui_compiled_template__, custom_id)
    assert m, f'{custom_id} is not a {cls.__name__}'
    if values is not None:
        it.data = {'values': values}

    async def go():
        await (await cls.from_custom_id(it, item, m)).callback(it)
    asyncio.run(go())
    return it


def seed_compare_pair():
    """Ana and Bo share the club (group 1); Ana is also in a private club Bo
    isn't; Eve shares nothing. Screenings: SIRÂT (Ana going, Bo maybe),
    HAMNET (Ana), VERTIGO (Bo), KHARTOUM (Ana, private club), SINNERS (next
    showing); past: SIRÂT both went, HAMNET Ana only. Watchlists: both want
    SINNERS, Bo wants HAMNET, Ana wants VERTIGO and KHARTOUM. Returns ids."""
    from datetime import datetime, timedelta
    from app import app, db, User, Group, GroupMembership, RSVP, Showtime, Theatre, Watchlist
    setup_db()
    with app.app_context():
        now = datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        films = {t: film_id(t) for t in ('SIRÂT', 'HAMNET', 'VERTIGO', 'SINNERS', 'KHARTOUM')}

        def show(title, days):
            s = Showtime(movie_id=films[title], theatre_id=tid, start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=2))
            db.session.add(s)
            db.session.flush()
            return s.id
        ids = {'both': show('SIRÂT', 1), 'ana_hamnet': show('HAMNET', 2), 'bo_vertigo': show('VERTIGO', 3),
               'private': show('KHARTOUM', 4), 'sinners_next': show('SINNERS', 5),
               'together': show('SIRÂT', -3), 'ana_only': show('HAMNET', -4)}
        g2 = Group(name='Ana Private', slug='ana-private', is_public=False)
        db.session.add(g2)
        db.session.flush()
        ana = User(email='ana7@test.dev', name='Ana', is_active=True, discord_user_id='7701')
        bo = User(email='bo7@test.dev', name='Bo', is_active=True, discord_user_id='7702')
        eve = User(email='eve7@test.dev', name='Eve', is_active=True)
        db.session.add_all([ana, bo, eve])
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=1, status='active'),
                            GroupMembership(user_id=ana.id, group_id=g2.id, status='active'),
                            GroupMembership(user_id=bo.id, group_id=1, status='active')])
        for u, key, gid, st in [(ana, 'both', 1, 'going'), (bo, 'both', 1, 'maybe'), (ana, 'ana_hamnet', 1, 'going'),
                                (bo, 'bo_vertigo', 1, 'going'), (ana, 'private', g2.id, 'going'),
                                (ana, 'together', 1, 'going'), (bo, 'together', 1, 'going'), (ana, 'ana_only', 1, 'going')]:
            db.session.add(RSVP(user_id=u.id, showtime_id=ids[key], group_id=gid, status=st))
        for u, t in [(ana, 'SINNERS'), (bo, 'SINNERS'), (bo, 'HAMNET'), (ana, 'VERTIGO'), (ana, 'KHARTOUM')]:
            db.session.add(Watchlist(user_id=u.id, movie_id=films[t]))
        db.session.commit()
        ids.update(ana=ana.id, bo=bo.id, eve=eve.id)
    all_linked_present()
    return ids
