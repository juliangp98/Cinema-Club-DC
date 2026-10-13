"""What the club games post in Discord, and who hears about them (R14).

Club posts in #movies — each its own choice in Club settings, all off until
an admin picks otherwise (Group.trivia_post / bingo_card_post / bingo_wins_post):
  · the question of the day (after 11 AM) and the month's bingo card:
    never | ask (an admin OKs it first — on the site, or with the buttons in
    the DM the bot sends admins who take DMs) | always
  · bingo wins: never | always — naming the winner only if their Sharing to
    Discord says Always for "My game wins" (else "Someone got bingo")
Unapproved posts lapse: the question at 10 PM, the card when its month ends.
Before saying yes, an admin can swap the question (until someone answers it)
or reshuffle the card.

Personal notices (notify.TYPES, each person's own switch): the question of
the day, yesterday's answer, a new card, your bingo, and — for admins — a
post waiting for their OK.

tick() does all of it and is safe to run any number of times: after each
scrape run, and (at most every few minutes) when the bot asks what to post.
"""
import json
from datetime import datetime, timedelta

SETTINGS = {'trivia': 'trivia_post', 'bingo_card': 'bingo_card_post', 'bingo_win': 'bingo_wins_post'}
MODES = {'trivia': ('never', 'ask', 'always'), 'bingo_card': ('never', 'ask', 'always'), 'bingo_win': ('never', 'always')}
TRIVIA_HOURS = (11, 22)                 # the question of the day posts (and is announced) in this window
WIN_FRESH = timedelta(hours=24)         # a win older than this when first seen isn't news
TICK_EVERY = timedelta(minutes=5)       # how often the bot's checks run tick()


def _local_now():
    """The club's clock (tests set it)."""
    return datetime.now()


def mode(group, kind):
    """A club's choice for one post — 'never' when the game itself is off."""
    on = group.trivia_enabled if kind == 'trivia' else group.bingo_enabled
    value = getattr(group, SETTINGS[kind]) or 'never'
    return value if on and value in MODES[kind] else 'never'


def _admins(group):
    from app import GroupMembership
    return [m.user for m in GroupMembership.query.filter_by(group_id=group.id, status='active', role='admin') if m.user]


def _players(group):
    """Active members who can play (read-only members can't)."""
    from app import GroupMembership
    return [m.user for m in GroupMembership.query.filter_by(group_id=group.id, status='active')
            if m.user and m.user.is_active and m.role != 'viewer']


def _told(kind, since, key=None):
    """{user_id} already sent `kind` since `since` (matching payload `key` if given)."""
    from app import Notification
    out = set()
    for n in Notification.query.filter(Notification.kind == kind, Notification.created_at >= since):
        if key is None or all(json.loads(n.payload_json or '{}').get(k) == v for k, v in key.items()):
            out.add(n.user_id)
    return out


def _notify(users, kind, payload, type_=None):
    import notify
    from app import db, Notification
    for u in users:
        if notify.wants(u, type_ or kind):
            notify._make(db, Notification, u, kind, None, None, payload, ready=True)


def _post(group, kind, ref, payload=None):
    """The GamePost for (group, kind, ref), made on first sight: approved when
    the club says Always; waiting (and its admins told) when it says Ask."""
    from sqlalchemy.exc import IntegrityError
    from app import db, GamePost
    post = GamePost.query.filter_by(group_id=group.id, kind=kind, ref=ref).first()
    if post:
        return post
    m = mode(group, kind)
    post = GamePost(group_id=group.id, kind=kind, ref=ref, status='approved' if m == 'always' else 'waiting',
                    payload_json=json.dumps(payload) if payload else None)
    db.session.add(post)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return GamePost.query.filter_by(group_id=group.id, kind=kind, ref=ref).first()
    if post.status == 'waiting':
        import bingo
        label = bingo.month_bounds(ref)[0].strftime('%B') if kind == 'bingo_card' else None
        _notify(_admins(group), 'game_review', {'post_id': post.id, 'post_kind': kind, 'month_label': label,
                                                'group': group.slug}, type_='reviews')
    return post


