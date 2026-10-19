"""What the bot posts and reports: its queue of Discord posts, site activity,
scrape events, the chatbot's context, members' alerts and notifications.
"""
import app as core
import taste
import places
from app import (ActivityEvent, BotSetting, DiscordPost, DiscordServer, DiscordServerMember, Group,
    Notification, RSVP, SavedSearch, ScrapeEvent, Showtime, ShowtimeThread, Theatre, User, Watchlist,
    _group_showtime_query, _notify_settings, _utcnow_naive, app, attended_showtime_ids, build_leaderboard, db,
    jsonify, on_discord, post_dict, render_post, request, set_share_pref, timedelta)
from routes.internal.common import _present_changed, require_internal, resolve_discord_user


def members_synced(group_id):
    """Has the bot reported this club's server's members yet? Until it has,
    nothing is posted there."""
    server = core.discord_server(group_id)
    if server and server.reported_at:
        return True
    return group_id == core.HOME_GROUP_ID and db.session.get(BotSetting, 'discord_members_synced_at') is not None


# ─── Discord posts: the bot's queue ───────────────────────────────────────────

@app.route('/api/internal/discord/posts/due')
@require_internal
def internal_posts_due():
    """What the bot should do now: post shares whose time has come, update
    posted ones whose content changed, delete ones with nothing left to show.
    Each item: {id, kind, action: post|edit|delete, message_id, data}.
    Nothing until the bot has reported who's in the server."""
    import places
    group_id = request.args.get('group_id', type=int)
    now = places.server_now()                                # the post queue's clock
    out = []
    if not members_synced(group_id):
        return jsonify(out)
    for p in (DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.status == 'pending',
                                       DiscordPost.post_at <= now)
              .order_by(DiscordPost.post_at, DiscordPost.id).limit(10)):
        data = render_post(p) if on_discord(p.user, p.group_id) else None
        if data is None:
            p.status = 'cancelled'            # nothing left to say (or they've left the server)
            continue
        out.append({'id': p.id, 'kind': p.kind, 'action': 'post', 'message_id': None, 'data': data})
    for p in (DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.dirty.is_(True),
                                       DiscordPost.status.in_(('posted', 'removing')))
              .order_by(DiscordPost.id).limit(10)):
        data = render_post(p, now)
        if p.kind == 'thread':                 # a thread lives on its own once started
            p.dirty = False
            continue
        out.append({'id': p.id, 'kind': p.kind, 'action': 'edit' if data else 'delete',
                    'message_id': p.message_id, 'data': data})
    db.session.commit()
    return jsonify(out)


@app.route('/api/internal/discord/members', methods=['POST'])
@require_internal
def internal_discord_members():
    """Who's in a connected server, from the bot: {guild_id, ids: [...], full:
    true} is the whole list (on start, and every half hour); {joined: [...]} /
    {left: [...]} are changes as they happen. Screenings whose Discord cards
    list someone who joined or left are refreshed. No guild_id: the home
    server, from before servers were per club."""
    data = request.json or {}
    guild = str(data.get('guild_id') or '') or None
    if guild and data.get('home') and not db.session.get(DiscordServer, guild):
        import discord_servers
        discord_servers.adopt_home(guild)                 # the bot's own server: register it
    server = db.session.get(DiscordServer, guild) if guild else None
    group_id = server.group_id if server else (core.HOME_GROUP_ID if not guild else None)
    if not group_id:
        return jsonify({'error': 'That server isn\'t connected to a club'}), 404
    clean = lambda key: {str(i) for i in data.get(key) or [] if str(i).isdigit()}
    rows = DiscordServerMember.query.filter(DiscordServerMember.guild_id == guild if guild
                                            else DiscordServerMember.guild_id.is_(None))
    current = {r.discord_user_id for r in rows}
    if data.get('full'):
        ids = clean('ids')
        joined, left = ids - current, current - ids
    else:
        joined, left = clean('joined') - current, clean('left') & current
    if left:
        rows.filter(DiscordServerMember.discord_user_id.in_(left)).delete(synchronize_session=False)
    for i in joined:
        db.session.add(DiscordServerMember(guild_id=guild, discord_user_id=i))
    changed = joined | left
    if changed:
        users = [u.id for u in User.query.filter(User.discord_user_id.in_(changed))]
        upcoming = {r.showtime_id for r in RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id).filter(
            RSVP.user_id.in_(users), RSVP.group_id == group_id, Showtime.start_time >= places.club_now(db.session.get(Group, group_id)))} \
            if users else set()
        if upcoming:
            ShowtimeThread.query.filter(ShowtimeThread.group_id == group_id,
                                        ShowtimeThread.showtime_id.in_(upcoming)) \
                .update({'card_dirty': True}, synchronize_session=False)
            DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.kind == 'invite',
                                     DiscordPost.ref_id.in_(upcoming), DiscordPost.status == 'posted') \
                .update({'dirty': True}, synchronize_session=False)
    if data.get('full'):
        if server:
            server.reported_at, server.member_count = _utcnow_naive(), len(clean('ids'))
        if group_id == core.HOME_GROUP_ID:
            row = db.session.get(BotSetting, 'discord_members_synced_at') or BotSetting(key='discord_members_synced_at')
            row.value = _utcnow_naive().isoformat(timespec='seconds')
            db.session.add(row)
    db.session.commit()
    _present_changed()
    return jsonify({'members': len(current - left) + len(joined), 'joined': len(joined), 'left': len(left)})


