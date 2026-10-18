"""Repertory bingo in Discord (R10e): 🎱 My bingo card on /play shows your
card privately — once the club has bingo on — and 🍿 My kernels explains what it's worth."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from helpers import press as tap, FakeInteraction, all_linked_present, client, patch_bot_api, setup_db


@pytest.fixture
def bot():
    """Ana (9701) checked in to a 35mm 1950 horror matinee this month; Adm is the club's admin."""
    import bingo
    from app import app, db, Attendance, BingoCard, GroupMembership, Movie, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        ana = User(name='Ana', discord_user_id='9701', is_active=True)
        adm = User(name='Adm', email='adm@b.test', is_active=True)
        m = Movie(title='NOSFERATU', release_year='1950', genres='horror', runtime_minutes=160)
        db.session.add_all([ana, adm, m])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active'))
        db.session.add(GroupMembership(user_id=adm.id, group_id=1, status='active', role='admin'))
        s = Showtime(movie_id=m.id, theatre_id=Theatre.query.filter_by(slug='afi').first().id, format_label='35mm',
                     start_time=datetime.now().replace(day=1, hour=14, minute=0) + timedelta(days=1))
        db.session.add(s)
        db.session.flush()
        db.session.add(Attendance(user_id=ana.id, showtime_id=s.id, status='went', source='discord',
                                  answered_at=datetime.utcnow()))
        db.session.add(BingoCard(group_id=1, month=bingo.month_of(), squares_json=json.dumps(
            ['film', 'pre1960', 'horror', 'late', 'comedy', 'documentary', 'event', 'big'])))
        db.session.commit()
        slug, admin = db.session.get(__import__('app').Group, 1).slug, adm.id
    all_linked_present()
    b = patch_bot_api()
    b.on = lambda: client(admin).put(f'/api/groups/{slug}', json={'bingo_enabled': True})
    return b


def test_bingo_is_off_until_the_club_turns_it_on(bot):
    it = FakeInteraction(uid=9701, name='ana')
    tap(bot.PlayButton, 'play:bingo', it)
    assert 'Bingo is off' in it.last[1]


def test_your_card(bot):
    bot.on()
    it = FakeInteraction(uid=9701, name='ana')
    tap(bot.PlayButton, 'play:bingo', it)
    _, _, kw = it.last
    e = kw['embed']
    assert kw['ephemeral'] is True and e.title.startswith('🎱 Repertory bingo · ')
    assert e.description.startswith('✅ ✅ ✅\n⬜ 🍿 ⬜\n⬜ ⬜ ⬜')                # the top row: a line
    assert '🎉 **Bingo!**' in e.description and '✅ 🎞️ **On film** — NOSFERATU' in e.description
    assert 'earned 5 this month' in e.footer.text


def test_kernels_explains_bingo_when_its_on(bot):
    bot.on()
    it = FakeInteraction(uid=9701, name='ana')
    tap(bot.PlayButton, 'play:kernels', it)
    e = it.last[2]['embed']
    assert 'bingo 5' in e.description
    assert 'Repertory bingo: **+5** for a line, **+15** for the full card' in {f.name: f.value for f in e.fields}['How to earn']


def test_home_squares_show_a_house():
    """R15: a square a diary entry filled shows 🏠 and the film, and the footer says how home squares count."""
    import embeds
    sq = [{'key': k, 'emoji': '🎞️', 'label': k.title(), 'hint': 'h', 'done': False, 'by': None, 'home': None} for k in 'abcdefgh']
    sq.insert(4, {'key': 'free', 'emoji': '🍿', 'label': 'Free', 'hint': '', 'done': True})
    sq[1].update(done=True, home={'title': 'OLD DOC', 'watched_on': '2026-10-05', 'link': ''})
    sq[2].update(done=True, by={'title': 'VERTIGO'})
    b = {'squares': sq, 'month_label': 'October 2026', 'full': False, 'line': False, 'filled': 2, 'kernels': 0, 'club': [],
         'rules': {'line': 5, 'full': 15, 'home': True, 'home_line': 3, 'home_full': 10}}
    e = embeds.bingo_embed(b)
    assert e.description.splitlines()[0] == '⬜ 🏠 ✅'
    assert '🏠 🎞️ **B** — OLD DOC (at home)' in e.description and '✅ 🎞️ **C** — VERTIGO' in e.description
    assert 'a line that needs one +3' in e.footer.text and 'the full card +10' in e.footer.text