def _trivia(group, now):
    import trivia
    from app import TriviaAnswer, TriviaQuestion
    if not group.trivia_enabled or not TRIVIA_HOURS[0] <= now.hour < TRIVIA_HOURS[1]:
        return
    q = trivia.question_for(group)
    if not q:
        return
    if mode(group, 'trivia') != 'never':
        _post(group, 'trivia', q.day.isoformat())
    day = q.day.isoformat()
    since = datetime.utcnow() - timedelta(days=2)
    players = _players(group)
    told = _told('trivia_daily', since, {'day': day, 'group': group.slug})
    _notify([u for u in players if u.id not in told], 'trivia_daily', {'day': day, 'group': group.slug, 'prompt': q.prompt})
    prev = TriviaQuestion.query.filter_by(group_id=group.id, slot='daily', day=q.day - timedelta(days=1)).first()
    if prev:
        answers = {a.user_id: a for a in TriviaAnswer.query.filter_by(question_id=prev.id)}
        told = _told('trivia_result', since, {'day': prev.day.isoformat(), 'group': group.slug})
        options = json.loads(prev.options_json)
        for u in players:
            if u.id in told:
                continue
            a = answers.get(u.id)
            _notify([u], 'trivia_result', {'day': prev.day.isoformat(), 'group': group.slug, 'prompt': prev.prompt,
                                           'answer': options[prev.answer],
                                           'you': None if not a else 'right' if a.correct else 'wrong',
                                           'answered': len(answers), 'correct': sum(x.correct for x in answers.values())})


def _bingo(group, now):
    import bingo
    from app import on_discord, share_prefs
    if not group.bingo_enabled:
        return
    card = bingo.card_for(group)
    start = bingo.month_bounds(card.month)[0]
    label = start.strftime('%B %Y')
    if mode(group, 'bingo_card') != 'never':
        _post(group, 'bingo_card', card.month)
    since = datetime.utcnow() - timedelta(days=40)
    told = _told('bingo_card', since, {'month': card.month, 'group': group.slug})
    names = [bingo.SQUARES[k][1] for k in json.loads(card.squares_json)]
    players = _players(group)
    _notify([u for u in players if u.id not in told], 'bingo_card',
            {'month': card.month, 'group': group.slug, 'month_label': label, 'squares': names})
    rules = {'line': bingo.LINE_KERNELS, 'full': bingo.FULL_KERNELS}
    for u in players:
        p = bingo.progress(card, u.id)
        for which in ('line', 'full'):
            at = p[f'{which}_at']
            if not at or at < datetime.utcnow() - WIN_FRESH:
                continue
            key = {'month': card.month, 'group': group.slug, 'which': which}
            if u.id not in _told('bingo_win', since, key):
                _notify([u], 'bingo_win', {**key, 'month_label': label, 'kernels': rules[which]})
            if mode(group, 'bingo_win') == 'always':
                _post(group, 'bingo_win', f'{card.month}:{u.id}:{which}',
                      {'user_id': u.id, 'which': which,
                       'named': share_prefs(u)['games'] == 'always' and on_discord(u)})


def _expire(group, now):
    import bingo
    from app import GamePost
    today, month = now.date().isoformat(), bingo.month_of()
    for post in GamePost.query.filter(GamePost.group_id == group.id, GamePost.status.in_(('waiting', 'approved'))):
        late_question = post.kind == 'trivia' and (post.ref < today or (post.status == 'waiting' and now.hour >= TRIVIA_HOURS[1]))
        if late_question or (post.kind == 'bingo_card' and post.ref < month):
            post.status = 'expired'


def tick(now=None):
    """Everything due for every club with a game on. Returns how many clubs.
    Works from a request (the bot's check) or on its own (the scraper)."""
    from flask import has_app_context
    from app import app, db, Group
    if not has_app_context():
        with app.app_context():
            return tick(now)
    now = now or _local_now()
    groups = Group.query.filter((Group.trivia_enabled.is_(True)) | (Group.bingo_enabled.is_(True))).all()
    for g in groups:
        _trivia(g, now)
        _bingo(g, now)
        _expire(g, now)
    db.session.commit()
    return len(groups)


def tick_if_due(now=None):
    """tick(), unless it ran in the last few minutes (the bot asks every minute)."""
    from app import db, BotSetting
    row = db.session.get(BotSetting, 'games_tick_at')
    last = datetime.fromisoformat(row.value) if row and row.value else None
    utc = datetime.utcnow()
    if last and utc - last < TICK_EVERY:
        return False
    if not row:
        row = BotSetting(key='games_tick_at')
        db.session.add(row)
    row.value = utc.isoformat()
    db.session.commit()
    tick(now)
    return True


# ─── What a post shows ────────────────────────────────────────────────────────

