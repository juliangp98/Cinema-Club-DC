"""Your alerts (the bell), the notification setting, web push.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
import app as core
from app import (Notification, PushSubscription, _notify_settings, _utcnow_naive, app, current_user, db,
    jsonify, request, require_auth)


@app.route('/api/notifications')
@require_auth
def notifications_list():
    """Your latest alerts (newest first) and how many are unread; ?count=1
    for just the count (the bell polls that)."""
    import notify
    user = current_user()
    unread = Notification.query.filter_by(user_id=user.id, read_at=None).count()
    if request.args.get('count'):
        return jsonify({'unread': unread})
    rows = (Notification.query.filter_by(user_id=user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(50).all())
    return jsonify({'items': [notify.item(n) for n in rows], 'unread': unread})


@app.route('/api/notifications/read', methods=['POST'])
@require_auth
def notifications_read():
    """Mark alerts read: {ids: [...]}, or all of them without ids."""
    user = current_user()
    q = Notification.query.filter_by(user_id=user.id, read_at=None)
    ids = (request.json or {}).get('ids')
    if isinstance(ids, list):
        q = q.filter(Notification.id.in_([i for i in ids if isinstance(i, int)]))
    marked = q.update({'read_at': _utcnow_naive()}, synchronize_session=False)
    db.session.commit()
    return jsonify({'marked': marked})


@app.route('/api/push/key')
def push_key():
    """The public half of the push key pair (None: push isn't set up)."""
    return jsonify({'key': core.VAPID_PUBLIC_KEY or None})


@app.route('/api/push/subscribe', methods=['POST'])
@require_auth
def push_subscribe():
    """This device wants push: {endpoint, keys: {p256dh, auth}} (the browser's
    PushSubscription). Turns push on in your setting."""
    import notify
    user = current_user()
    data = request.json or {}
    endpoint, keys = str(data.get('endpoint') or ''), data.get('keys') or {}
    if not core.VAPID_PUBLIC_KEY or not endpoint.startswith('https://') or not keys.get('p256dh') or not keys.get('auth'):
        return jsonify({'error': "Couldn't turn on push for this device."}), 400
    sub = PushSubscription.query.filter_by(endpoint=endpoint[:800]).first() \
        or PushSubscription(endpoint=endpoint[:800], user_id=user.id, p256dh='', auth='')
    sub.user_id, sub.p256dh, sub.auth = user.id, str(keys['p256dh'])[:200], str(keys['auth'])[:100]
    db.session.add(sub)
    db.session.flush()
    notify.set_prefs(user, {'channels': {'push': True}})
    db.session.commit()
    return jsonify(_notify_settings(user))


@app.route('/api/push/unsubscribe', methods=['POST'])
@require_auth
def push_unsubscribe():
    """This device stops getting push: {endpoint}."""
    user = current_user()
    PushSubscription.query.filter_by(user_id=user.id, endpoint=str((request.json or {}).get('endpoint') or '')).delete()
    db.session.commit()
    return jsonify(_notify_settings(user))


@app.route('/api/push/test', methods=['POST'])
@require_auth
def push_test():
    """Send yourself a test push on every device you turned it on for."""
    import notify
    sent = notify.push_to(current_user(), {'title': 'Push is on 🎬', 'body': "You'll get your Cinema Club alerts here.",
                                           'url': '/', 'tag': 'test'})
    return jsonify({'sent': sent})


@app.route('/api/me/notifications', methods=['GET', 'PUT'])
@require_auth
def my_notification_settings():
    import notify
    user = current_user()
    if request.method == 'PUT':
        notify.set_prefs(user, request.json or {})
        db.session.commit()
    return jsonify(_notify_settings(user))
