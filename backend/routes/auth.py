"""Signing in: email links, Discord, guest profiles, sessions.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
import app as core
from app import (AVATAR_COLORS, Attendance, FRONTEND_URL, GroupMembership, LoginToken, Message, PollVote,
    RSVP, Reaction, SharedRsvp, User, Watchlist, _update_profile_fields, _utcnow_naive, app, current_user,
    datetime, db, follow_discord_avatar, guest_blocked, hashlib, jsonify, merge_users, random, re, redirect,
    request, require_auth, secrets, session, time, timedelta, timezone, urlencode)


DISCORD_API = 'https://discord.com/api/v10'


def _start_session(user):
    """Sign `user` in. Clears any previous session first so a pre-existing
    cookie can't carry over."""
    session.clear()
    session.permanent = True
    session['user_id'] = user.id
    session['guest'] = bool(user.is_guest)
    session['seen'] = int(time.time())
GUEST_IDLE_LIMIT = timedelta(days=90)    # guests: the profile is deleted after this long away


# ─── Guest profiles (R5b) ─────────────────────────────────────────────────────
# A visitor's first RSVP, watchlist add or reaction makes a guest profile and
# signs them into it in this browser. It's private to them (no name, never in
# any club), lasts 90 days from their last visit, and becomes a full account
# when they add an email or Discord — or folds into the account they have.

GUEST_CAP_PER_HOUR = 5
GUEST_CAP_PER_DAY = 20


def _ip_hash():
    """A keyed hash of the visitor's address: enough to cap guest creation,
    useless for recovering the address."""
    return hashlib.sha256(f"{app.secret_key}|{_client_ip()}".encode()).hexdigest()


def _delete_guest(guest):
    for model in (RSVP, Watchlist, Reaction, Attendance, Message, PollVote, GroupMembership, SharedRsvp):
        model.query.filter_by(user_id=guest.id).delete(synchronize_session=False)
    LoginToken.query.filter_by(guest_user_id=guest.id).update({'guest_user_id': None}, synchronize_session=False)
    db.session.delete(guest)


def expire_guests(now=None):
    """Delete guest profiles nobody has used for GUEST_IDLE_LIMIT."""
    now = now or datetime.now()
    stale = User.query.filter(User.is_guest.is_(True), User.last_seen_at < now - GUEST_IDLE_LIMIT).limit(200).all()
    for g in stale:
        _delete_guest(g)
    return len(stale)


def absorb_guest(keep, guest):
    """Fold a guest profile into an existing account (the account's own rows
    win where both have one). Never touches the account's Discord link."""
    def move(model, *unique):
        for row in model.query.filter_by(user_id=guest.id).all():
            if model.query.filter_by(user_id=keep.id, **{c: getattr(row, c) for c in unique}).first():
                db.session.delete(row)
            else:
                row.user_id = keep.id
    move(RSVP, 'showtime_id', 'group_id')
    move(Watchlist, 'movie_id')
    move(Reaction, 'showtime_id', 'group_id', 'emoji')
    move(Attendance, 'showtime_id')
    if not keep.favorite_genres and guest.favorite_genres:
        keep.favorite_genres = guest.favorite_genres
    LoginToken.query.filter_by(guest_user_id=guest.id).update({'guest_user_id': None}, synchronize_session=False)
    db.session.flush()
    db.session.delete(guest)


def keep_guest(guest, **fields):
    """The guest profile becomes a full account (nothing moves)."""
    for k, v in fields.items():
        setattr(guest, k, v)
    guest.is_guest, guest.guest_ip_hash = False, None
    return guest


@app.route('/api/auth/guest', methods=['POST'])
def create_guest():
    """Make a guest profile and sign into it (or return whoever's signed in)."""
    user = current_user()
    if user:
        return jsonify({'user': user.to_dict()})
    h, now = _ip_hash(), _utcnow_naive()
    mine = User.query.filter(User.is_guest.is_(True), User.guest_ip_hash == h)
    if (mine.filter(User.created_at >= now - timedelta(hours=1)).count() >= GUEST_CAP_PER_HOUR
            or mine.filter(User.created_at >= now - timedelta(days=1)).count() >= GUEST_CAP_PER_DAY):
        return jsonify({'error': 'Too many new profiles from here — try again later.'}), 429
    expire_guests()
    guest = User(name='Guest', is_guest=True, is_active=True, avatar_color=random.choice(AVATAR_COLORS),
                 last_seen_at=datetime.now(), guest_ip_hash=h, created_at=now)
    db.session.add(guest)
    db.session.commit()
    _start_session(guest)
    return jsonify({'user': guest.to_dict()}), 201


