"""/club in Discord (7e): the club at a glance — members in the server by
name (the rest counted), its theatres, and the month's numbers, with medals
only for real places."""
import asyncio
from datetime import datetime, timedelta

import pytest

from helpers import FakeInteraction, client, patch_bot_api, setup_db, H


@pytest.fixture
def bot():
    """Ana (in the server) and Bo (site only) both checked in to the same screening this month."""
    from app import app, db, Attendance, GroupMembership, Movie, RSVP, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        ana = User(name='Ana', discord_user_id='9201', is_active=True)
        bo = User(name='Bo', email='bo@club.test', is_active=True)
        m = Movie(title='CLUB NIGHT')
        db.session.add_all([ana, bo, m])
        db.session.flush()
        s = Showtime(movie_id=m.id, theatre_id=Theatre.query.filter_by(slug='afi').first().id,
                     start_time=max(datetime.now() - timedelta(hours=2), datetime.now().replace(day=1, hour=0, minute=1)))
        db.session.add(s)
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
            db.session.add(RSVP(user_id=u.id, showtime_id=s.id, group_id=1, status='going'))
            db.session.add(Attendance(user_id=u.id, showtime_id=s.id, status='went', source='site', answered_at=datetime.utcnow()))
        db.session.commit()
    assert client().post('/api/internal/discord/members', json={'full': True, 'ids': ['9201']}, headers=H).status_code == 200
    return patch_bot_api()


def test_the_club_at_a_glance(bot):
    it = FakeInteraction(uid=9201, name='ana')
    asyncio.run(bot.club_cmd.callback(it))
    kind, _, kw = it.last
    e = kw['embed']
    assert kind == 'followup' and not kw.get('ephemeral') and e.url.endswith('/club')
    fields = {f.name: f.value for f in e.fields}
    members = next(v for n, v in fields.items() if n.startswith('👥'))
    assert 'Ana' in members and 'Bo' not in members and 'on the site' in members      # Bo isn't in the server
    month = next(v for n, v in fields.items() if n.startswith('📊'))
    assert '1 night out together' in month and '🥇 Ana' in month and 'Bo' not in month
    assert [b.label for b in kw['view'].children] == ['Club page', 'Leaderboard']
