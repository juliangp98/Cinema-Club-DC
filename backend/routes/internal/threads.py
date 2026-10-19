"""Screening discussions mirrored between the site and Discord threads.
"""
from app import (DiscordDeletion, Message, Showtime, ShowtimeThread,
    _active_membership, _as_int, _utcnow_naive, app, db, jsonify, present_user_ids, request, require_role,
    screening_card, timedelta, utc_iso)
from routes.internal.common import require_internal, resolve_discord_user


# ─── Discussion threads (mirrored with Discord) ───────────────────────────────
# Each screening's discussion can have a thread in #movies. The bot owns all
# Discord calls; the backend keeps the mapping and an outbox: site comments not
# yet copied to Discord, site deletions to carry out, and starter cards whose
# RSVP list changed. Thread messages come back in as comments.

DISCUSSION_BACKFILL = 10                      # earlier comments copied into a new thread
OUTBOX_WINDOW = timedelta(hours=24)           # older unsent comments are backfilled instead
CARD_REFRESH_EVERY = timedelta(minutes=3)


def _pending_post(q, group_id):
    """Site comments the bot still has to copy into this club's Discord (never
    ones their writer kept off Discord, or by anyone not in its server)."""
    return q.filter(Message.source == 'site', Message.discord_message_id.is_(None),
                    Message.to_discord.isnot(False), Message.user_id.in_(list(present_user_ids(group_id))),
                    Message.created_at >= _utcnow_naive() - OUTBOX_WINDOW)


def _thread_dict(t):
    return {'thread_id': t.thread_id, 'channel_id': t.channel_id, 'guild_id': t.guild_id,
            'starter_message_id': t.starter_message_id, 'showtime_id': t.showtime_id, 'url': t.url}


def _outbound(m):
    """A comment as the bot posts it: under its author's name (and Discord avatar, if linked)."""
    avatar = m.user.avatar_url if (m.user.avatar_url or '').startswith('https://cdn.discordapp.com/') else None
    return {'message_id': m.id, 'showtime_id': m.showtime_id, 'body': m.body, 'created_at': utc_iso(m.created_at),
            'author': {'id': m.user.id, 'name': m.user.name, 'avatar_url': avatar}}


def thread_info(showtime, group_id):
    """The thread (if any) and starter card for a screening; when there's no
    thread yet, the comments to copy in when it's created: the last
    DISCUSSION_BACKFILL, minus any the outbox is about to post anyway."""
    t = ShowtimeThread.query.filter_by(showtime_id=showtime.id, group_id=group_id).first()
    out = {'thread': _thread_dict(t) if t else None, 'card': screening_card(showtime, group_id)}
    if not t:
        q = Message.query.filter_by(showtime_id=showtime.id, group_id=group_id)
        pending = {m.id for m in _pending_post(q, group_id)}
        earlier = [m for m in q.order_by(Message.created_at.desc(), Message.id.desc())
                   if m.id not in pending and m.to_discord is not False and m.user_id in present_user_ids(group_id)]
        out['earlier_total'] = len(earlier)
        out['backfill'] = [_outbound(m) for m in reversed(earlier[:DISCUSSION_BACKFILL])]
    return out


@app.route('/api/internal/discussion/threads')
@require_internal
def internal_discussion_threads():
    """Every linked thread id (the bot only mirrors these)."""
    group_id = request.args.get('group_id', type=int)
    return jsonify([t.thread_id for t in ShowtimeThread.query.filter_by(group_id=group_id)])


@app.route('/api/internal/discussion/thread')
@require_internal
def internal_discussion_thread():
    showtime = db.session.get(Showtime, request.args.get('showtime_id', type=int) or 0)
    if not showtime:
        return jsonify({'error': 'showtime_not_found'}), 404
    return jsonify(thread_info(showtime, request.args.get('group_id', type=int)))


@app.route('/api/internal/discussion/threads', methods=['POST'])
@require_internal
def internal_register_thread():
    """Link a newly created thread. If the screening already has one (a race),
    returns that with 409 so the bot can drop its duplicate."""
    data = request.json or {}
    showtime_id, group_id = _as_int(data.get('showtime_id')), _as_int(data.get('group_id'))
    existing = ShowtimeThread.query.filter_by(showtime_id=showtime_id, group_id=group_id).first()
    if existing:
        return jsonify({'error': 'exists', 'thread': _thread_dict(existing)}), 409
    t = ShowtimeThread(showtime_id=showtime_id, group_id=group_id, guild_id=str(data.get('guild_id')),
                       channel_id=str(data.get('channel_id')), thread_id=str(data.get('thread_id')),
                       starter_message_id=str(data['starter_message_id']) if data.get('starter_message_id') else None,
                       card_refreshed_at=_utcnow_naive())
    db.session.add(t)
    db.session.commit()
    return jsonify(_thread_dict(t)), 201


@app.route('/api/internal/discussion/threads/<thread_id>/unlink', methods=['POST'])
@require_internal
def internal_unlink_thread(thread_id):
    """The thread was deleted in Discord: forget it (comments stay on the site;
    the next comment starts a new thread)."""
    t = ShowtimeThread.query.filter_by(thread_id=str(thread_id)).first()
    if t:
        Message.query.filter_by(showtime_id=t.showtime_id, group_id=t.group_id) \
            .update({'discord_message_id': None}, synchronize_session=False)
        DiscordDeletion.query.filter_by(thread_id=t.thread_id, done_at=None).delete()
        db.session.delete(t)
        db.session.commit()
    return jsonify({'unlinked': bool(t)})


