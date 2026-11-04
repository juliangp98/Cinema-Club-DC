"""Quiz games in Discord (R15): /play has a button for each one the club has
on; a round plays out privately with its buttons."""
import asyncio
import json
import re

import pytest

from helpers import FakeInteraction, all_linked_present, client, items_of, patch_bot_api, setup_db


@pytest.fixture
def bot():
    """Ana (9611) in the Discord club (group 1, our films only); Adm its admin."""
    from app import app, db, Group, GroupMembership, User
    setup_db()
    with app.app_context():
        db.session.get(Group, 1).trivia_source = 'local'
        ana = User(name='Ana', discord_user_id='9611', is_active=True)
        adm = User(name='Adm', email='adm@qz.test', is_active=True)
        db.session.add_all([ana, adm])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active'))
        db.session.add(GroupMembership(user_id=adm.id, group_id=1, status='active', role='admin'))
        db.session.commit()
        b = patch_bot_api()
        b.test_admin = adm.id
    all_linked_present()
    return b


def run(coro):
    return asyncio.run(coro)


def test_off_until_the_club_turns_one_on(bot):
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_today.callback(it))
    assert not [b for b in items_of(it.last[2]['view']) if (b.custom_id or '').startswith('quiz:')]
    assert 'Quiz games' not in it.last[2]['embed'].description


def test_a_higher_or_lower_round_with_buttons(bot):
    from app import app, db, Group, QuizRound
    with app.app_context():
        slug = db.session.get(Group, 1).slug
    assert client(bot.test_admin).put(f'/api/groups/{slug}', json={'quizzes': {'higher_lower': True}}).status_code == 200
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_today.callback(it))
    kind, _, kw = it.last
    assert kind == 'followup' and kw['ephemeral'] and '🎮 Quiz games: ↕️ Higher or lower — 5 🍿 left to earn today' in kw['embed'].description
    [play] = [b for b in items_of(kw['view']) if (b.custom_id or '').startswith('quiz:')]
    assert play.custom_id == 'quiz:start:higher_lower' and play.label == '↕️ Higher or lower'

    start = run(bot.QuizButton.from_custom_id(None, play, re.fullmatch(bot.QuizButton.__discord_ui_compiled_template__.pattern,
                                                                         play.custom_id)))
    it2 = FakeInteraction(uid=9611, name='ana')
    run(start.callback(it2))
    assert it2.sent[0][0] == 'defer'                                          # answered first
    _, _, kw = it2.last
    labels = [b.label for b in items_of(kw['view'])]
    assert labels[0].startswith('⬅️ Before ') and labels[1].startswith('After ')
    assert 'come out before or after' in kw['embed'].description

    with app.app_context():
        r = QuizRound.query.filter_by(kind='higher_lower').first()
        chain = json.loads(r.state_json)['chain']
    right = 'before' if chain[-1]['year'] < chain[-2]['year'] else 'after'
    button = next(b for b in items_of(kw['view']) if b.custom_id.endswith(f':{right}'))
    answer = run(bot.QuizButton.from_custom_id(None, button, re.fullmatch(bot.QuizButton.__discord_ui_compiled_template__.pattern,
                                                                            button.custom_id)))
    it3 = FakeInteraction(uid=9611, name='ana')
    run(answer.callback(it3))
    kind, _, kw = it3.last
    assert kind == 'edit' and kw['embed'].description.startswith('✅ Right! +1 🍿')


def test_a_still_in_discord():
    """The still is the embed's picture (the site's cropped copy); Zoom out is a button until the last step."""
    import embeds
    import bot as b
    r = {'id': 7, 'kind': 'still', 'label': 'Guess the still', 'emoji': '🖼️', 'done': False, 'score': 0, 'earned': 0, 'each': 3,
         'by_step': True, 'left_today': 5, 'last': None, 'image': '/api/quizzes/still/7/abc-1.jpg', 'step': 1, 'steps': 3,
         'worth': 3, 'options': ['Vertigo (1958)', 'Psycho (1960)', 'The Birds (1963)', 'Rear Window (1954)']}
    e = embeds.quiz_round_embed(r)
    assert e.image.url.endswith('/api/quizzes/still/7/abc-1.jpg') and e.footer.text.startswith('worth 3 🍿 now')
    async def labels(x):                                                      # views need a running loop
        return [i.label for i in items_of(b.quiz_round_view(x))]
    assert run(labels(r)) == ['A', 'B', 'C', 'D', '🔍 Zoom out']
    assert '🔍 Zoom out' not in run(labels({**r, 'step': 3}))


def test_play_game_goes_straight_into_one(bot):
    """/play solo game: a round of that game at once (no hub, no button); a
    game the club has off says so. /play kernels: yours."""
    from discord import app_commands
    from app import app, db, Group
    pick = lambda v: app_commands.Choice(name=v, value=v)
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_solo.callback(it, game=pick('higher_lower')))
    assert it.sent[0][0] == 'defer' and 'embed' not in it.last[2]                     # off in this club: no round
    with app.app_context():
        slug = db.session.get(Group, 1).slug
    client(bot.test_admin).put(f'/api/groups/{slug}', json={'quizzes': {'higher_lower': True}})
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_solo.callback(it, game=pick('higher_lower')))
    kind, _, kw = it.last
    assert kind == 'followup' and kw['ephemeral'] and 'come out before or after' in kw['embed'].description
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_kernels.callback(it))
    assert it.last[2]['embed'].title and it.last[2]['ephemeral']                        # your kernels, privately


def test_higher_or_lower_in_a_decade_in_discord(bot, monkeypatch):
    """/play solo decade: suggests the club's decades; the run stays in it, and Play again keeps it.
    A decade it can't play says so and runs classic."""
    import quizzes
    from discord import app_commands
    from app import app, db, Group, QuizRound
    monkeypatch.setattr(quizzes, 'DECADE_FILMS', 2)
    with app.app_context():
        slug = db.session.get(Group, 1).slug
    client(bot.test_admin).put(f'/api/groups/{slug}', json={'quizzes': {'higher_lower': True}})
    choices = run(bot.decade_autocomplete(FakeInteraction(uid=9611, name='ana'), ''))
    assert choices and all(c.name.startswith('The ') and c.name.endswith('0s') for c in choices)
    decade = int(choices[0].value)
    hl = app_commands.Choice(name='Higher or lower', value='higher_lower')
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_solo.callback(it, game=hl, decade=str(decade)))
    _, note, kw = it.last
    assert note is None and f'in the {decade}s' in kw['embed'].description
    with app.app_context():
        r = QuizRound.query.filter_by(kind='higher_lower', status='open').one()
        chain = json.loads(r.state_json)['chain']
    assert all(decade <= f['year'] < decade + 10 for f in chain)
    miss = 'after' if chain[-1]['year'] < chain[-2]['year'] else 'before'
    button = next(b for b in items_of(kw['view']) if b.custom_id.endswith(f':{miss}'))
    it = FakeInteraction(uid=9611, name='ana')
    run(run(bot.QuizButton.from_custom_id(None, button, re.fullmatch(bot.QuizButton.__discord_ui_compiled_template__.pattern,
                                                                       button.custom_id))).callback(it))
    again = next(b for b in items_of(it.last[2]['view']) if b.label == '🔁 Play again')
    assert again.custom_id == f'quiz:start:higher_lower:{decade}'
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.play_solo.callback(it, game=hl, decade='1890'))
    assert 'Not in the 1890s' in it.last[1] and 'in the 1890s' not in it.last[2]['embed'].description
