"""Screening notes (R10f): off until a club admin turns them on; quick tags
about the screening (print, sound, crowd, Q&A) from members who checked in,
shown on the screening, in the feed and summed up on theatre pages."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    """Notes Club: Ana (admin), Bo, Vi (read-only); Out is in another club.
    Ana, Bo and Out went to a 35mm screening at AFI two days ago."""
    from app import app, db, Attendance, Group, GroupMembership, Movie, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        g, other = Group(name='Notes Club', slug='notes-club', is_public=False), Group(name='Other', slug='notes-other')
        us = {n: User(name=n, email=f'{n.lower()}@n.test', is_active=True) for n in ('Ana', 'Bo', 'Vi', 'Out')}
        db.session.add_all([g, other, *us.values()])
        db.session.flush()
        for n, role in (('Ana', 'admin'), ('Bo', 'member'), ('Vi', 'viewer')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g.id, status='active', role=role))
        db.session.add(GroupMembership(user_id=us['Out'].id, group_id=other.id, status='active'))
        m = Movie(title='NOTED FILM')
        db.session.add(m)
        db.session.flush()
        afi = Theatre.query.filter_by(slug='afi').first()
        s = Showtime(movie_id=m.id, theatre_id=afi.id, format_label='35mm', start_time=datetime.now() - timedelta(days=2))
        db.session.add(s)
        db.session.flush()
        for n in ('Ana', 'Bo', 'Out'):
            db.session.add(Attendance(user_id=us[n].id, showtime_id=s.id, status='went', source='site',
                                      answered_at=datetime.utcnow()))
        db.session.commit()
        return {**{n: u.id for n, u in us.items()}, 'G': g.id, 'OTHER': other.id, 'slug': g.slug, 'S': s.id}


def note(c, who, tag, group='G'):
    return client(c[who]).post('/api/notes', json={'group_id': c[group], 'showtime_id': c['S'], 'tag': tag})


def view(c, who='Ana'):
    return client(c[who]).get('/api/notes', query_string={'group_id': c['G'], 'showtime_id': c['S']}).json


def turn_on(c, group_slug=None, admin='Ana'):
    r = client(c[admin]).put(f"/api/groups/{group_slug or c['slug']}", json={'notes_enabled': True})
    assert r.status_code == 200 and r.json['notes'] == {'enabled': True}


def test_notes_start_off_and_only_admins_switch_them(club):
    assert view(club) == {'enabled': False}
    assert 'off' in note(club, 'Ana', 'print').json['error']
    assert client(club['Bo']).put(f"/api/groups/{club['slug']}", json={'notes_enabled': True}).status_code == 403
    turn_on(club)
    v = view(club)
    assert v['enabled'] and v['can_add'] and [t['key'] for t in v['tags']][:2] == ['print', 'worn']


def test_only_people_who_were_there_add_notes(club):
    from app import app, db, Attendance
    turn_on(club)
    with app.app_context():
        Attendance.query.filter_by(user_id=club['Bo']).delete()
        db.session.commit()
    assert 'Check in' in note(club, 'Bo', 'print').json['error'] and view(club, 'Bo')['can_add'] is False
    assert 'members' in note(club, 'Vi', 'print').json['error']
    assert 'Pick one' in note(club, 'Ana', 'nonsense').json['error']


def test_tags_toggle_and_count_the_clubs_members(club):
    turn_on(club)
    note(club, 'Ana', 'print')
    note(club, 'Ana', 'packed')
    v = note(club, 'Bo', 'print').json
    tags = {t['key']: t for t in v['tags']}
    assert tags['print']['count'] == 2 and tags['print']['mine'] and tags['packed']['count'] == 1 and not tags['packed']['mine']
    assert {t['key']: t['count'] for t in note(club, 'Bo', 'print').json['tags']}['print'] == 1   # tapped again: removed
    from app import app, db, ScreeningNote
    with app.app_context():                                                                 # Out was there too, in another club
        db.session.add(ScreeningNote(user_id=club['Out'], showtime_id=club['S'], tag='print'))
        db.session.commit()
    assert {t['key']: t['count'] for t in view(club)['tags']}['print'] == 1                # only this club's members count


def test_notes_show_in_the_feed(club):
    turn_on(club)
    note(club, 'Ana', 'print')
    note(club, 'Bo', 'print')
    note(club, 'Bo', 'qa')
    cards = client(club['Ana']).get('/api/feed', query_string={'group_id': club['G']}).json['cards']
    card = next(c for c in cards if c.get('showtime', {}).get('id') == club['S'])
    assert [(t['key'], t['count']) for t in card['notes']] == [('print', 2), ('qa', 1)]
    assert any(a['kind'] == 'note' for a in card['activity'])


def test_theatre_pages_sum_up_what_members_say(club):
    url = '/api/theatres/afi/notes'
    assert client(club['Ana']).get(url, query_string={'group_id': club['G']}).json == {'enabled': False}
    turn_on(club)
    note(club, 'Ana', 'print')
    note(club, 'Bo', 'sound')
    note(club, 'Bo', 'print')
    t = client(club['Ana']).get(url, query_string={'group_id': club['G']}).json
    assert t['screenings'] == 1 and [(x['key'], x['count']) for x in t['tags']] == [('print', 2), ('sound', 1)]
    assert not any(x['heads_up'] for x in t['tags'])
    [r] = t['recent']
    assert r['screening']['title'] == 'NOTED FILM' and [(x['key'], x['count']) for x in r['tags']] == [('print', 2), ('sound', 1)]
    note(club, 'Ana', 'sound_trouble')
    t = client(club['Ana']).get(url, query_string={'group_id': club['G']}).json
    assert {x['key']: x['heads_up'] for x in t['tags']}['sound_trouble'] is True
    assert client(club['Out']).get(url, query_string={'group_id': club['G']}).status_code == 403
