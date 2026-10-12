"""Clubs: creating, joining, members and roles, settings, site admin.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
from html import escape as esc

import app as core
from app import (AVATAR_COLORS, FRONTEND_URL, Group, GroupMembership, Message, Poll, PollCategory,
    PollOption, PollVote, ROLES, RSVP, Reaction, ShowtimeThread, Theatre, User, _active_membership, _as_int,
    _screening_item, _upload, app, current_user, datetime, db, guest_blocked, jsonify, random, re, request,
    require_auth, require_role, role_at_least, rsvp_changed, secrets, timezone, upcoming_rsvps)


def email_invite(to_email, group_name, invite_url):
    core.send_email(to_email, f"You're invited to {group_name} on Cinema Club DC",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>You've been invited to join <strong>{esc(group_name)}</strong> on Cinema Club DC!</p>
        <p><a href="{invite_url}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Accept Invite</a></p>
        <p style="color:#888;font-size:13px;">Or copy this link: {invite_url}</p>
        </div>""")


def email_added_to_group(to_email, group_name):
    core.send_email(to_email, f"You've been added to {group_name}",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>You've been added to <strong>{esc(group_name)}</strong>. Open Cinema Club DC to check out upcoming showtimes!</p>
        <p><a href="{FRONTEND_URL}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Open Cinema Club DC</a></p>
        </div>""")


def email_join_request(admin_email, requester_name, group_name):
    core.send_email(admin_email, f"{requester_name} wants to join {group_name}",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p><strong>{esc(requester_name)}</strong> has requested to join <strong>{esc(group_name)}</strong>.</p>
        <p>Log in to Cinema Club DC to approve or deny the request.</p>
        <p><a href="{FRONTEND_URL}/groups" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Manage Group</a></p>
        </div>""")


