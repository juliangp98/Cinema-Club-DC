"""Quiz games in Discord (R15): /games lists the ones the club has on, each
with a Play button; a round plays out privately with its buttons."""
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
    run(bot.games_cmd.callback(it))
    assert it.last[1] == bot.QUIZ_OFF_MSG


def test_a_higher_or_lower_round_with_buttons(bot):
    from app import app, db, Group, QuizRound
    with app.app_context():
        slug = db.session.get(Group, 1).slug
    assert client(bot.test_admin).put(f'/api/groups/{slug}', json={'quizzes': {'higher_lower': True}}).status_code == 200
    it = FakeInteraction(uid=9611, name='ana')
    run(bot.games_cmd.callback(it))
    kind, _, kw = it.last
    assert kind == 'followup' and kw['ephemeral'] and kw['embed'].title == '🎮 Quiz games'
    [play] = items_of(kw['view'])
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
