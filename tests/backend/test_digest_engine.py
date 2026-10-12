"""The weekly digest picks its films with the Discover engine (R9a): a film is
"rare", "last chance" or "opening" by the same rules on the site and in the
digest, and each film is in at most one digest section."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db


@pytest.fixture
def week():
    """A club at AFI: a rare 35mm one-off, two members wanting an unplanned
    film, and a new release opening across two theatres."""
    from app import app, db, Group, GroupMembership, Movie, Showtime, Theatre, User, Watchlist
    setup_db()
    with app.app_context():
        afi, suns = (Theatre.query.filter_by(slug=s).first() for s in ('afi', 'suns'))
        g = Group(name='Digest Club', slug='digest-club', is_public=False, theatres='afi,suns')
        db.session.add(g)
        db.session.flush()
        day = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        def film(title, year, shows):
            m = Movie(title=title, release_year=str(year))
            db.session.add(m)
            db.session.flush()
            for th, h in shows:
                db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=day + timedelta(hours=h),
                                        format_label='35mm' if title == 'RARE PRINT' else None))
            return m
        film('RARE PRINT', 1961, [(afi, 19)])
        wanted = film('WANTED', 2001, [(afi, 20), (afi, 44)])
        film('NEW ONE', datetime.now().year, [(afi, 21), (suns, 22), (afi, 45)])
        for i in range(2):
            u = User(name=f'M{i}', email=f'm{i}@t.dev', is_active=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
            db.session.add(Watchlist(user_id=u.id, movie_id=wanted.id))
        db.session.commit()
        return g.id


def test_the_digest_uses_the_discover_shelves(week):
    import discover
    from app import app, db, Group, DIGEST_CAPS, PLAN_MIN_WATCHERS
    d = client().get('/api/internal/digest', query_string={'group_id': week, 'days': 7}, headers=H).json
    sections = {k: [x['title'] for x in d[k]] for k in ('plans', 'rare', 'last_chance', 'opening')}
    assert sections['plans'] == ['WANTED'] and sections['rare'][0] == 'RARE PRINT'
    titles = [t for ts in sections.values() for t in ts]
    assert len(titles) == len(set(titles))                       # each film in one section
    with app.app_context():
        group = db.session.get(Group, week)
        _, picks = discover.weekly(group, days=7, caps=DIGEST_CAPS, plan_min=PLAN_MIN_WATCHERS)
        assert sections == {k: [f.movie.title for f, _, _ in v] for k, v in picks.items()}   # the engine's picks
        now = datetime.now()
        films = discover.catalog(group, now, now + timedelta(days=7))
        rare_shelf = [f.movie.title for f, _ in discover.shelf('rare', films, discover.context(group, None, films, now))]
        assert set(sections['rare']) <= set(rare_shelf)          # "rare" means what Discover's shelf means