def email_approved(to_email, group_name):
    core.send_email(to_email, f"Welcome to {group_name}!",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>Your request to join <strong>{esc(group_name)}</strong> has been approved! 🎉</p>
        <p><a href="{FRONTEND_URL}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Open Cinema Club DC</a></p>
        </div>""")

def slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return slug[:50]


# ─── Routes: Admin ────────────────────────────────────────────────────────────

@app.route('/api/admin/invite', methods=['POST'])
@require_auth
def create_invite():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    group_id = _as_int(data.get('group_id'))

    if not email:
        return jsonify({'error': 'Email required'}), 400

    # Only a group's admins may invite to it — otherwise anyone could add
    # themselves (or others) straight into any group, skipping approval.
    group = db.session.get(Group, group_id) if group_id else None
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    membership = _active_membership(current_user(), group.id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    group_name = group.name
    existing = User.query.filter_by(email=email).first()

    if existing and existing.is_active:
        # User already has an account — just add them to the group directly
        if group_id:
            membership = GroupMembership.query.filter_by(user_id=existing.id, group_id=group_id).first()
            if not membership:
                membership = GroupMembership(user_id=existing.id, group_id=group_id, role='member', status='active')
                db.session.add(membership)
                db.session.commit()
            elif membership.status != 'active':
                membership.status = 'active'
                db.session.commit()
        email_added_to_group(email, group_name)
        return jsonify({'status': 'added', 'email': email, 'message': f'{email} added to {group_name}'})

    if existing and not existing.is_active:
        # Inactive user (previous invite that was removed, etc.) — reactivate path
        token = secrets.token_urlsafe(32)
        existing.invite_token = token
        if group_id:
            membership = GroupMembership.query.filter_by(user_id=existing.id, group_id=group_id).first()
            if not membership:
                membership = GroupMembership(user_id=existing.id, group_id=group_id, role='member', status='pending')
                db.session.add(membership)
            elif membership.status != 'active':
                membership.status = 'pending'
        db.session.commit()
        invite_url = f"{FRONTEND_URL}/invite/{token}"
        email_invite(email, group_name, invite_url)
        return jsonify({'status': 'reinvited', 'email': email, 'invite_url': invite_url,
                        'message': f'Invite re-sent to {email}'})

    # Brand new user — create inactive with invite token
    token = secrets.token_urlsafe(32)
    user = User(
        email=email,
        name=email.split('@')[0],
        invite_token=token,
        avatar_color=random.choice(AVATAR_COLORS),
        is_active=False
    )
    db.session.add(user)
    db.session.flush()

    if group_id:
        membership = GroupMembership(user_id=user.id, group_id=group_id, role='member', status='pending')
        db.session.add(membership)

    db.session.commit()

    invite_url = f"{FRONTEND_URL}/invite/{token}"
    email_invite(email, group_name, invite_url)
    return jsonify({'status': 'invited', 'email': email, 'invite_url': invite_url,
                    'message': f'Invite sent to {email}'})


# ─── Routes: Groups ──────────────────────────────────────────────────────────

@app.route('/api/groups', methods=['GET'])
@require_auth
def list_groups():
    user = current_user()
    memberships = GroupMembership.query.filter_by(user_id=user.id, status='active').all()
    groups = []
    for m in memberships:
        g = m.group.to_dict()
        g['role'] = m.role
        groups.append(g)
    return jsonify(groups)


@app.route('/api/groups', methods=['POST'])
@require_auth
def create_group():
    user = current_user()
    blocked = guest_blocked(user)
    if blocked:
        return blocked
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Group name required'}), 400

    slug = slugify(name)
    if Group.query.filter_by(slug=slug).first():
        return jsonify({'error': 'A group with this name already exists'}), 409

    # Validate theatres
    valid_slugs = {t.slug for t in Theatre.query.all()}
    requested_theatres = data.get('theatres', [])
    if requested_theatres:
        theatres_str = ','.join(s for s in requested_theatres if s in valid_slugs)
    else:
        theatres_str = ','.join(valid_slugs)  # default to all

    group = Group(
        name=name,
        slug=slug,
        description=data.get('description', ''),
        created_by=user.id,
        is_public=data.get('is_public', True),
        theatres=theatres_str
    )
    db.session.add(group)
    db.session.flush()

    membership = GroupMembership(user_id=user.id, group_id=group.id, role='admin', status='active')
    db.session.add(membership)
    db.session.commit()

    return jsonify(group.to_dict()), 201


@app.route('/api/groups/discover')
@require_auth
def discover_groups():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)

    query = Group.query.filter_by(is_public=True)
    if q:
        query = query.filter(Group.name.ilike(f'%{q}%'))

    pagination = query.order_by(Group.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    user = current_user()
    user_memberships = {m.group_id: m.status for m in GroupMembership.query.filter_by(user_id=user.id).all()}

    result = []
    for g in pagination.items:
        d = g.to_dict()
        d['membership_status'] = user_memberships.get(g.id)
        result.append(d)

    return jsonify({
        'groups': result,
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    })


@app.route('/api/groups/by-id/<int:group_id>', methods=['GET'])
@require_auth
def get_group_by_id(group_id):
    group = db.session.get(Group, group_id)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    user = current_user()
    membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
    d = group.to_dict()
    if membership:
        d['role'] = membership.role
    return jsonify(d)


@app.route('/api/groups/<slug>', methods=['GET'])
@require_auth
def get_group(slug):
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    user = current_user()
    membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
    # Pending requesters see the group, not its member list.
    d = group.to_dict(include_members=bool(membership and membership.status == 'active'),
                      with_email=role_at_least(membership, 'admin'))
    if membership:
        d['role'] = membership.role
        d['membership_status'] = membership.status
    return jsonify(d)


@app.route('/api/groups/<slug>', methods=['PUT'])
@require_auth
def update_group(slug):
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    user = current_user()
    admin_membership = GroupMembership.query.filter_by(
        user_id=user.id, group_id=group.id, role='admin', status='active'
    ).first()
    if not admin_membership:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json or {}

    name = (data.get('name') or '').strip()
    if name:
        group.name = name[:100]

    if 'description' in data:
        desc = (data.get('description') or '').strip()
        group.description = desc[:500]

    if 'theatres' in data:
        valid_slugs = {t.slug for t in Theatre.query.all()}
        theatres_list = data.get('theatres', [])
        group.theatres = ','.join(s for s in theatres_list if s in valid_slugs)

    # Picture (R6b): an emoji replaces a photo; "photo": null removes it.
    import media
    if 'emoji' in data:
        emoji = media.clean_emoji(data.get('emoji'))
        if data.get('emoji') and not emoji:
            return jsonify({'error': 'Pick an emoji.'}), 400
        group.emoji = emoji
        if emoji:
            media.delete(app.instance_path, group.photo_url)
            group.photo_url = None
    if 'photo' in data and data['photo'] is None:
        media.delete(app.instance_path, group.photo_url)
        group.photo_url = None
    if 'short_name' in data:
        group.short_name = re.sub(r'\s+', ' ', (data.get('short_name') or '')).strip()[:12] or None

    db.session.commit()
    return jsonify(group.to_dict())


@app.route('/api/groups/<slug>/picture', methods=['POST'])
@require_auth
def upload_group_picture(slug):
    """An admin uploads the club's photo (multipart 'file'); it replaces any emoji."""
    import media
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    _, err = require_role(current_user(), group.id, 'admin')
    if err:
        return err
    url, err = _upload('club')
    if err:
        return err
    media.delete(app.instance_path, group.photo_url)
    group.photo_url, group.emoji = url, None
    db.session.commit()
    return jsonify(group.to_dict())


@app.route('/api/groups/<slug>', methods=['DELETE'])
@require_auth
def delete_group(slug):
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    user = current_user()
    admin_membership = GroupMembership.query.filter_by(
        user_id=user.id, group_id=group.id, role='admin', status='active'
    ).first()
    if not admin_membership:
        return jsonify({'error': 'Admin access required'}), 403

    # Delete all group-scoped data in FK-safe order
    # Delete poll data first (votes → options → categories → polls)
    for poll in Poll.query.filter_by(group_id=group.id).all():
        for cat in poll.categories:
            PollVote.query.filter_by(category_id=cat.id).delete()
            PollOption.query.filter_by(category_id=cat.id).delete()
        PollCategory.query.filter_by(poll_id=poll.id).delete()
    Poll.query.filter_by(group_id=group.id).delete()
    Message.query.filter_by(group_id=group.id).delete()
    ShowtimeThread.query.filter_by(group_id=group.id).delete()   # threads stay in Discord, unlinked
    Reaction.query.filter_by(group_id=group.id).delete()
    RSVP.query.filter_by(group_id=group.id).delete()
    GroupMembership.query.filter_by(group_id=group.id).delete()
    import media
    media.delete(app.instance_path, group.photo_url)
    db.session.delete(group)
    db.session.commit()

    return jsonify({'message': 'Group deleted'})


@app.route('/api/groups/<slug>/join', methods=['POST'])
@require_auth
def join_group(slug):
    user = current_user()
    blocked = guest_blocked(user)
    if blocked:
        return blocked
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    existing = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
    if existing:
        return jsonify({'error': 'Already a member or request pending', 'status': existing.status}), 409

    membership = GroupMembership(user_id=user.id, group_id=group.id, role='member', status='pending')
    db.session.add(membership)
    db.session.commit()

    # Email all group admins about the join request
    admins = GroupMembership.query.filter_by(group_id=group.id, role='admin', status='active').all()
    for a in admins:
        admin_user = db.session.get(User, a.user_id)
        if admin_user:
            email_join_request(admin_user.email, user.name, group.name)

    return jsonify({'message': 'Join request sent', 'status': 'pending'}), 202


@app.route('/api/groups/<slug>/members')
@require_auth
def group_members(slug):
    user = current_user()
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id, status='active').first()
    if not membership:
        return jsonify({'error': 'Not a member'}), 403

    members = GroupMembership.query.filter_by(group_id=group.id).all()
    result = []
    for m in members:
        # Only admins can see pending members
        if m.status == 'pending' and membership.role != 'admin':
            continue
        result.append(m.to_dict(with_email=membership.role == 'admin'))   # emails: admins only

    return jsonify(result)


