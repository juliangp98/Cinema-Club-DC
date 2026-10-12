"""/compare in Discord: the real slash command against the backend. (What
compare finds is tested in backend/test_compare.py; this is the bot's side.)"""
import asyncio
import types

import pytest

from helpers import patch_bot_api, seed_compare_pair


class Interaction:
    """Records (kind, ephemeral, content, embed)."""
    def __init__(self, uid):
        self.log, self.guild_id, self.channel_id = [], None, 1
        self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', mention=f'<@{uid}>',
                                          display_avatar=types.SimpleNamespace(url='https://cdn/x.png'))
        outer = self

        class R:
            async def defer(self, ephemeral=False, **k):
                outer.log.append(('defer', ephemeral, None, None))

        class F:
            async def send(self, content=None, ephemeral=False, embed=None, **k):
                outer.log.append(('followup', ephemeral, content, embed))
        self.response, self.followup = R(), F()


def member(uid, name):
    return types.SimpleNamespace(id=uid, display_name=name)


def compare(bot, uid, other):
    it = Interaction(uid)
    asyncio.run(bot.compare.callback(it, other))
    return it


@pytest.fixture
def bot():
    """Bo (7702) and Ana (7701), as in backend/test_compare.py; Bo said he
    missed the screening they'd both been going to."""
    from app import app, db, Attendance
    ids = seed_compare_pair()
    with app.app_context():
        db.session.add(Attendance(user_id=ids['bo'], showtime_id=ids['together'], status='missed', source='site'))
        db.session.commit()
    return patch_bot_api()


def test_compare_is_a_private_card_for_the_pair(bot):
    it = compare(bot, 7702, member(7701, 'Ana'))
    kind, ephemeral, _, emb = it.log[-1]
    assert it.log[0] == ('defer', True, None, None) and kind == 'followup' and ephemeral
    assert emb.title == '🤝 You & Ana'
    fields = {f.name: f.value for f in emb.fields}
    assert 'SINNERS' in fields['🎯 You both want to see'] and 'next:' in fields['🎯 You both want to see']
    assert 'SIRÂT' in fields["🎟️ You're both going"]
    assert 'HAMNET' in fields["👀 Ana's going to something on your watchlist"]
    assert 'VERTIGO' in fields["📣 You're going to something on Ana's watchlist"]
    assert 'KHARTOUM' not in str(fields)                         # her private club's screening
    assert '🍿 Seen together' not in fields                      # Bo missed it


def test_comparing_with_yourself_or_a_stranger(bot):
    assert compare(bot, 7702, member(7702, 'Bo')).log[-1][2] == 'Pick someone other than yourself.'
    assert compare(bot, 7702, member(9999, 'Zed')).log[-1][2] == "Zed hasn't used Cinema Club yet."


def test_nothing_in_common_gets_a_hint():
    import embeds
    empty = embeds.compare_embed({'name': 'Cal', 'both_want': [], 'both_going': [], 'they_go_you_want': [],
                                  'you_go_they_want': [], 'seen_together': []})
    assert not empty.fields and '/watch' in empty.description
