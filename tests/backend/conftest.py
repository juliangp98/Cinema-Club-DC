"""Shared fixtures for the backend tests: the Versus Club (challenges,
tournaments, scouting)."""
import json
from datetime import datetime

import pytest

from helpers import setup_db

FILMS = [('ALPHA', 1950), ('BRAVO', 1962), ('CHARLIE', 1971), ('DELTA', 1984), ('ECHO', 1990), ('FOXTROT', 1999),
         ('GOLF', 2004), ('HOTEL', 2011), ('INDIA', 2018), ('JULIET', 1977)]


@pytest.fixture
def club():
    """Versus Club (our films; Who said it and Higher or lower on, challenges
    on): Ana (organizer), Bo, Cy and Di (members, Bo on Discord), Eve in
    another club. Everyone in Versus Club has 20 kernels to play with."""
    from app import app, db, Group, GroupMembership, KernelGift, Movie, Quote, Showtime, User
    setup_db()
    with app.app_context():
        g = Group(name='Versus Club', slug='versus-club', is_public=False, trivia_source='local', challenges_enabled=True,
                  quizzes_json=json.dumps({'who_said': True, 'higher_lower': True, 'still': True}))
        other = Group(name='Elsewhere', slug='elsewhere-v', is_public=False)
        us = {n: User(name=n, email=f'{n.lower()}@versus.test', is_active=True) for n in ('Ana', 'Bo', 'Cy', 'Di', 'Eve', 'Gift')}
        us['Bo'].discord_user_id = '9911'
        db.session.add_all([g, other, *us.values()])
        db.session.flush()
        for n, u in us.items():
            db.session.add(GroupMembership(user_id=u.id, group_id=(other if n == 'Eve' else g).id, status='active',
                                           role='organizer' if n == 'Ana' else 'member'))
        for i, (t, y) in enumerate(FILMS):
            db.session.add(Movie(title=t, release_year=str(y), tmdb_id=960000 + i, genres='drama'))
        cast = [{'name': n, 'character': c} for n, c in (('Humphrey Bogart', 'Rick Blaine'), ('Ingrid Bergman', 'Ilsa Lund'),
                                                        ('Paul Henreid', 'Victor Laszlo'), ('Claude Rains', 'Captain Renault'),
                                                        ('Conrad Veidt', 'Major Strasser'))]
        db.session.add(Movie(title='CASABLANCA', release_year='1942', tmdb_id=969999, genres='drama,romance',
                             cast_json=json.dumps(cast)))
        db.session.add(Quote(text='Here’s looking at you, kid.', movie='Casablanca', character='Rick'))
        show = Showtime.query.first()
        for n in ('Ana', 'Bo', 'Cy', 'Di'):
            db.session.add(KernelGift(giver_id=us['Gift'].id, recipient_id=us[n].id, group_id=g.id, showtime_id=show.id,
                                      week=datetime(2026, 1, 5).date(), amount=20))
        db.session.commit()
        return {'G': g.id, 'slug': g.slug, **{n: u.id for n, u in us.items()}}