@app.route('/api/internal/discussion/outbox')
@require_internal
def internal_discussion_outbox():
    group_id = request.args.get('group_id', type=int)
    # Comments wait until their screening has a thread (Discord's Discuss, or
    # "Start a Discord thread" on the site); new comments never start one.
    threaded = db.session.query(ShowtimeThread.showtime_id).filter(ShowtimeThread.group_id == group_id)
    posts = _pending_post(Message.query.filter(Message.group_id == group_id, Message.showtime_id.in_(threaded)), group_id) \
        .order_by(Message.created_at, Message.id).limit(20).all()
    stale = _utcnow_naive() - CARD_REFRESH_EVERY
    cards = ShowtimeThread.query.filter(
        ShowtimeThread.group_id == group_id, ShowtimeThread.card_dirty.is_(True),
        db.or_(ShowtimeThread.card_refreshed_at.is_(None), ShowtimeThread.card_refreshed_at < stale)).limit(10).all()
    deletions = DiscordDeletion.query.filter_by(done_at=None).order_by(DiscordDeletion.id).limit(20).all()
    return jsonify({
        'posts': [_outbound(m) for m in posts],
        'deletions': [{'id': d.id, 'thread_id': d.thread_id, 'discord_message_id': d.discord_message_id}
                      for d in deletions],
        'cards': [{**_thread_dict(t), 'card': screening_card(db.session.get(Showtime, t.showtime_id), group_id)}
                  for t in cards if db.session.get(Showtime, t.showtime_id)],
    })


@app.route('/api/internal/discussion/mirrored', methods=['POST'])
@require_internal
def internal_discussion_mirrored():
    """Record the Discord copies of site comments ({items: [{message_id, discord_message_id}]})."""
    for item in (request.json or {}).get('items', []):
        m = db.session.get(Message, _as_int(item.get('message_id')))
        if m and not m.discord_message_id:
            m.discord_message_id = str(item.get('discord_message_id'))
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/discussion/deletions/<int:deletion_id>/done', methods=['POST'])
@require_internal
def internal_discussion_deletion_done(deletion_id):
    d = db.session.get(DiscordDeletion, deletion_id)
    if d and not d.done_at:
        d.done_at = _utcnow_naive()
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/discussion/cards/<thread_id>/refreshed', methods=['POST'])
@require_internal
def internal_discussion_card_refreshed(thread_id):
    t = ShowtimeThread.query.filter_by(thread_id=str(thread_id)).first()
    if t:
        t.card_dirty, t.card_refreshed_at = False, _utcnow_naive()
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/discussion/messages', methods=['POST'])
@require_internal
def internal_discussion_message():
    """A message from a screening thread (typed, or posted by the bot for a
    member) becomes that member's comment. Idempotent per Discord message."""
    data = request.json or {}
    t = ShowtimeThread.query.filter_by(thread_id=str(data.get('thread_id'))).first()
    if not t:
        return jsonify({'error': 'unknown_thread'}), 404
    did = str(data.get('discord_message_id') or '')
    existing = Message.query.filter_by(discord_message_id=did).first() if did else None
    if existing:
        return jsonify({'id': existing.id, 'duplicate': True})
    body = (data.get('body') or '').strip()[:2000]
    if not body or not did:
        return jsonify({'error': 'body and discord_message_id required'}), 400
    user, err = resolve_discord_user(data)
    if err:
        return err
    if not _active_membership(user, t.group_id):
        return jsonify({'error': 'not_member'}), 403
    source = 'discord_bot' if data.get('source') == 'discord_bot' else 'discord'
    # Typed in the thread: Discord's own permissions apply, so it mirrors. Posted
    # through the bot's Discuss button: read-only members can't (R5c).
    if source == 'discord_bot':
        _, err = require_role(user, t.group_id, 'member')
        if err:
            return err
    m = Message(user_id=user.id, showtime_id=t.showtime_id, group_id=t.group_id, body=body,
                source=source, discord_message_id=did)
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id}), 201


@app.route('/api/internal/discussion/messages/edit', methods=['POST'])
@require_internal
def internal_discussion_edit():
    data = request.json or {}
    m = Message.query.filter_by(discord_message_id=str(data.get('discord_message_id'))).first()
    body = (data.get('body') or '').strip()[:2000]
    updated = bool(m and body and m.source == 'discord')   # only messages typed in Discord are edited there
    if updated:
        m.body = body
        db.session.commit()
    return jsonify({'updated': updated})


@app.route('/api/internal/discussion/messages/delete', methods=['POST'])
@require_internal
def internal_discussion_delete():
    """Messages deleted in a thread (by their author or a moderator) leave the site too."""
    ids = [str(i) for i in (request.json or {}).get('discord_message_ids', [])]
    n = Message.query.filter(Message.discord_message_id.in_(ids)).delete(synchronize_session=False) if ids else 0
    db.session.commit()
    return jsonify({'deleted': n})