@app.route('/api/groups/<slug>/members/<int:uid>/approve', methods=['POST'])
@require_auth
def approve_member(slug, uid):
    user = current_user()
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    admin_membership = GroupMembership.query.filter_by(
        user_id=user.id, group_id=group.id, role='admin', status='active'
    ).first()
    if not admin_membership:
        return jsonify({'error': 'Admin access required'}), 403

    target = GroupMembership.query.filter_by(user_id=uid, group_id=group.id, status='pending').first()
    if not target:
        return jsonify({'error': 'No pending request found'}), 404

    target.status = 'active'
    db.session.commit()

    # Email the approved user
    approved_user = db.session.get(User, uid)
    if approved_user:
        email_approved(approved_user.email, group.name)

    return jsonify({'message': 'Member approved'})


@app.route('/api/groups/<slug>/members/<int:uid>/deny', methods=['POST'])
@require_auth
def deny_member(slug, uid):
    user = current_user()
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    admin_membership = GroupMembership.query.filter_by(
        user_id=user.id, group_id=group.id, role='admin', status='active'
    ).first()
    if not admin_membership:
        return jsonify({'error': 'Admin access required'}), 403

    target = GroupMembership.query.filter_by(user_id=uid, group_id=group.id, status='pending').first()
    if not target:
        return jsonify({'error': 'No pending request found'}), 404

    db.session.delete(target)
    db.session.commit()
    return jsonify({'message': 'Request denied'})


