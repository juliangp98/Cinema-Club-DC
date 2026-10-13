"""Screening notes (R10f), off until a club admin turns them on: quick tags
about the screening itself — the print, the sound, the crowd, the Q&A —
from members who checked in. Letterboxd covers the film; these cover the
night. They show on the screening (drawer and feed card), in the club feed,
and summed up on theatre pages for the club's members. Nobody is sent
anything."""
from datetime import datetime, timedelta

TAGS = {                     # key: (emoji, label)
    'print': ('🎞️', 'Gorgeous print'),
    'worn': ('📼', 'Worn print'),
    'sound': ('🔊', 'Great sound'),
    'sound_trouble': ('🔇', 'Sound trouble'),
    'projection': ('⚠️', 'Projection trouble'),
    'packed': ('👥', 'Packed house'),
    'crowd': ('😂', 'Great crowd'),
    'roomy': ('🪑', 'Plenty of seats'),
    'qa': ('🎤', 'Great Q&A or intro'),
}
THEATRE_DAYS = 180


def _members(group_id):
    from app import GroupMembership
    return {m.user_id for m in GroupMembership.query.filter_by(group_id=group_id, status='active')}


def counts(group_id, showtime_ids, member_ids=None):
    """{showtime_id: {tag: count}} from the club's members' notes."""
    from app import ScreeningNote
    member_ids = member_ids if member_ids is not None else _members(group_id)
    out = {}
    if not showtime_ids or not member_ids:
        return out
    for n in ScreeningNote.query.filter(ScreeningNote.showtime_id.in_(list(showtime_ids)),
                                        ScreeningNote.user_id.in_(list(member_ids))):
        out.setdefault(n.showtime_id, {}).setdefault(n.tag, 0)
        out[n.showtime_id][n.tag] += 1
    return out


def tag_list(tally, mine=()):
    """[{key, emoji, label, count, mine}] in TAGS order (all tags, or only those used)."""
    return [{'key': k, 'emoji': e, 'label': label, 'count': tally.get(k, 0), 'mine': k in mine}
            for k, (e, label) in TAGS.items()]


def view(group, user, showtime_id):
    """A screening's notes for the drawer: every tag with its count and
    whether it's yours, and whether you can add any (you checked in)."""
    from app import Attendance, ScreeningNote
    if not group or not group.notes_enabled:
        return {'enabled': False}
    tally = counts(group.id, [showtime_id]).get(showtime_id, {})
    mine = {n.tag for n in ScreeningNote.query.filter_by(user_id=user.id, showtime_id=showtime_id)}
    went = Attendance.query.filter_by(user_id=user.id, showtime_id=showtime_id, status='went').first() is not None
    return {'enabled': True, 'can_add': went, 'tags': tag_list(tally, mine)}


def toggle(group, user, showtime_id, tag):
    """Add or remove one of your tags on a screening you checked in to.
    Returns (view, error)."""
    from app import db, Attendance, ScreeningNote, require_role
    if not group or not group.notes_enabled:
        return None, 'Screening notes are off for this club.'
    _, err = require_role(user, group.id, 'member')
    if err:
        return None, 'Only club members can add notes.'
    if tag not in TAGS:
        return None, 'Pick one of the notes.'
    if not Attendance.query.filter_by(user_id=user.id, showtime_id=showtime_id, status='went').first():
        return None, 'Check in ("Went") first — notes are from people who were there.'
    row = ScreeningNote.query.filter_by(user_id=user.id, showtime_id=showtime_id, tag=tag).first()
    if row:
        db.session.delete(row)
    else:
        db.session.add(ScreeningNote(user_id=user.id, showtime_id=showtime_id, tag=tag))
    db.session.commit()
    return view(group, user, showtime_id), None


def card(group, showtime_id, member_ids):
    """The tags a feed card shows (only ones used, most first)."""
    if not group or not group.notes_enabled:
        return []
    tally = counts(group.id, [showtime_id], member_ids).get(showtime_id, {})
    return sorted([t for t in tag_list(tally) if t['count']], key=lambda t: -t['count'])


def feed_events(group_id, member_ids, since):
    """('note', 's<showtime>', when, uid, tag) for the club feed."""
    from app import ScreeningNote
    if not member_ids:
        return []
    return [('note', f's{n.showtime_id}', n.created_at, n.user_id, n.tag)
            for n in ScreeningNote.query.filter(ScreeningNote.user_id.in_(list(member_ids)),
                                                ScreeningNote.created_at >= since)]


def theatre(group, theatre_id, now=None):
    """What the club's members say about a theatre's screenings lately:
    {'screenings': n, 'tags': [{key, emoji, label, count}] (used ones, most first)}."""
    from app import db, ScreeningNote, Showtime
    if not group or not group.notes_enabled:
        return None
    now = now or datetime.now()
    members = _members(group.id)
    if not members:
        return {'screenings': 0, 'tags': []}
    rows = (db.session.query(ScreeningNote.tag, ScreeningNote.showtime_id)
            .join(Showtime, ScreeningNote.showtime_id == Showtime.id)
            .filter(Showtime.theatre_id == theatre_id, Showtime.start_time >= now - timedelta(days=THEATRE_DAYS),
                    ScreeningNote.user_id.in_(list(members))).all())
    tally = {}
    for tag, _ in rows:
        tally[tag] = tally.get(tag, 0) + 1
    return {'screenings': len({sid for _, sid in rows}),
            'tags': sorted([t for t in tag_list(tally) if t['count']], key=lambda t: -t['count'])}