@app.route('/api/internal/discord/posts/<int:post_id>/done', methods=['POST'])
@require_internal
def internal_post_done(post_id):
    """{action: posted (+message_id, jump_url) | edited | deleted}."""
    p = db.session.get(DiscordPost, post_id)
    if not p:
        return jsonify({'error': 'Not found'}), 404
    data = request.json or {}
    action = data.get('action')
    if action == 'posted':
        p.status, p.posted_at = 'posted', places.server_now()
        p.message_id = str(data.get('message_id') or '') or None
        p.jump_url = (data.get('jump_url') or '')[:200] or None
    elif action == 'edited':
        p.dirty = False
    elif action == 'deleted':
        p.status, p.dirty = 'removed', False
    else:
        return jsonify({'error': 'Unknown action'}), 400
    db.session.commit()
    return jsonify(post_dict(p))


@app.route('/api/internal/scrape-events')
@require_internal
def internal_scrape_events():
    q = ScrapeEvent.query
    if request.args.get('unannounced'):
        q = q.filter(ScrapeEvent.announced_at.is_(None))
    # Never announce stale events (e.g. backfill runs while the bot was down)
    since_hours = request.args.get('since_hours', 48, type=int)
    q = q.filter(ScrapeEvent.created_at > _utcnow_naive() - timedelta(hours=since_hours))
    events = q.order_by(ScrapeEvent.created_at).limit(20).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/internal/scrape-events/<int:event_id>/announced', methods=['POST'])
@require_internal
def internal_mark_announced(event_id):
    event = db.session.get(ScrapeEvent, event_id)
    if not event:
        return jsonify({'error': 'Not found'}), 404
    if not event.announced_at:
        event.announced_at = _utcnow_naive()
        db.session.commit()
    return jsonify(event.to_dict())


@app.route('/api/internal/activity-events')
@require_internal
def internal_activity_events():
    q = ActivityEvent.query
    if request.args.get('unannounced'):
        q = q.filter(ActivityEvent.announced_at.is_(None))
    # Don't announce stale actions if the bot was offline a while.
    since_hours = request.args.get('since_hours', 6, type=int)
    q = q.filter(ActivityEvent.created_at > _utcnow_naive() - timedelta(hours=since_hours))
    events = q.order_by(ActivityEvent.created_at).limit(20).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/internal/activity-events/<int:event_id>/announced', methods=['POST'])
@require_internal
def internal_mark_activity_announced(event_id):
    ev = db.session.get(ActivityEvent, event_id)
    if not ev:
        return jsonify({'error': 'Not found'}), 404
    if not ev.announced_at:
        ev.announced_at = _utcnow_naive()
        db.session.commit()
    return jsonify(ev.to_dict())


