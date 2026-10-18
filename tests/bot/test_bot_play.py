"""/play in Discord (R10): the one games hub, privately — trivia and bingo
only when the club has them on, the quiz games (test_bot_quizzes.py), polls
waiting for your vote (with Vote buttons), and your kernels."""
import asyncio
import re

import pytest

from helpers import FakeInteraction, all_linked_present, client, items_of, patch_bot_api, setup_db


@pytest.fixture
def bot():
    """Ana (9801) in the Discord club (group 1), Adm its admin; an open poll."""
    from app import app, db, GroupMembership, Poll, PollCategory, PollOption, User
    setup_db()
    with app.app_context():
        Poll.query.filter_by(group_id=1).delete()
        ana = User(name='Ana', discord_user_id='9801', is_active=True)
        adm = User(name='Adm', email='adm@play.test', is_active=True)
        db.session.add_all([ana, adm])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active'))
        db.session.add(GroupMembership(user_id=adm.id, group_id=1, status='active', role='admin'))
        p = Poll(group_id=1, created_by=adm.id, title='Best of fall', status='open')
        db.session.add(p)
        db.session.flush()
        c = PollCategory(poll_id=p.id, title='Pick')
        db.session.add(c)
        db.session.flush()
        db.session.add_all([PollOption(category_id=c.id, text='x'), PollOption(category_id=c.id, text='y')])
        db.session.commit()
        slug, admin, pid = __import__('app').db.session.get(__import__('app').Group, 1).slug, adm.id, p.id
    all_linked_present()
    b = patch_bot_api()
    b.switch = lambda **on: client(admin).put(f'/api/groups/{slug}', json=on)
    b.poll_id = pid
    return b


def play(bot):
    it = FakeInteraction(uid=9801, name='ana')
    asyncio.run(bot.play_cmd.callback(it))
    return it.last[2]


def test_play_with_the_games_off(bot):
    kw = play(bot)
    e = kw['embed']
    assert kw['ephemeral'] is True and e.title.startswith('🎮 Play at ')
    assert 'Waiting for your vote: **Best of fall**' in e.description and '🍿 **0** kernels' in e.description
    assert 'trivia' not in e.description.lower() and 'bingo' not in e.description.lower()
    buttons = items_of(kw['view'])
    assert [b.custom_id for b in buttons] == ['play:kernels', f'vote:b:open:{bot.poll_id}:0:0:0', None]
    assert buttons[-1].url.endswith('/play')


def test_play_with_trivia_and_bingo_on(bot):
    bot.switch(trivia_enabled=True, bingo_enabled=True)
    kw = play(bot)
    assert "Today's trivia question is waiting" in kw['embed'].description
    assert '🎱 Bingo · ' in kw['embed'].description and '0/8' in kw['embed'].description
    ids = [b.custom_id for b in items_of(kw['view'])]
    assert ids[:2] == ['play:trivia', 'play:bingo']

    async def press(custom_id):
        m = re.fullmatch(bot.PlayButton.__discord_ui_compiled_template__, custom_id)
        btn = await bot.PlayButton.from_custom_id(None, None, m)
        it = FakeInteraction(uid=9801, name='ana')
        await btn.callback(it)
        return it.last[2]
    assert asyncio.run(press('play:trivia'))['embed'].title == '🧠 Question of the day'
    assert asyncio.run(press('play:bingo'))['embed'].title.startswith('🎱 Repertory bingo')
    assert asyncio.run(press('play:kernels'))['embed'].title == '🍿 Your kernels: 0'
