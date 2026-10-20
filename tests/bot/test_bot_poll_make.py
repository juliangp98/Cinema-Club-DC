"""/poll make end to end: an AI draft previewed privately, Create now (once),
organizers only."""
import asyncio
import json
import re
import types

import pytest

from helpers import all_linked_present, items_of, patch_bot_api, setup_db

DRAFT = {'title': 'Spookiest picks', 'poll_type': 'standard', 'scoring_mode': 'ranked',
         'categories': [{'title': 'Scariest', 'options': ['Hausu', 'Suspiria', 'The Thing']}], 'notes': ''}


class Interaction:
    def __init__(self, uid):
        self.log, self.guild_id, self.channel_id = [], None, 1
        self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', display_avatar=None)
        outer = self

        class R:
            async def defer(self, **k):
                outer.log.append(('defer', k))

        class F:
            async def send(self, content=None, embed=None, view=None, ephemeral=False, **k):
                outer.log.append(('send', content, embed, view, ephemeral))
        self.response, self.followup = R(), F()

    @property
    def last(self):
        return self.log[-1]


@pytest.fixture
def bot():
    """An organizer (Discord 6201) and a member (6202); the AI drafts DRAFT."""
    import ai
    from app import app, db, User, GroupMembership
    from fake_groq import Fake
    setup_db()
    with app.app_context():
        for did, name, role in (('6201', 'Orga', 'organizer'), ('6202', 'Memb', 'member')):
            u = User(discord_user_id=did, name=name, is_active=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role=role))
        db.session.commit()
    ai._client = Fake(['qwen/qwen3-32b'])
    ai._client.reply = lambda m, msgs, kw: 'ok' if msgs[-1]['content'].endswith('weekend?') else json.dumps(DRAFT)
    b = patch_bot_api()
    all_linked_present()
    return b


def make_draft(bot):
    it = Interaction(6201)
    asyncio.run(bot.poll_cmd.callback(it, request='spookiest Halloween movies'))
    return it.last


def test_organizers_get_a_private_draft_preview(bot):
    _, _, embed, view, ephemeral = make_draft(bot)
    assert ephemeral and embed.title == '📝 Draft: Spookiest picks'
    assert embed.fields[0].name == 'Scariest' and 'Hausu' in embed.fields[0].value and 'not posted yet' in embed.footer.text
    create, editor = items_of(view)[:2]
    assert create.custom_id.startswith('polldraft:create:')
    assert editor.url.endswith('/polls/new?draft=' + create.custom_id.split(':')[-1])


def test_create_now_opens_the_poll_once(bot):
    from app import app, Poll, DiscordPost
    create = items_of(make_draft(bot)[3])[0]
    btn = asyncio.run(bot.DraftCreateButton.from_custom_id(None, None, re.fullmatch(r'polldraft:create:(?P<id>[0-9]+)', create.custom_id)))
    it = Interaction(6201)
    asyncio.run(btn.callback(it))
    with app.app_context():
        p = Poll.query.filter_by(title='Spookiest picks').first()
        assert p.status == 'open' and DiscordPost.query.filter_by(kind='poll', ref_id=p.id).first()    # announced
    assert 'is open' in it.last[1]
    again = Interaction(6201)
    asyncio.run(btn.callback(again))
    assert 'Already created' in again.last[1]


def test_members_are_told_its_for_organizers(bot):
    it = Interaction(6202)
    asyncio.run(bot.poll_cmd.callback(it, request='comfort movies'))
    assert 'organizers and admins' in it.last[1]
