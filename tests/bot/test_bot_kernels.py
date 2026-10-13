"""Kernels in Discord (R10b): /kernels (your total, where it came from, this
week's allowance, how to earn), and the breakdown on /leaderboard and /profile."""
import asyncio
from datetime import datetime, timedelta

import pytest

from helpers import FakeInteraction, all_linked_present, client, patch_bot_api, setup_db


@pytest.fixture
def bot():
    """Ana (9401) said she was going to a screening yesterday and checked in;
    Bo (9402) gave her 2 kernels for it."""
    from app import app, db, Attendance, GroupMembership, Movie, RSVP, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        ana = User(name='Ana', discord_user_id='9401', is_active=True)
        bo = User(name='Bo', discord_user_id='9402', email='bo@k.test', is_active=True)
        m = Movie(title='KERNEL NIGHT')
        db.session.add_all([ana, bo, m])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        s = Showtime(movie_id=m.id, theatre_id=Theatre.query.filter_by(slug='afi').first().id,
                     start_time=datetime.now() - timedelta(days=1))
        db.session.add(s)
        db.session.flush()
        db.session.add(RSVP(user_id=ana.id, showtime_id=s.id, group_id=1, status='going'))
        db.session.add(Attendance(user_id=ana.id, showtime_id=s.id, status='went', source='discord',
                                  answered_at=datetime.utcnow()))
        db.session.commit()
        ids = (ana.id, bo.id, s.id)
    for _ in range(2):
        assert client(ids[1]).post('/api/kernels/toss', json={'group_id': 1, 'showtime_id': ids[2], 'user_id': ids[0],
                                                              'delta': 1}).status_code == 200
    all_linked_present()
    return patch_bot_api()


def test_kernels_shows_the_total_and_how_to_earn(bot):
    it = FakeInteraction(uid=9401, name='ana')
    asyncio.run(bot.kernels_cmd.callback(it))
    _, _, kw = it.last
    e = kw['embed']
    assert kw['ephemeral'] is True and e.title == '🍿 Your kernels: 9'
    assert e.description == 'polls 0 · going out 7 · from members 2'
    fields = {f.name: f.value for f in e.fields}
    assert fields['Going out'].startswith('Checked in +5 · planned it +2')
    assert fields['This week'].startswith('10 to give · 3 to take')
    assert '**+5**' in fields['How to earn'] and 'up to 10 a week' in fields['How to earn']


def test_kernels_without_an_account(bot):
    it = FakeInteraction(uid=5555, name='nobody')
    asyncio.run(bot.kernels_cmd.callback(it))
    assert it.last[1] == bot.NO_ACCOUNT_MSG


def test_the_leaderboard_and_profile_say_where_kernels_came_from(bot):
    it = FakeInteraction(uid=9402, name='bo')
    asyncio.run(bot.leaderboard.callback(it))
    assert '🥇 **Ana** — 🍿 9 (polls 0 · going out 7 · from members 2)' in it.last[2]['embed'].description
    it = FakeInteraction(uid=9401, name='ana')
    asyncio.run(bot.profile.callback(it))
    fields = {f.name: f.value for f in it.last[2]['embed'].fields}
    assert fields['Kernels'] == '🍿 9 (polls 0 · going out 7 · from members 2)'