@app.route('/api/internal/chat-context')
@require_internal
def internal_chat_context():
    """Compact per-user + what's-playing bundle powering the bot's @-mention
    chatbot. Everything is bounded to keep the prompt small, and the bot is
    told to treat `upcoming` as the ONLY source of real screenings."""
    discord_id = str(request.args.get('discord_user_id') or '').strip()
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = places.club_now(group)

    user = User.query.filter_by(discord_user_id=discord_id).first() if discord_id else None
    out = {'user': {'linked': bool(user)}}

    if user:
        out['user'].update({
            'name': user.name,
            'genres': ', '.join(taste.GENRE_LABELS[k] for k in taste.genres(user)),
            'letterboxd_username': user.letterboxd_username or '',
            'bio': (user.bio or '')[:300],
        })

        import kernels
        k = kernels.breakdown(user.id, group.id if group else None)
        standing = {'kernels': k['kernels'], 'correct_picks': k['correct']}
        if group:
            board = build_leaderboard(group)
            standing['of'] = len(board)
            for i, row in enumerate(board):
                if row['user']['id'] == user.id:
                    standing['rank'] = i + 1
                    standing['attendance'] = row['attendance']
                    break
        out['standing'] = standing

        wl = (Watchlist.query.filter_by(user_id=user.id)
              .order_by(Watchlist.created_at.desc()).limit(25).all())
        out['watchlist'] = [{'title': w.movie.title, 'year': w.movie.release_year}
                            for w in wl if w.movie]

        seen_ids = attended_showtime_ids(user.id, {group.id} if group else None)
        seen, attended = set(), []
        for s in (Showtime.query.filter(Showtime.id.in_(seen_ids))
                  .order_by(Showtime.start_time.desc()).limit(60).all() if seen_ids else []):
            m = s.movie
            if not m or m.title in seen:
                continue
            seen.add(m.title)
            attended.append({
                'title': m.title,
                'year': m.release_year,
                'theatre': s.theatre.short_name or s.theatre.name,
                'date': s.start_time.strftime('%Y-%m-%d'),
            })
            if len(attended) >= 20:
                break
        out['attended'] = attended

    # What the ask is about (R3b): films that fit it, from the Discover engine.
    prompt = (request.args.get('prompt') or '').strip()
    if prompt and group:
        import discover
        out['picks'] = discover.chat_picks(group, user, prompt[:500], now)

    # Always include what's playing (group-scoped) so unlinked askers still get help.
    upcoming = (_group_showtime_query(group)
                .filter(Showtime.start_time >= now,
                        Showtime.start_time <= now + timedelta(days=14))
                .order_by(Showtime.start_time).limit(60).all())
    out['upcoming'] = [{
        'title': s.movie.title,
        'genres': s.movie.genres or '',
        'theatre': s.theatre.short_name or s.theatre.name,
        'date': s.start_time.strftime('%a %-m/%-d'),
        'time': s.start_time.strftime('%-I:%M %p'),
    } for s in upcoming]
    # Where the crew is (the chatbot's persona): the club's city and a few of
    # its theatres, its independent houses first.
    import cities
    theatres = [t for t in places.theatres_in() if t.slug in places.club_slugs(group)]
    theatres.sort(key=lambda t: (t.slug not in places.arthouse_slugs(), t.name))
    out['club'] = {'city': cities.get(places.club_city(group)).short, 'haunts': [t.name for t in theatres[:4]]}

    return jsonify(out)


def _slug_list(value):
    return [s.strip() for s in (value or '').split(',') if s.strip()]


@app.route('/api/internal/alerts')
@require_internal
def internal_alerts():
    """Theatres whose new-showtime drops the bot announces for a group. Opt-in:
    a theatre not listed is quiet, and its new showtimes reach people through
    the weekly digest instead."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    slugs = _slug_list(group.announce_enabled_theatres if group else '')
    names = {t.slug: (t.short_name or t.name)
             for t in Theatre.query.filter(Theatre.slug.in_(slugs)).all()} if slugs else {}
    return jsonify({
        'slugs': slugs,
        'enabled': [{'slug': s, 'name': names.get(s, s)} for s in slugs],
    })


@app.route('/api/internal/alerts', methods=['POST'])
@require_internal
def internal_alerts_update():
    data = request.json or {}
    group = db.session.get(Group, data.get('group_id')) if data.get('group_id') else None
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    slug = (data.get('theatre_slug') or '').strip()
    action = (data.get('action') or '').lower()
    theatre = Theatre.query.filter_by(slug=slug).first()
    if not theatre:
        return jsonify({'error': 'Theatre not found'}), 404
    if action not in ('enable', 'disable'):
        return jsonify({'error': 'action must be enable or disable'}), 400

    current = _slug_list(group.announce_enabled_theatres)
    changed = (slug not in current) if action == 'enable' else (slug in current)
    if action == 'enable' and changed:
        current.append(slug)
    elif action == 'disable':
        current = [s for s in current if s != slug]
    group.announce_enabled_theatres = ','.join(current)
    db.session.commit()
    return jsonify({'theatre_slug': slug, 'theatre_name': theatre.short_name or theatre.name,
                    'enabled': action == 'enable', 'changed': changed, 'slugs': current})


@app.route('/api/internal/notifications/dm')
@require_internal
def internal_notification_dms():
    """Alerts the bot should DM now, bundled per person."""
    import notify
    return jsonify(notify.pending_dms())


@app.route('/api/internal/notifications/dm-sent', methods=['POST'])
@require_internal
def internal_notification_dm_sent():
    """The bot DMed these (or couldn't — DMs closed): don't send them again."""
    ids = [i for i in (request.json or {}).get('ids') or [] if isinstance(i, int)]
    if ids:
        Notification.query.filter(Notification.id.in_(ids)).update(
            {'discord_at': _utcnow_naive()}, synchronize_session=False)
        db.session.commit()
    return jsonify({'marked': len(ids)})


@app.route('/api/internal/notifications/settings', methods=['POST'])
@require_internal
def internal_notification_settings():
    """/notifications in Discord: read (no changes sent) or change your setting."""
    import notify
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    if data.get('channels') or data.get('types'):
        notify.set_prefs(user, data)
    if isinstance(data.get('digest_mentions'), bool):       # "mention me in the Monday digest"
        set_share_pref(user, 'watchlist', 'always' if data['digest_mentions'] else 'never')
    if isinstance(data.get('remove_search'), int):           # "stop alerts for" a saved search
        SavedSearch.query.filter_by(id=data['remove_search'], user_id=user.id).delete()
    db.session.commit()
    return jsonify(_notify_settings(user))
