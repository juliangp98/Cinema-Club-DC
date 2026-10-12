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

WORK = os.environ['CINEMACLUB_TEST_WORK']        # a scratch folder for the test run


class Checks:
    """Named checks inside one test: every failure is reported, not just the first."""
    def __init__(self):
        self.failed, self.count = [], 0

    def check(self, name, cond, detail=''):
        self.count += 1
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond or detail == '' else f'   [{str(detail)[:600]}]'))
        if not cond:
            self.failed.append(name + (f'   [{str(detail)[:600]}]' if detail != '' else ''))

    def done(self):
        assert not self.failed, f'{len(self.failed)} of {self.count} checks failed:\n  ' + '\n  '.join(self.failed)


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
    return bot


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

    @property
    def last(self):
        return self.sent[-1]


def items_of(view):
    """A view's components (DynamicItems unwrapped)."""
    return [getattr(c, 'item', c) for c in (view.children if view else [])]


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
