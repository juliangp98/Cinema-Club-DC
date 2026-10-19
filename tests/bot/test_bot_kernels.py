"""Kernels in Discord (R10b): 🍿 My kernels on /play (your total, where it
came from, this week's allowance, how to earn), the breakdown on /leaderboard
and /profile, and 🍿 Give kernels on someone's /profile (the feed's rules)."""
import asyncio
from datetime import datetime, timedelta

import pytest

from helpers import items_of, press as tap, FakeInteraction, all_linked_present, client, patch_bot_api, setup_db


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
    tap(bot.PlayButton, 'play:kernels', it)
    _, _, kw = it.last
    e = kw['embed']
    assert kw['ephemeral'] is True and e.title == '🍿 Your kernels: 9'
    assert e.description == 'polls 0 · going out 7 · from members 2'
    fields = {f.name: f.value for f in e.fields}
    assert fields['Going out'].startswith('Checked in +5 · planned it +2')
    assert fields['This week'].startswith('10 to give · 3 to take')
    assert '**+5**' in fields['How to earn'] and 'up to 10 a week' in fields['How to earn']


def test_kernels_without_an_account(bot):
    it = FakeInteraction(uid=5555, name='nobody', guild_id=None)        # a DM: only existing accounts
    tap(bot.PlayButton, 'play:kernels', it)
    assert it.last[1] == bot.NO_ACCOUNT_MSG


def test_the_leaderboard_and_profile_say_where_kernels_came_from(bot):
    it = FakeInteraction(uid=9402, name='bo')
    asyncio.run(bot.leaderboard.callback(it))
    assert '🥇 **Ana** — 🍿 9 (polls 0 · going out 7 · from members 2)' in it.last[2]['embed'].description
    it = FakeInteraction(uid=9401, name='ana')
    asyncio.run(bot.profile.callback(it))
    fields = {f.name: f.value for f in it.last[2]['embed'].fields}
    assert fields['Kernels'] == '🍿 9 (polls 0 · going out 7 · from members 2)'


def test_ties_share_a_place_and_nobody_medals_at_zero():
    import embeds
    assert [embeds.medal(p, k) for p, k in ((1, 9), (1, 9), (3, 4), (4, 0))] == ['🥇', '🥇', '🥉', '4.']
    assert embeds.medal(1, 0) == '1.'                                              # everyone on 0: no 🥈 on top


def test_give_kernels_from_a_profile(bot):
    """Bo gave Ana 2 for KERNEL NIGHT on the feed; from her /profile he gives a third, and that's the cap."""
    from types import SimpleNamespace
    it = FakeInteraction(uid=9402, name='bo')
    asyncio.run(bot.profile.callback(it, member=SimpleNamespace(id=9401, display_name='Ana')))
    give = next(b for b in items_of(it.last[2]['view']) if b.label == '🍿 Give kernels')
    assert give.custom_id == 'prof:give:9401'
    opened = tap(bot.ProfileButton, give.custom_id, FakeInteraction(uid=9402, name='bo'))
    kw = opened.last[2]
    assert kw['ephemeral'] and kw['embed'].title == '🍿 Give Ana kernels'
    assert '**KERNEL NIGHT**' in kw['embed'].description and 'checked in · you: +2' in kw['embed'].description
    assert kw['embed'].footer.text.startswith('This week you have 8 to give')
    [pick] = items_of(kw['view'])
    sid = pick.options[0].value
    chosen = tap(bot.GiveSelect, pick.custom_id, FakeInteraction(uid=9402, name='bo'), values=[sid])
    ups = [b.custom_id for b in items_of(chosen.last[2]['view'])[1:]]
    assert ups == [f'give:up:9401:{sid}', f'give:down:9401:{sid}']
    done = tap(bot.GiveButton, ups[0], FakeInteraction(uid=9402, name='bo'))
    assert done.last[0] == 'edit' and 'you: +3' in done.last[2]['embed'].description
    capped = tap(bot.GiveButton, ups[0], FakeInteraction(uid=9402, name='bo'))
    assert capped.last[1] == 'Up to 3 kernels per person per screening.'
    me = tap(bot.ProfileButton, 'prof:give:9402', FakeInteraction(uid=9402, name='bo'))
    assert "That's you" in me.last[1]