# Emailed sign-in links: single-use, short-lived, rate-limited per address and
# per client so the form can't be used to flood someone's inbox.
SIGNIN_LINK_TTL = timedelta(minutes=15)
SIGNIN_RATE_WINDOW = timedelta(minutes=15)
SIGNIN_MAX_PER_EMAIL = 5
SIGNIN_MAX_PER_IP = 20
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _client_ip():
    """The real client address. Requests arrive via Cloudflare's tunnel and
    nginx, so remote_addr is a proxy; Cloudflare supplies the original IP."""
    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return (request.headers.get('CF-Connecting-IP') or forwarded or request.remote_addr or '')[:64]


def _issue_signin_link(email, purpose, name=None):
    """Create a one-time token and email its link. Returns an error response
    when rate-limited, otherwise None."""
    now = _utcnow_naive()
    since = now - SIGNIN_RATE_WINDOW
    ip = _client_ip()
    recent = LoginToken.query.filter(LoginToken.created_at > since)
    if (recent.filter(LoginToken.email == email).count() >= SIGNIN_MAX_PER_EMAIL
            or (ip and recent.filter(LoginToken.request_ip == ip).count() >= SIGNIN_MAX_PER_IP)):
        return jsonify({'error': 'Too many sign-in emails requested. Try again in 15 minutes.'}), 429

    token = secrets.token_urlsafe(32)
    asker = current_user()
    db.session.add(LoginToken(token_hash=_hash_token(token), email=email, purpose=purpose,
                              name=name, request_ip=ip, expires_at=now + SIGNIN_LINK_TTL,
                              guest_user_id=asker.id if asker and asker.is_guest else None))
    # Old rows only matter for rate limiting; keep the table small.
    LoginToken.query.filter(LoginToken.created_at < now - timedelta(days=1)).delete()
    db.session.commit()
    core.email_signin_link(email, f"{FRONTEND_URL}/auth/verify?token={token}", purpose)
    return None

# ─── Routes: Auth ─────────────────────────────────────────────────────────────

@app.route('/api/auth/accept-invite', methods=['POST'])
def accept_invite():
    data = request.json
    token = data.get('token')
    name = data.get('name', '').strip()

    if not token or not name:
        return jsonify({'error': 'Token and name required'}), 400

    user = User.query.filter_by(invite_token=token).first()
    if not user:
        return jsonify({'error': 'Invalid invite token'}), 404

    user.name = name
    user.is_active = True
    user.invite_token = None  # consume token
    db.session.commit()

    # The invite link was emailed to this address, so it proves ownership.
    _start_session(user)

    # Auto-add to groups if invited with a group association
    # Check if there's a pending membership waiting
    pending = GroupMembership.query.filter_by(user_id=user.id, status='pending').all()
    for m in pending:
        m.status = 'active'
    db.session.commit()

    return jsonify({'user': user.to_dict()})


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Step 1 of sign-in: email a one-time link. There's no password — opening
    the link proves the person controls the address. Step 2 is /api/auth/verify."""
    email = ((request.json or {}).get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    if not User.query.filter_by(email=email, is_active=True).first():
        return jsonify({'error': 'No active account for this email. Sign up or ask for an invite!'}), 404
    err = _issue_signin_link(email, 'login')
    if err:
        return err
    return jsonify({'sent': True, 'email': email})


@app.route('/api/auth/signup', methods=['POST'])
def signup():
    """Email a confirmation link; the account is created when it's opened."""
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    name = (data.get('name') or '').strip()[:100]

    if not email or not name:
        return jsonify({'error': 'Email and name are required'}), 400
    if not EMAIL_RE.match(email):
        return jsonify({'error': 'Enter a valid email address'}), 400
    if User.query.filter_by(email=email, is_active=True).first():
        return jsonify({'error': 'Account already exists. Try logging in!'}), 409

    err = _issue_signin_link(email, 'signup', name=name)
    if err:
        return err
    return jsonify({'sent': True, 'email': email})