@app.route('/api/groups/<slug>/members/<int:uid>', methods=['DELETE'])
@require_auth
def remove_member(slug, uid):
    user = current_user()
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404

    # User can remove themselves, or admin can remove others
    if uid == user.id:
        target = GroupMembership.query.filter_by(user_id=uid, group_id=group.id).first()
    else:
        admin_membership = GroupMembership.query.filter_by(
            user_id=user.id, group_id=group.id, role='admin', status='active'
        ).first()
        if not admin_membership:
            return jsonify({'error': 'Admin access required'}), 403
        target = GroupMembership.query.filter_by(user_id=uid, group_id=group.id).first()

    if not target:
        return jsonify({'error': 'Member not found'}), 404
    if _is_last_admin(target):
        return jsonify({'error': "The club's only admin can't leave. Make someone else an admin first.", 'code': 'last_admin'}), 400

    db.session.delete(target)
    db.session.commit()
    return jsonify({'message': 'Member removed'})


def _is_last_admin(m):
    return (m.role == 'admin' and m.status == 'active'
            and GroupMembership.query.filter_by(group_id=m.group_id, role='admin', status='active').count() <= 1)


@app.route('/api/groups/<int:group_id>/personal-plans')
@require_auth
def personal_plans(group_id):
    """Your upcoming personal plans (made as a guest or without a club) that
    you could share with this club — asked once when you're in it (R5c)."""
    user = current_user()
    _, err = require_role(user, group_id, 'member')
    if err:
        return err
    return jsonify({'items': [_screening_item(s, st) for s, st in upcoming_rsvps(user, [], personal=True)]})


@app.route('/api/groups/<int:group_id>/personal-plans', methods=['POST'])
@require_auth
def bring_plans(group_id):
    """Share the chosen personal plans with the club: each moves into it (one
    RSVP, now visible to the club). {showtime_ids: [...]}"""
    user = current_user()
    _, err = require_role(user, group_id, 'member')
    if err:
        return err
    ids = {_as_int(x) for x in (request.json or {}).get('showtime_ids', []) if _as_int(x)}
    moved = 0
    for r in RSVP.query.filter(RSVP.user_id == user.id, RSVP.group_id.is_(None), RSVP.showtime_id.in_(ids)).all():
        if RSVP.query.filter_by(user_id=user.id, showtime_id=r.showtime_id, group_id=group_id).first():
            db.session.delete(r)          # already planned with the club: the club's RSVP stands
        else:
            r.group_id = group_id
            r.updated_at = datetime.now(timezone.utc)
            thread = ShowtimeThread.query.filter_by(showtime_id=r.showtime_id, group_id=group_id).first()
            if thread:
                thread.card_dirty = True
            rsvp_changed(user.id, r.showtime_id, group_id, r.status)
            moved += 1
    db.session.commit()
    return jsonify({'moved': moved})


@app.route('/api/groups/<slug>/members/<int:uid>/role', methods=['PUT'])
@require_auth
def set_member_role(slug, uid):
    # Admins grant or revoke roles; a club always keeps at least one admin.
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    _, err = require_role(current_user(), group.id, 'admin')
    if err:
        return err
    role = (request.json or {}).get('role')
    if role not in ROLES:
        return jsonify({'error': 'Unknown role'}), 400
    target = GroupMembership.query.filter_by(user_id=uid, group_id=group.id, status='active').first()
    if not target:
        return jsonify({'error': 'Member not found'}), 404
    if role != 'admin' and _is_last_admin(target):
        return jsonify({'error': 'A club needs at least one admin. Make someone else an admin first.', 'code': 'last_admin'}), 400
    target.role = role
    db.session.commit()
    return jsonify(target.to_dict(with_email=True))       # admins only
