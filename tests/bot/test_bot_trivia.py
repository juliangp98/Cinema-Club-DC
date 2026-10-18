"""Daily trivia in Discord (R10d): /trivia (privately), A–D buttons that
answer privately (one try). The daily #movies post is test_bot_game_posts.py."""
import asyncio
import re
import types
from datetime import datetime

import pytest

from helpers import FakeInteraction, all_linked_present, client, items_of, patch_bot_api, setup_db


@pytest.fixture
def bot():
    """Ana (9601) is a member of the Discord club (group 1); Adm is its admin."""
    from app import app, db, GroupMembership, User
    setup_db()
    with app.app_context():
        ana = User(name='Ana', discord_user_id='9601', is_active=True)
        adm = User(name='Adm', email='adm@t.test', is_active=True)
        db.session.add_all([ana, adm])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active'))
        db.session.add(GroupMembership(user_id=adm.id, group_id=1, status='active', role='admin'))
        db.session.commit()
        b = patch_bot_api()
        b.test_admin = adm.id
    all_linked_present()
    return b


def switch(bot, **on):
    from app import app, db, Group
    with app.app_context():
        slug = db.session.get(Group, 1).slug
    assert client(bot.test_admin).put(f'/api/groups/{slug}', json=on).status_code == 200


def run(coro):
    return asyncio.run(coro)


def test_trivia_is_off_until_the_club_turns_it_on(bot):
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    assert it.last[1] == bot.TRIVIA_OFF_MSG


def test_answering_privately_once(bot):
    switch(bot, trivia_enabled=True)
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    _, _, kw = it.last
    assert kw['ephemeral'] is True and kw['embed'].title == '🧠 Question of the day'
    buttons = items_of(kw['view'])
    assert [b.label for b in buttons] == ['A', 'B', 'C', 'D']
    assert all(re.fullmatch(r'trivia:\d+:[0-3]', b.custom_id) for b in buttons)

    async def press(custom_id):
        m = re.fullmatch(bot.TriviaButton.__discord_ui_compiled_template__, custom_id)
        btn = await bot.TriviaButton.from_custom_id(None, None, m)
        it = FakeInteraction(uid=9601, name='ana')
        await btn.callback(it)
        return it
    first = run(press(buttons[0].custom_id))
    assert first.last[2]['ephemeral'] is True and first.last[1].startswith(('✅ Right', '❌ Not quite'))
    again = run(press(buttons[1].custom_id))
    assert 'already answered' in again.last[1]
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    assert it.last[1].startswith(('✅', '❌'))                                     # /trivia now shows your result


def test_kernels_explains_trivia_when_its_on(bot):
    switch(bot, trivia_enabled=True)
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.kernels_cmd.callback(it))
    how = {f.name: f.value for f in it.last[2]['embed'].fields}['How to earn']
    assert 'Trivia question of the day: **+1** easy · **+2** medium · **+3** hard' in how and 'Anytime' not in how
    switch(bot, trivia_anytime=True)
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.kernels_cmd.callback(it))
    assert 'Anytime trivia: **+1** easy · **+1** medium · **+2** hard each, up to 5 a day' in {f.name: f.value for f in it.last[2]['embed'].fields}['How to earn']


def press(bot, custom_id, template):
    async def go():
        m = re.fullmatch(template.__discord_ui_compiled_template__, custom_id)
        btn = await template.from_custom_id(None, None, m)
        it = FakeInteraction(uid=9601, name='ana')
        await btn.callback(it)
        return it
    return run(go())


def test_anytime_questions_in_discord(bot):
    switch(bot, trivia_enabled=True, trivia_anytime=True)
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    daily = items_of(it.last[2]['view'])
    answered = press(bot, daily[0].custom_id, bot.TriviaButton)                 # today's first…
    more = items_of(answered.last[2]['view'])
    assert [b.custom_id for b in more] == ['trivia:more']                       # …then "🎲 Another one"
    got = press(bot, 'trivia:more', bot.TriviaMoreButton)
    _, _, kw = got.last
    assert kw['ephemeral'] is True and kw['embed'].title == '🎲 Anytime trivia' and len(items_of(kw['view'])) == 4
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    assert it.last[2]['embed'].title == '🎲 Anytime trivia'                     # /trivia hands back the one you're on
    assert items_of(it.last[2]['view'])[0].custom_id == items_of(kw['view'])[0].custom_id


def test_without_anytime_trivia_waits_for_tomorrow(bot):
    switch(bot, trivia_enabled=True)
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    answered = press(bot, items_of(it.last[2]['view'])[0].custom_id, bot.TriviaButton)
    assert 'view' not in answered.last[2]                                       # no "Another one"
    it = FakeInteraction(uid=9601, name='ana')
    run(bot.trivia_cmd.callback(it))
    assert 'Anytime questions are off' in it.last[1]