@app.route('/api/auth/verify', methods=['POST'])
def verify_signin():
    """Step 2: redeem an emailed link (single use) and start the session. A
    signup link creates the account — or activates a never-accepted invite."""
    token = ((request.json or {}).get('token') or '').strip()
    rec = LoginToken.query.filter_by(token_hash=_hash_token(token)).first() if token else None
    now = _utcnow_naive()
    if not rec or rec.used_at or rec.expires_at < now:
        return jsonify({'error': 'This sign-in link is invalid, already used, or expired. '
                                 'Request a new one.'}), 400
    rec.used_at = now

    # A guest who asked for this link keeps their plans: the profile becomes the
    # new account, or folds into the existing one (works on any device).
    guest = db.session.get(User, rec.guest_user_id) if rec.guest_user_id else None
    if guest and not guest.is_guest:
        guest = None
    user = User.query.filter_by(email=rec.email).first()
    if rec.purpose == 'signup':
        if not user and guest:
            user = keep_guest(guest, email=rec.email, name=rec.name or rec.email.split('@')[0])
            guest = None
        elif not user:
            user = User(email=rec.email, name=rec.name or rec.email.split('@')[0],
                        avatar_color=random.choice(AVATAR_COLORS), is_active=True)
            db.session.add(user)
            db.session.flush()
        elif not user.is_active:
            # Orphaned invite: activate it, plus the group memberships it was invited to.
            user.name = rec.name or user.name
            user.is_active = True
            user.invite_token = None
            for m in GroupMembership.query.filter_by(user_id=user.id, status='pending').all():
                m.status = 'active'
    elif not user or not user.is_active:
        db.session.commit()
        return jsonify({'error': 'That account no longer exists.'}), 400

    if guest and guest.id != user.id:
        absorb_guest(user, guest)
    db.session.commit()
    _start_session(user)
    return jsonify({'user': user.to_dict()})


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'ok': True})


@app.route('/api/auth/me')
def me():
    user = current_user()
    if not user:
        return jsonify({'user': None})
    return jsonify({'user': user.to_dict()})


@app.route('/api/auth/profile', methods=['PUT'])
@require_auth
def update_profile():
    user = current_user()
    data = request.json

    if 'name' in data and data['name'].strip():
        user.name = data['name'].strip()[:100]
    if 'avatar_color' in data and data['avatar_color'] in AVATAR_COLORS:
        user.avatar_color = data['avatar_color']
    _update_profile_fields(user, data)

    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route('/api/me/discord-link-code', methods=['POST'])
@require_auth
def discord_link_code():
    """Generate a short-lived code the user types into Discord's /link command."""
    user = current_user()
    blocked = guest_blocked(user)
    if blocked:
        return blocked
    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
    user.discord_link_code = code
    user.discord_link_code_expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.session.commit()
    return jsonify({'code': code, 'expires_in_minutes': 10})


def _discord_oauth_enabled():
    return bool(core.DISCORD_CLIENT_ID and core.DISCORD_CLIENT_SECRET)


def _discord_redirect_uri():
    # nginx (and Vite in dev) proxy /api to Flask, so the callback lives on the site's origin.
    return f"{FRONTEND_URL}/api/auth/discord/callback"


@app.route('/api/auth/providers')
def auth_providers():
    """Which sign-in options the login page should offer."""
    return jsonify({'discord': _discord_oauth_enabled()})