def preview(post):
    """A post as it'll look (for the bot to post, and for admins to check):
    {id, kind, status, ...}. Trivia carries its question and — for admins —
    the right answer; the card its squares; a win who and which."""
    import bingo
    import trivia
    from app import db, Group, TriviaAnswer, TriviaQuestion, User
    group = db.session.get(Group, post.group_id)
    out = {'id': post.id, 'kind': post.kind, 'status': post.status, 'ref': post.ref}
    if post.kind == 'trivia':
        q = TriviaQuestion.query.filter_by(group_id=group.id, slot='daily', day=datetime.fromisoformat(post.ref).date()).first()
        if q:
            prev = TriviaQuestion.query.filter_by(group_id=group.id, slot='daily', day=q.day - timedelta(days=1)).first()
            out.update(question=trivia.as_dict(q), answer=q.answer,
                       yesterday=trivia.as_dict(prev, reveal=True) if prev else None,
                       can_swap=not TriviaAnswer.query.filter_by(question_id=q.id).first())
    elif post.kind == 'bingo_card':
        card = bingo.card_for(group, post.ref)
        out.update(month_label=bingo.month_bounds(card.month)[0].strftime('%B %Y'),
                   squares=[{'key': k, 'emoji': bingo.SQUARES[k][0], 'label': bingo.SQUARES[k][1], 'hint': bingo.SQUARES[k][3]}
                            for k in json.loads(card.squares_json)],
                   rules={'line': bingo.LINE_KERNELS, 'full': bingo.FULL_KERNELS})
    else:
        p = json.loads(post.payload_json or '{}')
        who = db.session.get(User, p.get('user_id'))
        out.update(which=p.get('which'), name=who.name if who and p.get('named') else None,
                   month_label=bingo.month_bounds(post.ref.split(':')[0])[0].strftime('%B'))
    return out


def ready_to_post(group):
    """Approved posts the bot should put in #movies now (the question only in its hours)."""
    from app import GamePost
    now = _local_now()
    out = []
    for post in GamePost.query.filter_by(group_id=group.id, status='approved').order_by(GamePost.id):
        if post.kind == 'trivia' and (post.ref != now.date().isoformat() or not TRIVIA_HOURS[0] <= now.hour < TRIVIA_HOURS[1]):
            continue
        out.append(preview(post))
    return out


def posted(post, message_id):
    from app import db, TriviaQuestion
    post.status, post.posted_at, post.message_id = 'posted', datetime.utcnow(), str(message_id or '')[:30] or None
    if post.kind == 'trivia':
        q = TriviaQuestion.query.filter_by(group_id=post.group_id, slot='daily',
                                           day=datetime.fromisoformat(post.ref).date()).first()
        if q:
            q.discord_message_id = post.message_id
    db.session.commit()


def waiting(group):
    """Posts waiting for an admin's OK, as they'll look."""
    from app import GamePost
    return [preview(p) for p in GamePost.query.filter_by(group_id=group.id, status='waiting').order_by(GamePost.id)]


def decide(post, user, action):
    """An admin's answer to a waiting post: 'post' | 'skip' | 'another'
    (trivia) | 'reshuffle' (the card). Returns (preview, error)."""
    import bingo
    import trivia
    from app import db, Group, TriviaQuestion, role_at_least, _active_membership
    group = db.session.get(Group, post.group_id)
    if not role_at_least(_active_membership(user, group.id), 'admin'):
        return None, 'Only club admins can do that.'
    if post.status != 'waiting':
        return preview(post), {'posted': 'It’s already posted.', 'approved': 'It’s already on its way.',
                               'skipped': 'It was skipped.', 'expired': 'It’s too late for that one.'}.get(post.status)
    if action in ('post', 'skip'):
        post.status = 'approved' if action == 'post' else 'skipped'
        post.decided_by, post.decided_at = user.id, datetime.utcnow()
        db.session.commit()
        return preview(post), None
    if action == 'another' and post.kind == 'trivia':
        q = TriviaQuestion.query.filter_by(group_id=group.id, slot='daily', day=datetime.fromisoformat(post.ref).date()).first()
        err = trivia.swap(q) if q else 'That question is gone.'
        return preview(post), err
    if action == 'reshuffle' and post.kind == 'bingo_card':
        bingo.reshuffle(bingo.card_for(group, post.ref))
        return preview(post), None
    return preview(post), 'Pick Post, Skip or a change that fits this post.'