@app.route('/api/auth/discord/start')
def discord_oauth_start():
    """Begin "Sign in with Discord" (mode=login), or "Connect Discord" for the
    signed-in user (mode=connect). Only the `identify` scope is requested."""
    if not _discord_oauth_enabled():
        return redirect(f"{FRONTEND_URL}/?{urlencode({'discord_error': 'unavailable'})}")
    viewer = current_user()
    mode = 'connect' if request.args.get('mode') == 'connect' and viewer and not viewer.is_guest else 'login'
    state = secrets.token_urlsafe(24)
    # Where to land afterwards: only a path on this site (never another host).
    nxt = request.args.get('next') or '/'
    nxt = nxt if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt else '/'
    session['discord_oauth'] = {'state': state, 'mode': mode, 'next': nxt[:300]}
    return redirect('https://discord.com/oauth2/authorize?' + urlencode({
        'client_id': core.DISCORD_CLIENT_ID, 'response_type': 'code', 'scope': 'identify',
        'redirect_uri': _discord_redirect_uri(), 'state': state, 'prompt': 'none',
    }))


@app.route('/api/auth/discord/callback')
def discord_oauth_callback():
    """Discord sends the browser back here. Login: sign into the account with
    that Discord id, creating a Discord-only one if needed (it joins groups the
    normal way). Connect: attach Discord to the signed-in account, merging a
    Discord-only account the member made through the bot."""
    import requests
    pending = session.pop('discord_oauth', None)

    def back(**params):
        # One line per attempt in `docker logs cinemaclub-backend`, so a failed
        # sign-in is never silent (no ids or codes logged).
        print(f"Discord {pending['mode'] if pending else 'sign-in'}: {params} -> {FRONTEND_URL}"
              f" (cookie {'present' if pending else 'missing'}, host {request.host})", flush=True)
        nxt = (pending or {}).get('next') or '/'
        return redirect(f"{FRONTEND_URL}{nxt}{'&' if '?' in nxt else '?'}{urlencode(params)}")

    if not pending or not request.args.get('state') or \
            not secrets.compare_digest(request.args['state'], pending['state']):
        return back(discord_error='expired')
    if request.args.get('error') or not request.args.get('code'):
        return back(discord_error='cancelled')
    try:
        token = requests.post(f'{DISCORD_API}/oauth2/token', timeout=10,
                              auth=(core.DISCORD_CLIENT_ID, core.DISCORD_CLIENT_SECRET),
                              data={'grant_type': 'authorization_code', 'code': request.args['code'],
                                    'redirect_uri': _discord_redirect_uri()})
        token.raise_for_status()
        me = requests.get(f'{DISCORD_API}/users/@me', timeout=10,
                          headers={'Authorization': f"Bearer {token.json()['access_token']}"})
        me.raise_for_status()
        me = me.json()
    except Exception as e:
        print(f'Discord sign-in failed: {e}')
        return back(discord_error='failed')

    discord_id = str(me['id'])
    name = (me.get('global_name') or me.get('username') or 'Discord member')[:100]
    avatar = (f"https://cdn.discordapp.com/avatars/{discord_id}/{me['avatar']}.png?size=128"
              if me.get('avatar') else None)
    existing = User.query.filter_by(discord_user_id=discord_id).first()

    if pending['mode'] == 'connect':
        user = current_user()
        if not user:
            return back(discord_error='signed_out')
        if existing and existing.id != user.id:
            if existing.email is not None:
                return back(discord_error='taken')
            merge_users(user, existing)
        user.discord_user_id = discord_id
        user.discord_username = (me.get('username') or '')[:40] or None
        follow_discord_avatar(user, avatar)
        db.session.commit()
        return back(discord='connected')

    viewer = current_user()
    guest = viewer if viewer and viewer.is_guest else None
    user = existing
    if user and not user.is_active:
        return back(discord_error='inactive')
    if not user and guest:                 # the guest profile becomes the account
        user = keep_guest(guest, discord_user_id=discord_id, name=name)   # picture: below
        guest = None
    elif not user:
        user = User(discord_user_id=discord_id, name=name, avatar_color=random.choice(AVATAR_COLORS),
                    is_active=True)
        db.session.add(user)
    if guest:                              # signing into an existing account: bring the guest's plans
        absorb_guest(user, guest)
    if user.email is None:             # Discord-only accounts track Discord's name
        user.name = name
    follow_discord_avatar(user, avatar)
    user.discord_username = (me.get('username') or '')[:40] or None
    db.session.commit()
    _start_session(user)
    return back(discord='signed_in')
