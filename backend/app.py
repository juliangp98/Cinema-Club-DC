from flask import Flask, jsonify, request, session, make_response, redirect, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
import time
import re
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from dotenv import load_dotenv
import sys as _sys

# Run directly (`python app.py`) this module is __main__; let `import app`
# (discover.py, the scrapers) find it instead of loading a second copy with
# its own database connection. Under gunicorn (`app:app`) it's already `app`.
_sys.modules.setdefault('app', _sys.modules[__name__])

# Load .env.development if it exists (local dev), otherwise .env (production/Docker)
env_file = os.path.join(os.path.dirname(__file__), '.env.development')
if os.path.exists(env_file):
    load_dotenv(env_file)
else:
    load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
if not os.environ.get('SECRET_KEY'):
    # A per-process random key means each gunicorn worker signs sessions
    # differently (random logouts) and every restart logs everyone out.
    print('⚠️  SECRET_KEY is not set — sessions will not survive restarts or '
          'work across workers. Set it in .env.production.')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///cinemaclub.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Sign-ins last 30 days (sessions are marked permanent at sign-in).
# The cookie lasts 90 days (guest profiles live in it); members' sessions
# still end after MEMBER_IDLE_LIMIT without a visit (see _session_upkeep).
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=90)
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024     # picture uploads are capped at 5 MB (media.py)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FRONTEND_URL', '').startswith('https://')

CORS(app, supports_credentials=True, origins=["http://localhost:5173", os.environ.get('FRONTEND_URL', '')])

db = SQLAlchemy(app)

# ─── Constants ────────────────────────────────────────────────────────────────

AVATAR_COLORS = ['#e8a838', '#c45c3a', '#4a7c6f', '#7b5ea7', '#3a6bb5', '#b5503a']

GENRE_LIST = [
    'action', 'comedy', 'drama', 'horror', 'sci-fi', 'thriller',
    'documentary', 'animation', 'romance', 'classic', 'foreign',
    'indie', 'experimental', 'mystery', 'fantasy', 'musical', 'war',
    'western', 'noir', 'biographical'
]

CINEMA_EMOJIS = [
    '\U0001F37F', '\U0001F3AC', '\U0001F44F', '\U0001F602', '\U0001F622',
    '\U0001F631', '\U0001F525', '\U0001F480', '\u2764\uFE0F', '\U0001F44E',
    '\U0001F44D', '\U0001F60D', '\U0001F914', '\U0001F634',
    '\U0001F1FA\U0001F1F8', '\U0001F1F2\U0001F1FD', '\U0001F1EF\U0001F1F5',
    '\U0001F1F0\U0001F1F7', '\U0001F1EB\U0001F1F7', '\U0001F1EE\U0001F1F9',
    '\U0001F1EC\U0001F1E7',
    '\U0001FAC3', '\U0001FAC4', '\U0001F930',
]

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173')
# Web push (R8d): a key pair made once with `python vapid_keys.py`. Without
# it, push simply isn't offered.
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_SUBJECT = os.environ.get('VAPID_SUBJECT', 'mailto:alerts@cinemaclubdc.com')
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
TMDB_API_TOKEN = os.environ.get('TMDB_API_TOKEN', '')
OMDB_API_KEY = os.environ.get('OMDB_API_KEY', '')
INTERNAL_API_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')
# "Sign in with Discord" — the bot's own application (OAuth2 tab in the portal).
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')


# ─── Email Helper ─────────────────────────────────────────────────────────────

def send_email(to, subject, html_body):
    """Send an email via Gmail SMTP. Falls back to console if SMTP not configured."""
    if not to:
        return  # Discord-only accounts have no email address
    subject = ' '.join(str(subject).split())        # one line: a name can't add headers
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"\n📧 EMAIL (console fallback — set SMTP_EMAIL & SMTP_PASSWORD to send for real)")
        print(f"   To: {to}")
        print(f"   Subject: {subject}")
        print(f"   Body: {html_body[:200]}...")
        # Print links in full — locally this is how you open sign-in links.
        for link in re.findall(r'href="([^"]+)"', html_body):
            print(f"   Link: {link}")
        print(flush=True)  # don't let stdout buffering hide the link
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Cinema Club DC <{SMTP_EMAIL}>"
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to, msg.as_string())
        print(f"📧 Email sent to {to}: {subject}")
    except Exception as e:
        print(f"⚠️  Email failed to {to}: {e}")


def email_signin_link(to_email, link_url, purpose):
    if purpose == 'signup':
        subject, intro, button = ('Confirm your Cinema Club DC account',
                                  'Confirm your email to finish creating your account.',
                                  'Confirm &amp; Sign In')
    else:
        subject, intro, button = ('Your Cinema Club DC sign-in link',
                                  'Use this link to sign in.', 'Sign In')
    send_email(to_email, subject,
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>{intro} It works once and expires in 15 minutes.</p>
        <p><a href="{link_url}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">{button}</a></p>
        <p style="color:#888;font-size:13px;">If you didn't ask for this, you can ignore this email —
        nobody can sign in without this link.</p>
        </div>""")

from models import (  # noqa: E402 — the tables (models.py), re-exported
    ActivityEvent, Announcement, Attendance, BotSetting, DiscordDeletion, DiscordPost, DiscordServerMember,
    Group, GroupMembership, KernelGift, LoginToken, Message, Movie, MovieAlias, Notification, Poll, PollCategory,
    PollDraft, PollOption, PollVote, PushSubscription, Quote, RSVP, Reaction, SavedSearch, SavedSearchHit,
    ScrapeEvent, ScrapeRun, SharedRsvp, Showtime, ShowtimeThread, Theatre, TriviaAnswer, TriviaQuestion, User,
    Watchlist)



def face(u):
    """What an avatar needs: color for initials, and the picture if any."""
    return {'avatar_color': u.avatar_color, 'avatar_url': u.avatar_url, 'avatar_emoji': u.avatar_emoji}


def follow_discord_avatar(user, url):
    """Remember a member's Discord picture, and show it unless they chose
    something else (a photo, an emoji or initials)."""
    if not url:
        return
    user.discord_avatar_url = url[:500]
    if user.avatar_kind in (None, 'discord'):
        user.avatar_url = url[:500]


# ─── Auth ─────────────────────────────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*args, **kwargs)
    return decorated

def current_user():
    return db.session.get(User, session['user_id']) if 'user_id' in session else None


MEMBER_IDLE_LIMIT = timedelta(days=30)   # members: signed out after this long away


@app.before_request
def _session_upkeep():
    """Members' sessions end after MEMBER_IDLE_LIMIT away (the cookie itself
    lasts 90 days, for guests); guests' last visit is recorded, daily, for
    expiry."""
    if 'user_id' not in session:
        return
    now = int(time.time())
    if not session.get('guest') and now - session.get('seen', now) > MEMBER_IDLE_LIMIT.total_seconds():
        session.clear()
        return
    if now - session.get('seen', 0) > 3600:
        session['seen'] = now
    if session.get('guest') and now - session.get('touched', 0) > 86400:
        session['touched'] = now
        User.query.filter_by(id=session['user_id'], is_guest=True).update({'last_seen_at': datetime.now()})
        db.session.commit()


def guest_blocked(user):
    """Clubs see names, so joining or starting one needs a kept profile."""
    if user and user.is_guest:
        return jsonify({'error': 'Keep your profile first (add an email or Discord) to join a club.', 'code': 'guest'}), 403
    return None


def _active_membership(user, group_id):
    if not user or not group_id:
        return None
    return GroupMembership.query.filter_by(user_id=user.id, group_id=group_id, status='active').first()


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def utc_iso(dt):
    """Activity timestamps are stored as naive UTC; mark them as UTC so browsers
    don't read them as local time. (Showtimes are naive local and stay as-is.)"""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def merge_users(keep, gone):
    """Fold account `gone` (a Discord-only account) into `keep` when someone
    links Discord to their site account. Everything moves over; where both
    accounts have the same row (an RSVP to one screening, a vote in one
    category) `keep`'s wins. Memberships merge to the stronger of the two."""
    def move(model, *unique_cols):
        for row in model.query.filter_by(user_id=gone.id).all():
            clash = (model.query.filter_by(user_id=keep.id, **{c: getattr(row, c) for c in unique_cols}).first()
                     if unique_cols else None)
            if clash:
                db.session.delete(row)
            else:
                row.user_id = keep.id

    move(RSVP, 'showtime_id', 'group_id')
    move(Attendance, 'showtime_id')
    move(Watchlist, 'movie_id')
    move(Reaction, 'showtime_id', 'group_id', 'emoji')
    move(Message)
    move(PollVote, 'category_id', 'rank')
    for m in GroupMembership.query.filter_by(user_id=gone.id).all():
        mine = GroupMembership.query.filter_by(user_id=keep.id, group_id=m.group_id).first()
        if not mine:
            m.user_id = keep.id
            continue
        if m.status == 'active':
            mine.status = 'active'
        if m.role == 'admin':
            mine.role = 'admin'
        db.session.delete(m)
    Group.query.filter_by(created_by=gone.id).update({'created_by': keep.id})
    Poll.query.filter_by(created_by=gone.id).update({'created_by': keep.id})
    for col in ('added_by', 'updated_by', 'deleted_by'):
        Quote.query.filter(getattr(Quote, col) == gone.id).update({col: keep.id})

    for col in ('favorite_genres', 'bio', 'letterboxd_username', 'avatar_url'):
        if not getattr(keep, col) and getattr(gone, col):
            setattr(keep, col, getattr(gone, col))
    discord_id, handle = gone.discord_user_id, gone.discord_username
    gone.discord_user_id = None
    db.session.flush()                 # free the unique Discord id first
    keep.discord_user_id = discord_id
    keep.discord_username = keep.discord_username or handle
    db.session.delete(gone)


# ─── Club roles (R5c) ─────────────────────────────────────────────────────────
# Each role includes the ones below it. Admins grant and revoke them.
#   viewer     read-only: sees the club (who's going, feed, polls, comments)
#   member     + RSVP, vote, comment, react, "who's in?" and thread starts
#   organizer  + create / run / score / delete polls and post them to Discord
#   admin      + members, invites, roles, club settings, deleting the club
ROLES = ('viewer', 'member', 'organizer', 'admin')
ROLE_RANK = {r: i for i, r in enumerate(ROLES)}
ROLE_LABELS = {'viewer': 'Read-only', 'member': 'Member', 'organizer': 'Organizer', 'admin': 'Admin'}


def role_at_least(membership, role):
    return bool(membership and membership.status == 'active'
                and ROLE_RANK.get(membership.role, ROLE_RANK['member']) >= ROLE_RANK[role])


def require_role(user, group_id, role):
    """(membership, error): `user` must hold at least `role` in the club."""
    m = _active_membership(user, group_id)
    if not m:
        return None, (jsonify({'error': 'Not a member of this group'}), 403)
    if not role_at_least(m, role):
        if role == 'member':
            return m, (jsonify({'error': "You're read-only in this club. Ask an admin to change that.",
                                'code': 'read_only'}), 403)
        return m, (jsonify({'error': f'{ROLE_LABELS[role]} access required', 'code': 'role'}), 403)
    return m, None


def require_group_member(group_id):
    """Group-scoped web routes (showtimes, RSVPs, reactions, discussion) must
    name a group the signed-in user actively belongs to — the client-supplied
    group_id is never trusted on its own. Returns an error response, or None."""
    if not group_id:
        return jsonify({'error': 'group_id required'}), 400
    if not _active_membership(current_user(), group_id):
        return jsonify({'error': 'Not a member of this group'}), 403
    return None


# ─── Pictures (R6b) ───────────────────────────────────────────────────────────
# Members and clubs pick a photo, an emoji, or initials. Photos are processed
# and stored by media.py; uploads are limited per person.

UPLOADS_PER_HOUR = 20
_uploads = {}              # user id -> recent upload times (per server process)


def _upload_allowed(user):
    now = time.monotonic()
    recent = [t for t in _uploads.get(user.id, []) if now - t < 3600]
    _uploads[user.id] = recent
    if len(recent) >= UPLOADS_PER_HOUR:
        return False
    recent.append(now)
    return True


def _upload(kind):
    """(url, error response) for the request's uploaded file."""
    import media
    f = request.files.get('file')
    if not f:
        return None, (jsonify({'error': 'Choose a picture to upload.'}), 400)
    if not _upload_allowed(current_user()):
        return None, (jsonify({'error': "That's a lot of uploads. Try again in a while."}), 429)
    try:
        return media.save(app.instance_path, f.read(media.MAX_BYTES + 1), kind), None
    except media.BadImage as e:
        return None, (jsonify({'error': str(e)}), 400)


@app.errorhandler(413)
def too_large(_):
    return jsonify({'error': 'That file is over 5 MB. Try a smaller one.'}), 413


def _update_profile_fields(user, data):
    """Bio, favorite genres and Letterboxd handle — shared by the site's profile
    menu and Discord's /profile. Genres may be a comma string or a list."""
    if 'bio' in data:
        user.bio = (data['bio'] or '').strip()[:500]
    if 'favorite_genres' in data:
        raw = data['favorite_genres'] or []
        raw = raw.split(',') if isinstance(raw, str) else raw
        picked = {g.strip().lower() for g in raw}
        user.favorite_genres = ','.join(g for g in GENRE_LIST if g in picked)
    if 'letterboxd_username' in data:
        handle = re.sub(r'[^A-Za-z0-9_]', '', (data['letterboxd_username'] or ''))[:60]
        user.letterboxd_username = handle or None


def _with_attendance(user, showtimes, dicts, group_id=None):
    """Add the viewer's own went/missed answer to each showtime dict, and (given
    the group) the link to its Discord thread, if there is one — one query each."""
    ids = [s.id for s in showtimes]
    answers = {a.showtime_id: a.status for a in Attendance.query.filter(
        Attendance.user_id == user.id, Attendance.showtime_id.in_(ids))} if ids else {}
    threads = {t.showtime_id: t.url for t in ShowtimeThread.query.filter(
        ShowtimeThread.group_id == group_id, ShowtimeThread.showtime_id.in_(ids))} if ids and group_id else {}
    shares = discord_states(user, ids, group_id)
    for d in dicts:
        d['user_attendance'] = answers.get(d['id'])
        d['discord_thread_url'] = threads.get(d['id'])
        d['discord'] = shares.get(d['id'])       # None outside the Discord server's group
    return dicts


def _brief_user(u):
    return {'id': u.id, 'name': u.name, **face(u)}


# ─── Discover (shelves, browse, surprise) ─────────────────────────────────────
# The engine lives in discover.py; the bot's internal routes use it too.

# ─── Public mode (R5a) ────────────────────────────────────────────────────────
# What's playing is public; what members do is not. Every schedule route reads
# its scope here: with ?group_id it's club mode (active membership required,
# exactly as before); without it, public mode — all tracked theatres, and
# screenings serialized by public_showtimes(), which never carries names, ids,
# RSVPs, reactions, comments or Discord links. Only anonymous counts, and only
# from PUBLIC_MIN_COUNT up, so "1 going" can't point at someone.

PUBLIC_MIN_COUNT = 3
PUBLIC_CACHE_SECONDS = 300
_public_cache = {}


def _public_count(n):
    return n if n and n >= PUBLIC_MIN_COUNT else None


def interest_counts(movie_ids=(), showtime_ids=()):
    """Anonymous interest: ({movie_id: want}, {showtime_id: going}), counted
    across every account (all clubs and personal plans — not guests, so
    throwaway profiles can't inflate them), small numbers withheld."""
    want, going = {}, {}
    accounts = db.session.query(User.id).filter(User.is_guest.isnot(True))
    if movie_ids:
        want = {mid: _public_count(n) for mid, n in db.session.query(Watchlist.movie_id, db.func.count(db.distinct(Watchlist.user_id)))
                .filter(Watchlist.movie_id.in_(set(movie_ids)), Watchlist.user_id.in_(accounts)).group_by(Watchlist.movie_id)}
    if showtime_ids:
        going = {sid: _public_count(n) for sid, n in db.session.query(RSVP.showtime_id, db.func.count(db.distinct(RSVP.user_id)))
                 .filter(RSVP.showtime_id.in_(set(showtime_ids)), RSVP.status == 'going', RSVP.user_id.in_(accounts))
                 .group_by(RSVP.showtime_id)}
    return want, going


def public_reactions(showtime_ids, viewer=None):
    """{showtime_id: {emoji: {count, users: [], user_reacted}}}: anonymous
    totals across every account (from PUBLIC_MIN_COUNT up), plus the viewer's
    own personal reactions."""
    out = {sid: {} for sid in showtime_ids}
    if not showtime_ids:
        return out
    accounts = db.session.query(User.id).filter(User.is_guest.isnot(True))
    for sid, emoji, n in (db.session.query(Reaction.showtime_id, Reaction.emoji, db.func.count(db.distinct(Reaction.user_id)))
                          .filter(Reaction.showtime_id.in_(showtime_ids), Reaction.user_id.in_(accounts))
                          .group_by(Reaction.showtime_id, Reaction.emoji)):
        if _public_count(n):
            out[sid][emoji] = {'count': n, 'users': [], 'user_reacted': False}
    if viewer:
        for r in Reaction.query.filter(Reaction.user_id == viewer.id, Reaction.group_id.is_(None),
                                       Reaction.showtime_id.in_(showtime_ids)):
            out[r.showtime_id].setdefault(r.emoji, {'count': None, 'users': [], 'user_reacted': False})['user_reacted'] = True
    return out


def public_showtimes(showtimes, viewer=None):
    """Screenings for public mode. Same shape as the club serializer (so the
    site renders either), with every member field empty."""
    ids = [s.id for s in showtimes]
    want, going = interest_counts({s.movie_id for s in showtimes}, ids)
    genres = {g.strip().lower() for g in ((viewer.favorite_genres if viewer else '') or '').split(',') if g.strip()}
    # The viewer's own personal plans (R5b) — never anyone else's.
    mine = {r.showtime_id: r.status for r in RSVP.query.filter(
        RSVP.user_id == viewer.id, RSVP.group_id.is_(None), RSVP.showtime_id.in_(ids))} if viewer and ids else {}
    went = {a.showtime_id: a.status for a in Attendance.query.filter(
        Attendance.user_id == viewer.id, Attendance.showtime_id.in_(ids))} if viewer and ids else {}
    reactions = public_reactions(ids, viewer)
    out = []
    for s in showtimes:
        movie_genres = {g.strip().lower() for g in (s.movie.genres or '').split(',') if g.strip()}
        out.append({
            'id': s.id, 'movie': s.movie.to_dict(), 'theatre': s.theatre.to_dict(),
            'start_time': s.start_time.isoformat(), 'end_time': s.end_time.isoformat() if s.end_time else None,
            'purchase_link': s.purchase_link, 'is_sold_out': s.is_sold_out,
            'format_label': s.format_label, 'event_label': s.event_label,
            'attendees': [], 'maybes': [], 'user_rsvp': mine.get(s.id), 'reactions': reactions.get(s.id, {}),
            'message_count': 0, 'user_attendance': went.get(s.id), 'discord_thread_url': None, 'discord': None,
            'recommended': bool(genres & movie_genres),          # the viewer's own genres only
            'interest': {'going': going.get(s.id), 'want': want.get(s.movie_id)},
            'public': True,
        })
    return out


def public_cached(key, build):
    """Anonymous public responses, cached briefly per worker (the warm-up
    loop below rebuilds the common ones before they expire)."""
    hit = _public_cache.get(key)
    now = time.monotonic()
    rewarm = bool(INTERNAL_API_TOKEN) and request.headers.get('X-Internal-Token') == INTERNAL_API_TOKEN \
        and request.headers.get('X-Warm') == '1'
    if hit and now - hit[0] < PUBLIC_CACHE_SECONDS and not rewarm:
        return hit[1]
    value = build()
    if len(_public_cache) > 500:
        _public_cache.clear()
    _public_cache[key] = (now, value)
    return value


# ─── Search (R6c) ─────────────────────────────────────────────────────────────
# Suggestions as you type (everyone), and ✨ AI search (kept accounts only: it
# spends the club's shared AI allowance, which the chatbot and poll drafts use too).

# ─── Any film on TMDB (R8c) ───────────────────────────────────────────────────
# Watchlist films no DC theatre has listed (yet): search TMDB, and open one
# (it's added to the catalog then; when a theatre books it, the scraper finds
# it by its TMDB id and its watchers hear).

TMDB_SEARCHES_PER_HOUR = 120
TMDB_CACHE_SECONDS = 3600
_tmdb_searches, _tmdb_cache = {}, {}


def tmdb_matches(q, who):
    """TMDB's films for `q` (cached an hour), each with our movie_id if we
    have it. None if `who` searched too much this hour."""
    import discover
    from enrich import tmdb_search_list
    key = discover.normalize(q)
    now = time.monotonic()
    hit = _tmdb_cache.get(key)
    if not hit or now - hit[0] > TMDB_CACHE_SECONDS:
        recent = [t for t in _tmdb_searches.get(who, []) if now - t < 3600]
        if len(recent) >= TMDB_SEARCHES_PER_HOUR:
            return None
        _tmdb_searches[who] = recent + [now]
        if len(_tmdb_cache) > 2000:
            _tmdb_cache.clear()
        hit = _tmdb_cache[key] = (now, tmdb_search_list(q))
    results = hit[1]
    ids = [r['tmdb_id'] for r in results]
    known = {m.tmdb_id: m.id for m in Movie.query.filter(Movie.tmdb_id.in_(ids))} if ids else {}
    return [{**r, 'movie_id': known.get(r['tmdb_id'])} for r in results]


def movie_for_tmdb(tmdb_id):
    """Our Movie for a TMDB film, added (with TMDB's details) if we don't have it."""
    from enrich import enrich_by_tmdb_id
    from scrapers.sync import _apply_movie_fields
    movie = Movie.query.filter_by(tmdb_id=tmdb_id).first()
    if movie:
        return movie
    details = enrich_by_tmdb_id(tmdb_id)
    if not details:
        return None
    movie = Movie(title=(details.get('tmdb_title') or '')[:200] or 'Untitled')
    _apply_movie_fields(movie, {}, details)
    db.session.add(movie)
    try:
        db.session.commit()
    except IntegrityError:                       # added by a simultaneous request
        db.session.rollback()
        movie = Movie.query.filter_by(tmdb_id=tmdb_id).first()
    return movie
_ai_searches = {}            # user id -> recent search times (per server process)


# ─── Routes: RSVP ─────────────────────────────────────────────────────────────

def apply_rsvp(user, showtime_id, status, group_id):
    """Shared RSVP logic for the web route and the Discord bot's internal route.
    Returns (showtime, error_response)."""
    if not showtime_id:
        return None, (jsonify({'error': 'showtime_id required'}), 400)

    showtime = db.session.get(Showtime, showtime_id)
    if not showtime:
        return None, (jsonify({'error': 'Showtime not found'}), 404)

    existing = RSVP.query.filter_by(user_id=user.id, showtime_id=showtime_id, group_id=group_id).first()

    if status is None:
        if existing:
            db.session.delete(existing)
            db.session.commit()
    elif status in ('going', 'maybe', 'not_going'):
        if existing:
            if existing.status != status:
                existing.updated_at = datetime.now(timezone.utc)   # bumps it in the Feed
            existing.status = status
        else:
            new_rsvp = RSVP(user_id=user.id, showtime_id=showtime_id, group_id=group_id, status=status)
            db.session.add(new_rsvp)
        db.session.commit()
    else:
        return None, (jsonify({'error': 'Invalid status'}), 400)

    # The screening's thread card in Discord lists who's going: refresh it,
    # and any shared RSVP post or "who's in?" invite showing this screening.
    thread = ShowtimeThread.query.filter_by(showtime_id=showtime_id, group_id=group_id).first()
    if thread and not thread.card_dirty:
        thread.card_dirty = True
    rsvp_changed(user.id, showtime_id, group_id, status)
    db.session.commit()
    return db.session.get(Showtime, showtime_id), None


# ─── Choose what goes to Discord (R3d) ────────────────────────────────────────
# Nothing done on the site posts to #movies unless the member chooses to: per
# kind, "ask" (a prompt after acting), "always" or "never" (a Share button is
# still there). Each post is a DiscordPost the bot works through; it stays in
# step with the site (edited when an RSVP or poll changes, deleted when what it
# shows is gone) and never @-pings anyone. Only the group tied to the club's
# Discord server (DEFAULT_GROUP_ID, shared with the bot) has any of this.
#
# And only members who've linked Discord AND are in that server (on_discord)
# ever appear there: their own shares, comments, names in lists, pings. Anyone
# else is at most a count ("+2 on the site"), whatever their settings say.

DISCORD_GROUP_ID = int(os.environ.get('DEFAULT_GROUP_ID', '1') or 1)
SHARE_KINDS = ('rsvp', 'poll', 'comment', 'watchlist')
SHARE_CHOICES = ('ask', 'always', 'never')
RSVP_BATCH_WAIT = timedelta(seconds=60)    # quick RSVPs in a row become one post...
RSVP_BATCH_MAX = timedelta(minutes=5)      # ...but none waits longer than this
LIVE_POSTS = ('pending', 'posted')
MAX_SCHEDULE = timedelta(days=60)


def share_prefs(user):
    import json
    try:
        raw = json.loads(user.share_prefs or '{}')
    except ValueError:
        raw = {}
    return {k: raw[k] if raw.get(k) in SHARE_CHOICES else 'ask' for k in SHARE_KINDS}


def set_share_pref(user, kind, value):
    import json
    if kind in SHARE_KINDS and value in SHARE_CHOICES:
        prefs = share_prefs(user)
        prefs[kind] = value
        user.share_prefs = json.dumps(prefs)


def discord_group(group_id):
    return bool(group_id) and group_id == DISCORD_GROUP_ID


def _present():
    """(discord ids in the server, site user ids among them), once per request."""
    from flask import g, has_request_context
    if has_request_context() and getattr(g, 'discord_present', None) is not None:
        return g.discord_present
    ids = {r[0] for r in db.session.query(DiscordServerMember.discord_user_id)}
    users = {r[0] for r in db.session.query(User.id).filter(User.discord_user_id.in_(ids))} if ids else set()
    if has_request_context():
        g.discord_present = (ids, users)
    return ids, users


def on_discord(user):
    """Linked to Discord and in the club's server: the only people Discord sees."""
    return bool(user and user.discord_user_id and user.discord_user_id in _present()[0])


def present_user_ids():
    return _present()[1]


def can_share(user, group_id):
    """May this member's own actions go to the server at all?"""
    return discord_group(group_id) and on_discord(user)


def split_present(users):
    """(people Discord may see, how many others) — for name lists."""
    shown = [u for u in users if u and u.id in present_user_ids()]
    return shown, len(users) - len(shown)


def watch_shared(w):
    """May the digest name or ping this watchlist entry's owner? Only if they're
    on Discord, and their "watchlist" choice (or their answer for this film) says so."""
    if not on_discord(w.user):
        return False
    pref = share_prefs(w.user)['watchlist']
    if pref == 'never':
        return False
    return w.share_discord if w.share_discord is not None else pref == 'always'


def post_dict(p):
    return {'id': p.id, 'kind': p.kind, 'status': p.status, 'post_at': p.post_at.isoformat(),
            'posted_at': p.posted_at.isoformat() if p.posted_at else None, 'jump_url': p.jump_url,
            'note': p.note, 'by': {'id': p.user.id, 'name': p.user.name}}


def queue_rsvp_share(user, showtime_id, group_id, now=None):
    """Share an RSVP. Several in quick succession go out as one post."""
    now = now or datetime.now()
    item = (SharedRsvp.query.join(DiscordPost)
            .filter(SharedRsvp.user_id == user.id, SharedRsvp.showtime_id == showtime_id,
                    DiscordPost.group_id == group_id, DiscordPost.status.in_(LIVE_POSTS)).first())
    if item:
        return item.post
    post = (DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.kind == 'rsvp',
                                     DiscordPost.user_id == user.id, DiscordPost.status == 'pending',
                                     DiscordPost.created_at >= now - RSVP_BATCH_MAX)
            .order_by(DiscordPost.id.desc()).first())
    if post:
        post.post_at = min(now + RSVP_BATCH_WAIT, post.created_at + RSVP_BATCH_MAX)
    else:
        post = DiscordPost(group_id=group_id, kind='rsvp', user_id=user.id, post_at=now + RSVP_BATCH_WAIT,
                           created_at=now)
        db.session.add(post)
    post.rsvps.append(SharedRsvp(user_id=user.id, showtime_id=showtime_id))
    db.session.commit()
    return post


def unshare_rsvp(user_id, showtime_id, group_id):
    """Take one screening out of someone's RSVP posts: dropped before it goes
    out, or edited out of the Discord post (deleted if it was the last)."""
    items = (SharedRsvp.query.join(DiscordPost)
             .filter(SharedRsvp.user_id == user_id, SharedRsvp.showtime_id == showtime_id,
                     DiscordPost.group_id == group_id, DiscordPost.status.in_(LIVE_POSTS)).all())
    for it in items:
        post = it.post
        post.rsvps.remove(it)
        if post.status == 'pending':
            if not post.rsvps:
                post.status = 'cancelled'
        else:
            post.dirty = True
    return bool(items)


def rsvp_changed(user_id, showtime_id, group_id, status):
    """Keep posts in step with an RSVP change (from the site or Discord)."""
    if status not in ('going', 'maybe'):
        unshare_rsvp(user_id, showtime_id, group_id)
    else:
        for it in (SharedRsvp.query.join(DiscordPost)
                   .filter(SharedRsvp.user_id == user_id, SharedRsvp.showtime_id == showtime_id,
                           DiscordPost.group_id == group_id, DiscordPost.status == 'posted')):
            it.post.dirty = True
    DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.kind == 'invite',
                             DiscordPost.ref_id == showtime_id, DiscordPost.status == 'posted') \
        .update({'dirty': True}, synchronize_session=False)


def poll_payload(poll, results=False):
    """What a poll announcement / results post shows (plain names: no pings;
    members who aren't on Discord stay unnamed)."""
    payload = {'poll_id': poll.id, 'group_id': poll.group_id, 'title': poll.title, 'status': poll.status,
               'poll_type': poll.poll_type, 'scoring_mode': poll.scoring_mode,
               'categories': len(poll.categories), 'creator': poll.creator.name if on_discord(poll.creator) else None}
    if results:
        board = poll_scores(poll)
        payload['voters'] = len(board)
        payload['top'] = [{'name': s['user'].name if on_discord(s['user']) else None,
                           'kernels': s['kernels'], 'correct': s['correct']} for s in board[:3]]
    return payload


def _brief_screening(s):
    return {'showtime_id': s.id, 'title': s.movie.title, 'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label}


def render_post(p, now=None):
    """What a post shows right now, or None when there's nothing left to show
    (the bot then deletes it, or never posts it)."""
    now = now or datetime.now()
    if p.status == 'removing':
        return None
    if p.kind == 'rsvp':
        items = []
        for it in p.rsvps:
            r = RSVP.query.filter_by(user_id=it.user_id, showtime_id=it.showtime_id, group_id=p.group_id).first()
            s = db.session.get(Showtime, it.showtime_id)
            if r and s and r.status in ('going', 'maybe') and not s.is_cancelled:
                items.append({**_brief_screening(s), 'status': r.status})
        items.sort(key=lambda x: x['start_time'])
        return {'user': p.user.name, 'items': items} if items and on_discord(p.user) else None
    if p.kind in ('invite', 'thread'):
        s = db.session.get(Showtime, p.ref_id or 0)
        if not s or s.is_cancelled:
            return None
        if p.kind == 'thread':
            return {'showtime_id': s.id}
        card = screening_card(s, p.group_id)
        for who in ('going', 'maybe'):
            card[who] = [{'name': x['name']} for x in card[who]]      # names only: no pings
        return {'by': p.user.name if on_discord(p.user) else None, 'note': p.note, 'card': card,
                'started': s.start_time <= now}
    poll = db.session.get(Poll, p.ref_id or 0)
    if not poll:
        return None
    if p.kind == 'poll':
        return poll_payload(poll)
    if p.kind == 'poll_results':
        return poll_payload(poll, results=True) if poll.status == 'scored' else None
    return None


def _parse_post_at(value, now):
    """'Now' (None) or a local date-time from the site's picker."""
    if not value:
        return now
    try:
        at = datetime.fromisoformat(str(value).replace('Z', ''))
    except ValueError:
        return None
    if at.tzinfo:
        at = at.astimezone().replace(tzinfo=None)
    if at < now - timedelta(minutes=5) or at > now + MAX_SCHEDULE:
        return None
    return max(at, now)


def _live_post(kind, ref_id, group_id):
    return (DiscordPost.query.filter(DiscordPost.kind == kind, DiscordPost.ref_id == ref_id,
                                     DiscordPost.group_id == group_id, DiscordPost.status.in_(LIVE_POSTS))
            .order_by(DiscordPost.id.desc()).first())


def queue_poll_post(poll, user, kind, post_at):
    existing = _live_post(kind, poll.id, poll.group_id)
    if existing:
        return existing
    post = DiscordPost(group_id=poll.group_id, kind=kind, user_id=user.id, ref_id=poll.id, post_at=post_at)
    db.session.add(post)
    db.session.commit()
    return post


def announce_new_poll(poll, user, data):
    """A new poll's announcement: now, later, or not yet, as the creator chose
    on the form ("announce": now | later | none, "announce_at"). Without a
    choice, their poll preference decides ("ask" means not yet)."""
    if not can_share(user, poll.group_id):
        return
    choice = data.get('announce')
    if choice not in ('now', 'later', 'none'):
        choice = 'now' if share_prefs(user)['poll'] == 'always' else 'none'
    if choice == 'none':
        return
    now = datetime.now()
    at = _parse_post_at(data.get('announce_at'), now) if choice == 'later' else now
    queue_poll_post(poll, user, 'poll', at or now)


def discord_states(user, showtime_ids, group_id):
    """{showtime_id: discord block} for the viewer: their shared RSVP post, any
    "who's in?" invite, and whether a thread is being started. Nothing for
    members who aren't in the club's Discord server: they can't share there."""
    if not can_share(user, group_id) or not showtime_ids:
        return {}
    mine = {it.showtime_id: it.post for it in SharedRsvp.query.join(DiscordPost).filter(
        SharedRsvp.user_id == user.id, SharedRsvp.showtime_id.in_(showtime_ids),
        DiscordPost.group_id == group_id, DiscordPost.status.in_(LIVE_POSTS))}
    invites, threads = {}, set()
    for p in DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.kind.in_(('invite', 'thread')),
                                      DiscordPost.ref_id.in_(showtime_ids), DiscordPost.status.in_(LIVE_POSTS)) \
            .order_by(DiscordPost.id):
        if p.kind == 'invite':
            invites[p.ref_id] = p
        elif p.status == 'pending':
            threads.add(p.ref_id)
    return {sid: {'my_share': post_dict(mine[sid]) if sid in mine else None,
                  'invite': post_dict(invites[sid]) if sid in invites else None,
                  'thread_pending': sid in threads}
            for sid in showtime_ids}


# ─── Attendance ("did you go?") + watch history ──────────────────────────────

ATTENDANCE_ASK_AFTER = timedelta(hours=2)   # ask once a screening has been over this long
ATTENDANCE_LOOKBACK = timedelta(days=7)     # ...but never about anything older


def _screening_end(s):
    return s.end_time or s.start_time + timedelta(minutes=(s.movie.runtime_minutes or 120) + 20)


def pending_attendance(user, include_prompted=True):
    """Screenings `user` RSVP'd going to that ended 2h+ ago, within the past
    week, and they haven't said whether they made it — oldest first.
    include_prompted=False leaves out ones the bot already asked about."""
    now = datetime.now()
    rsvps = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
             .filter(RSVP.user_id == user.id, RSVP.status == 'going',
                     Showtime.is_cancelled.isnot(True),
                     Showtime.start_time >= now - ATTENDANCE_LOOKBACK, Showtime.start_time <= now)
             .order_by(Showtime.start_time).all())
    known = {a.showtime_id: a for a in Attendance.query.filter(
        Attendance.user_id == user.id, Attendance.showtime_id.in_([r.showtime_id for r in rsvps]))} if rsvps else {}
    out, seen = [], set()
    for r in rsvps:
        s, a = r.showtime, known.get(r.showtime_id)
        if s.id in seen or _screening_end(s) + ATTENDANCE_ASK_AFTER > now:
            continue
        seen.add(s.id)
        if a and (a.status or not include_prompted):
            continue
        out.append(s)
    return out


def attended_showtime_ids(user_id, group_ids=None):
    """Screenings someone saw: confirmed 'went', plus past 'going' RSVPs they
    haven't answered about, minus any they said they missed. group_ids limits
    which groups' RSVPs count (confirmed answers are personal and always do)."""
    q = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
         .filter(RSVP.user_id == user_id, RSVP.status == 'going',
                 Showtime.start_time < datetime.now(), Showtime.is_cancelled.isnot(True)))
    if group_ids is not None:
        q = q.filter(RSVP.group_id.in_(list(group_ids)))
    ids = {r.showtime_id for r in q}
    for a in Attendance.query.filter(Attendance.user_id == user_id, Attendance.status.isnot(None)):
        if a.status == 'went':
            ids.add(a.showtime_id)
        else:
            ids.discard(a.showtime_id)
    return ids


def _screening_item(s, status=None):
    return {'showtime_id': s.id, 'title': s.movie.title, 'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label,
            'poster_url': s.movie.poster_url, 'status': status}


def set_attendance(user, showtime_id, status, source):
    """Record 'went' / 'missed', or None to clear. Returns (showtime, error)."""
    showtime = db.session.get(Showtime, _as_int(showtime_id))
    if not showtime:
        return None, (jsonify({'error': 'Screening not found'}), 404)
    if showtime.start_time > datetime.now():
        return None, (jsonify({'error': "That screening hasn't happened yet"}), 400)
    if status not in ('went', 'missed', None):
        return None, (jsonify({'error': 'status must be went, missed, or null'}), 400)
    row = Attendance.query.filter_by(user_id=user.id, showtime_id=showtime.id).first()
    if status is None:
        if row and row.prompted_at:
            row.status = row.answered_at = None   # keep the "already asked" marker
        elif row:
            db.session.delete(row)
    else:
        row = row or Attendance(user_id=user.id, showtime_id=showtime.id)
        row.status, row.source, row.answered_at = status, source, _utcnow_naive()
        db.session.add(row)
    db.session.commit()
    return showtime, None


def history_items(target, viewer_is_target, group_ids=None):
    """A member's watch history, newest first. Your own also lists screenings
    you marked as missed, so you can correct them."""
    seen = attended_showtime_ids(target.id, group_ids)
    answers = {a.showtime_id: a.status for a in
               Attendance.query.filter(Attendance.user_id == target.id, Attendance.status.isnot(None))}
    ids = seen | ({sid for sid, st in answers.items() if st == 'missed'} if viewer_is_target else set())
    showtimes = (Showtime.query.filter(Showtime.id.in_(ids)).order_by(Showtime.start_time.desc()).limit(200).all()
                 if ids else [])
    # 'went' = confirmed; 'going' = RSVP'd and never said otherwise
    return [_screening_item(s, answers.get(s.id) or 'going') for s in showtimes]


def viewable_groups(viewer, target):
    """Groups whose RSVPs `viewer` may see for `target`: all their own when it's
    themselves, otherwise the active groups they share. None = no access."""
    mine = {m.group_id for m in GroupMembership.query.filter_by(user_id=viewer.id, status='active')}
    if viewer.id == target.id:
        return mine
    shared = mine & {m.group_id for m in GroupMembership.query.filter_by(user_id=target.id, status='active')}
    return shared or None


def upcoming_rsvps(user, group_ids, personal=False):
    """[(showtime, 'going'|'maybe')] for upcoming RSVPs in these groups (and,
    for your own list, your personal ones), soonest first; one per screening,
    'going' winning if they disagree."""
    if not group_ids and not personal:
        return []
    in_scope = RSVP.group_id.in_(list(group_ids or []))
    if personal:
        in_scope = db.or_(in_scope, RSVP.group_id.is_(None))
    rows = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
            .filter(RSVP.user_id == user.id, RSVP.status.in_(('going', 'maybe')),
                    in_scope, Showtime.start_time > datetime.now(),
                    Showtime.is_cancelled.isnot(True))
            .order_by(Showtime.start_time).all())
    best = {}
    for r in rows:
        if best.get(r.showtime_id, (None, None))[1] != 'going':
            best[r.showtime_id] = (r.showtime, r.status)
    return sorted(best.values(), key=lambda pair: pair[0].start_time)


def next_showings(movie_ids):
    """{movie_id: its soonest upcoming screening} in one query."""
    first = {}
    if movie_ids:
        for s in (Showtime.query.filter(Showtime.movie_id.in_(list(movie_ids)), Showtime.start_time > datetime.now(),
                                        Showtime.is_cancelled.isnot(True)).order_by(Showtime.start_time)):
            first.setdefault(s.movie_id, s)
    return first


# ─── Alerts (R8) ──────────────────────────────────────────────────────────────
# Your alerts (the bell's "For you") and your one notification setting.

def _notify_settings(user):
    import notify
    return {**notify.prefs(user), 'available': notify.available(user), 'push_ready': bool(VAPID_PUBLIC_KEY),
            'types_info': [{'key': k, 'label': label, 'hint': hint} for k, (label, hint) in notify.TYPES.items()],
            'searches': [notify.search_dict(s) for s in
                         SavedSearch.query.filter_by(user_id=user.id).order_by(SavedSearch.created_at)]}


def compare_members(me, other, group_ids):
    """Where two members line up — to coordinate outings:
      both_want   — films on both watchlists (with the next showing),
      both_going  — upcoming screenings both RSVP'd to,
      they_go_you_want — screenings they're going to that are on your watchlist,
      you_go_they_want — screenings you're going to that are on theirs,
      seen_together — screenings you both saw."""
    my_wl = {w.movie_id for w in Watchlist.query.filter_by(user_id=me.id)}
    their_wl = {w.movie_id for w in Watchlist.query.filter_by(user_id=other.id)}
    mine = {s.id: (s, st) for s, st in upcoming_rsvps(me, group_ids)}
    theirs = {s.id: (s, st) for s, st in upcoming_rsvps(other, group_ids)}

    both_movies = my_wl & their_wl
    nxt = next_showings(both_movies)
    movies = {m.id: m for m in Movie.query.filter(Movie.id.in_(list(both_movies)))} if both_movies else {}
    both_want = sorted(({'movie': {'id': mid, 'title': movies[mid].title, 'release_year': movies[mid].release_year},
                         'next': _screening_item(nxt[mid]) if mid in nxt else None}
                        for mid in both_movies if mid in movies),
                       key=lambda i: (i['next'] is None, i['next']['start_time'] if i['next'] else i['movie']['title']))

    def items(pairs):
        return [_screening_item(s, st) for s, st in sorted(pairs, key=lambda p: p[0].start_time)]

    seen = attended_showtime_ids(me.id, group_ids) & attended_showtime_ids(other.id, group_ids)
    seen_rows = (Showtime.query.filter(Showtime.id.in_(seen)).order_by(Showtime.start_time.desc()).limit(50).all()
                 if seen else [])
    return {
        'name': other.name,
        'both_want': both_want,
        'both_going': items(theirs[sid] for sid in theirs if sid in mine),
        'they_go_you_want': items(p for sid, p in theirs.items() if sid not in mine and p[0].movie_id in my_wl),
        'you_go_they_want': items(p for sid, p in mine.items() if sid not in theirs and p[0].movie_id in their_wl),
        'seen_together': [_screening_item(s, 'went') for s in seen_rows],
    }


def _profile_target(user_id):
    """(viewer, target, viewable group ids) for the /api/users/<id>/… lists, or an error."""
    me, target = current_user(), db.session.get(User, user_id)
    if not target or not target.is_active:
        return None, None, None, (jsonify({'error': 'User not found'}), 404)
    groups = viewable_groups(me, target)
    if groups is None:
        return None, None, None, (jsonify({'error': 'You do not share a group with this user'}), 403)
    return me, target, groups, None
FEED_PAGE = 20


# ─── Routes: Polls ────────────────────────────────────────────────────────────

import json as _json


def build_poll(group_id, user, data):
    """Create a poll from {title, description, poll_type, scoring_mode,
    categories: [{title, options: [{text, extra?}]}]} — the site's form, a
    Discord "Create now", or an AI draft. Returns (poll, error)."""
    title = (data.get('title') or '').strip()[:200]
    if not title:
        return None, (jsonify({'error': 'Title required'}), 400)
    poll = Poll(group_id=group_id, created_by=user.id, title=title,
                description=(data.get('description') or '')[:2000],
                poll_type=data.get('poll_type') if data.get('poll_type') in ('standard', 'prediction') else 'standard',
                scoring_mode=data.get('scoring_mode') if data.get('scoring_mode') in ('none', 'single', 'ranked', 'confidence') else 'none')
    db.session.add(poll)
    db.session.flush()
    order = 0
    for cat_data in data.get('categories', []):
        cat_title = (cat_data.get('title') or '').strip()[:200]
        options = [o for o in cat_data.get('options', []) if (o.get('text') or '').strip()]
        if not cat_title or not options:
            continue
        cat = PollCategory(poll_id=poll.id, title=cat_title, sort_order=order)
        order += 1
        db.session.add(cat)
        db.session.flush()
        for j, opt_data in enumerate(options):
            extra = opt_data.get('extra')
            db.session.add(PollOption(category_id=cat.id, text=opt_data['text'].strip()[:200], sort_order=j,
                                      extra_data=_json.dumps(extra) if extra else None))
    db.session.commit()
    return poll, None


# ─── Poll drafts from a plain-English ask (R6a) ───────────────────────────────

DRAFTS_PER_HOUR = 12        # per person: drafts use the shared AI's daily budget


def _draft_poll(user, group, prompt, scope='playing'):
    """(response, status) — shared by the site and the bot's /poll. `scope`:
    "playing" (local showings) or "all" (films in general)."""
    import poll_ai
    ai = _ai()
    prompt = re.sub(r'\s+', ' ', prompt or '').strip()[:300]
    if len(prompt) < 3:
        return {'error': 'Describe the poll you want (e.g. "spookiest Halloween movies").'}, 400
    recent = PollDraft.query.filter(PollDraft.user_id == user.id,
                                    PollDraft.created_at >= datetime.now() - timedelta(hours=1)).count()
    if recent >= DRAFTS_PER_HOUR:
        return {'error': "That's a lot of drafts this hour. Try again in a bit, or build the poll by hand."}, 429
    try:
        data = poll_ai.draft(group, prompt, scope=scope)
    except ai.RateLimited as e:
        mins = max(1, round((e.retry_after_sec or 600) / 60))
        return {'error': f"The AI is out of juice for now (back in ~{mins} min). You can still build the poll by hand.",
                'code': 'rate_limited'}, 429
    except (ai.Unavailable, poll_ai.DraftError) as e:
        msg = str(e) if isinstance(e, poll_ai.DraftError) else "The AI isn't available right now. You can still build the poll by hand."
        return {'error': msg, 'code': 'unavailable'}, 502
    except Exception as e:
        print(f'poll draft failed: {e}')
        return {'error': "Couldn't draft that. Try rewording it, or build the poll by hand.", 'code': 'failed'}, 502
    d = PollDraft(group_id=group.id, user_id=user.id, prompt=prompt, data_json=_json.dumps(data))
    db.session.add(d)
    db.session.commit()
    return {'id': d.id, 'group_id': group.id, 'prompt': prompt, **data}, 201


# ─── Poll voting + scoring rules (shared by the site and Discord's /vote) ─────

RANKED_PICKS = 3


def apply_votes(user, poll, votes_data, clear=()):
    """Save a member's picks for an open poll. Each category mentioned (in
    votes, or in clear) is replaced wholesale, so an empty ranked list or a
    clear wipes it. Invalid entries are skipped. Returns how many were saved.
    - single/none: one pick per category (the last one sent wins)
    - confidence: one pick, confidence clamped to 1–10
    - ranked: up to RANKED_PICKS distinct nominees, distinct ranks 1..RANKED_PICKS"""
    cats = {c.id: c for c in poll.categories}
    picks = {}
    for v in votes_data or []:
        if not isinstance(v, dict):
            continue
        cat = cats.get(_as_int(v.get('category_id')))
        opt_id = _as_int(v.get('option_id'))
        if cat and opt_id in {o.id for o in cat.options}:
            picks.setdefault(cat.id, []).append((opt_id, v))

    rows = []
    for cat_id, entries in picks.items():
        if poll.scoring_mode == 'ranked':
            used_opts, used_ranks = set(), set()
            for opt_id, v in entries:
                rank = _as_int(v.get('rank'))
                if not rank or not 1 <= rank <= RANKED_PICKS or rank in used_ranks or opt_id in used_opts:
                    continue
                used_opts.add(opt_id)
                used_ranks.add(rank)
                rows.append(PollVote(category_id=cat_id, user_id=user.id, option_id=opt_id, rank=rank))
        else:
            opt_id, v = entries[-1]
            confidence = 1
            if poll.scoring_mode == 'confidence':
                confidence = max(1, min(10, _as_int(v.get('confidence')) or 1))
            rows.append(PollVote(category_id=cat_id, user_id=user.id, option_id=opt_id, confidence=confidence))

    touched = set(picks) | {c for c in (_as_int(x) for x in (clear or [])) if c in cats}
    if touched:
        PollVote.query.filter(PollVote.user_id == user.id, PollVote.category_id.in_(touched)) \
            .delete(synchronize_session=False)
    db.session.add_all(rows)
    db.session.commit()
    return len(rows)


def vote_kernels(scoring_mode, vote, correct_option_id):
    """Kernels one pick earned in a scored category (None if it has no winner yet)."""
    if not correct_option_id:
        return None
    if vote.option_id == correct_option_id:
        return {'confidence': vote.confidence, 'single': 1,
                'ranked': max(1, 4 - (vote.rank or 1))}.get(scoring_mode, 0)
    return -vote.confidence if scoring_mode == 'confidence' else 0


def poll_scores(poll):
    """One poll's standings: [{user, correct, kernels, total}], best first."""
    scores = {}
    for cat in poll.categories:
        for vote in cat.votes:
            s = scores.setdefault(vote.user_id, {'correct': 0, 'kernels': 0, 'total': 0})
            s['total'] += 1
            k = vote_kernels(poll.scoring_mode, vote, cat.correct_option_id)
            if k is not None:
                s['kernels'] += k
                s['correct'] += vote.option_id == cat.correct_option_id
    users = {u.id: u for u in User.query.filter(User.id.in_(scores))} if scores else {}
    board = [{'user': users[uid], **s} for uid, s in scores.items() if uid in users]
    board.sort(key=lambda x: (-x['kernels'], -x['correct']))
    return board


def calc_user_kernels(user_id, group_id=None):
    """Total popcorn kernels + correct picks across scored polls (optionally one group's)."""
    total, correct = 0, 0
    votes = PollVote.query.filter_by(user_id=user_id).all()
    for vote in votes:
        cat = vote.category
        if not cat or not cat.correct_option_id:
            continue
        poll = cat.poll
        if not poll or poll.status != 'scored':
            continue
        if group_id and poll.group_id != group_id:
            continue
        total += vote_kernels(poll.scoring_mode, vote, cat.correct_option_id)
        correct += vote.option_id == cat.correct_option_id
    return total, correct


def build_leaderboard(group):
    """The club's standings: one kernel total each (polls + going out + from
    members, R10b), with where it came from; ties by correct picks, then
    screenings attended."""
    import kernels
    members = [m for m in group.memberships if m.status == 'active' and m.user]
    counts = kernels.breakdowns([m.user_id for m in members], group.id)
    rows = []
    for m in members:
        k = counts[m.user_id]
        rows.append({
            'user': m.user.public_dict(),
            'kernels': k['kernels'],
            'correct': k['correct'],
            'attendance': len(attended_showtime_ids(m.user_id, {group.id})),
            'breakdown': {part: k[part] for part in kernels.PARTS},
        })
    rows.sort(key=lambda r: (-r['kernels'], -r['correct'], -r['attendance']))
    return rows


# ─── Routes: Internal API (Discord bot) ───────────────────────────────────────
# Consumed by the bot container over the Docker network, authed by
# X-Internal-Token (see require_internal). No session/cookies involved.

def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _group_showtime_query(group):
    """Showtimes filtered to a group's selected theatres (all when unset)."""
    q = Showtime.query.join(Movie).join(Theatre).filter(
        Showtime.is_cancelled.isnot(True),
        Theatre.is_active.isnot(False),
    )
    slugs = [t.strip() for t in (group.theatres or '').split(',') if t.strip()] if group else []
    if slugs:
        q = q.filter(Theatre.slug.in_(slugs))
    return q
RARE_MIN_SCORE = 4                       # a screening needs this rarity score to be called rare
PLAN_MIN_WATCHERS = 2                    # "make plans": members wanting a film nobody's going to yet
LAST_CHANCE_MARGIN = timedelta(days=3)   # the theatre's schedule must run this far past the last showing
SCHEDULE_GAP_DAYS = 2                    # a published schedule can skip this many days (closed days) in a row
DIGEST_CAPS = {'plans': 2, 'rare': 5, 'last_chance': 3, 'opening': 4}   # keep it short enough to read
EVENT_WORDS = [                          # special-event billing -> (pattern, how the digest says it)
    (r'q\s*&\s*a', 'Q&A'), (r'in[- ]person', 'in person'), (r'\bintro', 'intro'), (r'premiere', 'premiere'),
    (r'anniversary', 'anniversary'), (r'double[- ]feature', 'double feature'), (r'marathon', 'marathon'),
    (r'\bguest', 'guest'), (r'conversation with', 'conversation'),
]


def rarity(s, showings, venues, this_year):
    """(score, reasons) for one screening of a film shown `showings` times at
    `venues` theatres in the digest window. Rewards what makes a screening hard
    to catch again: few showings, film prints, age, one venue, special events —
    and marks down wide releases, so an anniversary re-release in 30
    multiplex slots doesn't count."""
    score, why = 0, []
    if showings == 1:
        score += 3; why.append('one night only')
    elif showings <= 3:
        score += 2; why.append(f'{showings} showings')
    elif showings <= 6:
        score += 1
    else:
        score -= 2
    fmt = (s.format_label or '').lower()
    if '70mm' in fmt:
        score += 4; why.append('70mm')
    elif '35mm' in fmt or '16mm' in fmt:
        score += 3; why.append('35mm' if '35mm' in fmt else '16mm')
    year = _as_int((s.movie.release_year or '')[:4])
    if year:
        age = this_year - year
        score += 3 if age >= 40 else 2 if age >= 20 else 1 if age >= 5 else 0
        if age >= 5:
            why.append(str(year))
    if venues == 1:
        score += 1
    billing = s.event_label or ''
    for pattern, label in EVENT_WORDS:
        if re.search(pattern, billing, re.I):
            score += 2; why.append(label)
            break
    return score, why


def is_last_chance(final_start, theatre_ids, horizon):
    """A film's last listed showing is really its last only if every theatre
    showing it has published its full schedule well past that date — otherwise
    the run may just extend beyond a theatre's one-week listing horizon."""
    return all(horizon.get(tid, final_start) >= final_start + LAST_CHANCE_MARGIN for tid in theatre_ids)


def schedule_horizons(group, now):
    """{theatre_id: the date through which it has published its full schedule}.
    Theatres list regular films only a week or so out but special events months
    ahead, so a theatre's latest showtime says nothing about whether a film's
    run continues. Instead: a full day has at least half the theatre's typical
    daily showtimes (the median of the coming week's days that have any), and
    the schedule runs from today through the last full day before more than
    SCHEDULE_GAP_DAYS days in a row that aren't — so a lone event later on, or
    an empty day lowering the typical count, never stretches it."""
    rows = (_group_showtime_query(group)
            .with_entities(Showtime.theatre_id, db.func.date(Showtime.start_time), db.func.count(Showtime.id))
            .filter(Showtime.start_time >= now, Showtime.start_time < now + timedelta(days=90))
            .group_by(Showtime.theatre_id, db.func.date(Showtime.start_time)).all())
    per_day = {}
    for tid, day, n in rows:
        per_day.setdefault(tid, {})[(datetime.fromisoformat(str(day)).date() - now.date()).days] = n
    horizons = {}
    for tid, days in per_day.items():
        week = sorted(n for d, n in days.items() if d < 7)
        threshold = max(1, week[len(week) // 2] / 2) if week else 1
        last, gap = 0, 0
        for d in range(max(days) + 1):
            if days.get(d, 0) >= threshold:
                last, gap = d, 0
            else:
                gap += 1
                if gap > SCHEDULE_GAP_DAYS:
                    break
        horizons[tid] = datetime.combine(now.date() + timedelta(days=last), datetime.max.time())
    return horizons


def screening_card(showtime, group_id):
    """A screening as Discord shows it: going / maybe name only members in the
    server; going_more / maybe_more count everyone else."""
    rsvps = (RSVP.query.filter(RSVP.showtime_id == showtime.id, RSVP.group_id == group_id,
                               RSVP.status.in_(('going', 'maybe'))).order_by(RSVP.created_at).all())
    card = {'showtime_id': showtime.id, 'title': showtime.movie.title,
            'start_time': showtime.start_time.isoformat(),
            'theatre': showtime.theatre.name, 'theatre_short': showtime.theatre.short_name or showtime.theatre.name,
            'format_label': showtime.format_label, 'poster_url': showtime.movie.poster_url,
            'site_path': f'/calendar?showtime={showtime.id}'}
    for status in ('going', 'maybe'):
        shown, more = split_present([r.user for r in rsvps if r.status == status])
        card[status] = [{'name': u.name, 'discord_user_id': u.discord_user_id} for u in shown]
        card[f'{status}_more'] = more
    return card


# ─── Shared AI (R6a) ──────────────────────────────────────────────────────────
# backend/ai.py owns the model choice for everything AI: the site's poll
# drafts and the bot's chatbot (which calls /api/internal/ai/chat). /llm
# overrides are the llm_* settings above; model changes reach the owner by DM
# (an ActivityEvent the bot turns into one).

def _ai_overrides():
    rows = {r.key: r.value for r in BotSetting.query.filter(BotSetting.key.in_(('llm_primary', 'llm_fallback')))}
    return {'primary': rows.get('llm_primary', ''), 'fallback': rows.get('llm_fallback', '')}


def _ai_switched(choice, message):
    """Each server process refreshes on its own; tell the owner once per change."""
    import json
    key = '|'.join(str(x) for x in choice) + '|' + hashlib.sha256(
        '\n'.join(l for l in message.split('\n') if l.startswith('• Note')).encode()).hexdigest()[:12]
    row = db.session.get(BotSetting, 'ai_choice')
    if row and row.value == key:
        return
    row = row or BotSetting(key='ai_choice')
    row.value = key
    db.session.add(row)
    db.session.add(ActivityEvent(kind='llm_switch', payload_json=json.dumps({'message': message})))
    db.session.commit()


def _ai():
    import ai
    ai.configure(on_switch=_ai_switched, load_overrides=_ai_overrides)
    return ai


# ─── Init ─────────────────────────────────────────────────────────────────────

def migrate():
    """Idempotent migrations for SQLite (ADD COLUMN only)."""
    stmts = [
        "ALTER TABLE user ADD COLUMN bio TEXT DEFAULT ''",
        "ALTER TABLE user ADD COLUMN favorite_genres TEXT DEFAULT ''",
        "ALTER TABLE user ADD COLUMN avatar_url TEXT",
        "ALTER TABLE movie ADD COLUMN genres TEXT DEFAULT ''",
        "ALTER TABLE rsvp ADD COLUMN group_id INTEGER REFERENCES 'group'(id)",
        "ALTER TABLE 'group' ADD COLUMN theatres TEXT DEFAULT ''",
        "ALTER TABLE 'group' ADD COLUMN announce_muted_theatres TEXT DEFAULT ''",
        # TMDB / OMDb enrichment columns
        "ALTER TABLE movie ADD COLUMN tmdb_id INTEGER",
        "ALTER TABLE movie ADD COLUMN imdb_id VARCHAR(20)",
        "ALTER TABLE movie ADD COLUMN backdrop_url VARCHAR(500)",
        "ALTER TABLE movie ADD COLUMN tagline VARCHAR(500)",
        "ALTER TABLE movie ADD COLUMN vote_average FLOAT",
        "ALTER TABLE movie ADD COLUMN content_rating VARCHAR(10)",
        "ALTER TABLE movie ADD COLUMN cast_json TEXT",
        "ALTER TABLE movie ADD COLUMN crew_json TEXT",
        "ALTER TABLE movie ADD COLUMN awards VARCHAR(500)",
        "ALTER TABLE movie ADD COLUMN ratings_json TEXT",
        "ALTER TABLE movie ADD COLUMN trailer_key VARCHAR(50)",
        # Scraper platform / multi-theatre columns
        "ALTER TABLE theatre ADD COLUMN short_name VARCHAR(20)",
        "ALTER TABLE theatre ADD COLUMN is_active BOOLEAN DEFAULT 1",
        "ALTER TABLE showtime ADD COLUMN is_cancelled BOOLEAN DEFAULT 0",
        "ALTER TABLE movie ADD COLUMN title_normalized VARCHAR(220)",
        # Discord account linking
        "ALTER TABLE user ADD COLUMN discord_user_id VARCHAR(30)",
        "ALTER TABLE user ADD COLUMN discord_link_code VARCHAR(12)",
        "ALTER TABLE user ADD COLUMN discord_link_code_expires DATETIME",
        "ALTER TABLE user ADD COLUMN letterboxd_username VARCHAR(60)",
        # Catalog cleanup: lookup retry throttle, per-screening format/event labels
        "ALTER TABLE movie ADD COLUMN enrich_attempted_at DATETIME",
        "ALTER TABLE showtime ADD COLUMN format_label VARCHAR(60)",
        "ALTER TABLE showtime ADD COLUMN event_label VARCHAR(200)",
        # Opt-in Discord drop alerts (empty = all off)
        "ALTER TABLE 'group' ADD COLUMN announce_enabled_theatres VARCHAR(400) DEFAULT ''",
        # Discord-first accounts
        "ALTER TABLE user ADD COLUMN discord_username VARCHAR(40)",
        # Feed: when an RSVP last changed, when a poll was scored
        "ALTER TABLE rsvp ADD COLUMN updated_at DATETIME",
        "ALTER TABLE poll ADD COLUMN scored_at DATETIME",
        # Discussion threads mirrored with Discord
        "ALTER TABLE message ADD COLUMN source VARCHAR(12)",
        "ALTER TABLE message ADD COLUMN discord_message_id VARCHAR(30)",
        "CREATE INDEX IF NOT EXISTS ix_message_discord_message_id ON message (discord_message_id)",
        # R3d: choose what goes to Discord
        "ALTER TABLE user ADD COLUMN share_prefs TEXT",
        "ALTER TABLE message ADD COLUMN to_discord BOOLEAN",
        # R5b: guest profiles
        "ALTER TABLE user ADD COLUMN is_guest BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN last_seen_at DATETIME",
        "ALTER TABLE user ADD COLUMN guest_ip_hash VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_user_guest_ip_hash ON user (guest_ip_hash)",
        "ALTER TABLE login_token ADD COLUMN guest_user_id INTEGER",
        # R6b: pictures
        "ALTER TABLE user ADD COLUMN avatar_emoji VARCHAR(16)",
        "ALTER TABLE user ADD COLUMN avatar_kind VARCHAR(10)",
        "ALTER TABLE user ADD COLUMN discord_avatar_url TEXT",
        "ALTER TABLE 'group' ADD COLUMN photo_url VARCHAR(200)",
        "ALTER TABLE 'group' ADD COLUMN emoji VARCHAR(16)",
        "ALTER TABLE 'group' ADD COLUMN short_name VARCHAR(12)",
        "ALTER TABLE 'group' ADD COLUMN trivia_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE 'group' ADD COLUMN trivia_discord BOOLEAN DEFAULT 0",
        # R7a: theatre maps, calendar subscriptions
        "ALTER TABLE theatre ADD COLUMN latitude FLOAT",
        "ALTER TABLE theatre ADD COLUMN longitude FLOAT",
        "ALTER TABLE user ADD COLUMN calendar_token VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_user_calendar_token ON user (calendar_token)",
        "ALTER TABLE group_membership ADD COLUMN calendar_token VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_membership_calendar_token ON group_membership (calendar_token)",
        # R8: alerts
        "ALTER TABLE user ADD COLUMN notify_prefs TEXT",
    ]
    for sql in stmts:
        try:
            db.session.execute(db.text(sql))
        except Exception:
            pass  # column already exists
    db.session.commit()
    # R6a.1: the digest's watchlist mentions became a choice. Members already
    # on Discord keep being mentioned for what's on their lists today.
    try:
        db.session.execute(db.text("ALTER TABLE watchlist ADD COLUMN share_discord BOOLEAN"))
        db.session.execute(db.text(
            "UPDATE watchlist SET share_discord = 1 WHERE user_id IN "
            "(SELECT id FROM user WHERE discord_user_id IS NOT NULL)"))
        db.session.commit()
    except Exception:
        db.session.rollback()   # already added
    # Opt-in notifications (Oct 2026): digest pings were turned on for every
    # Discord member in R6a.1 and for every /watch add; clear those so each
    # person is asked. A "No" stays, and so does "Always" chosen in settings.
    if not db.session.get(BotSetting, 'optin_reset_done'):
        db.session.execute(db.text("UPDATE watchlist SET share_discord = NULL WHERE share_discord = 1"))
        db.session.add(BotSetting(key='optin_reset_done', value='1'))
        db.session.commit()
    db.session.execute(db.text("UPDATE rsvp SET updated_at = created_at WHERE updated_at IS NULL"))
    # Pictures so far all came from Discord: remember them as such.
    db.session.execute(db.text("UPDATE user SET discord_avatar_url = avatar_url WHERE discord_avatar_url IS NULL "
                               "AND avatar_url LIKE 'https://cdn.discordapp.com/%'"))
    db.session.commit()
    # Every movie's current title is a venue label the scraper may see again.
    db.session.execute(db.text(
        "INSERT OR IGNORE INTO movie_alias (title, movie_id) SELECT title, id FROM movie"))
    db.session.commit()
    _migrate_poll_vote_ranked_constraint()
    _migrate_user_email_nullable()
    _backfill_title_normalized()


def _backup_sqlite(suffix):
    """Consistent copy of the SQLite file next to it (VACUUM INTO also captures
    WAL contents). Returns the path, or None when not on a SQLite file."""
    path = db.engine.url.database
    if db.engine.url.get_backend_name() != 'sqlite' or not path or path == ':memory:':
        return None
    target = f"{path}.{suffix}.bak"
    if os.path.exists(target):
        return target
    con = db.engine.raw_connection()
    try:
        con.isolation_level = None
        con.execute("VACUUM INTO ?", (target,))
    finally:
        con.close()
    print(f'Database backed up to {target}')
    return target


def _migrate_user_email_nullable():
    """Discord-only accounts have no email, so user.email must allow NULL.
    SQLite can't relax NOT NULL in place: rebuild the table from its own stored
    definition (column order and every added column preserved), after backing
    up the database. Also enforce one account per Discord user — the column was
    added with ALTER TABLE, which can't add its UNIQUE constraint."""
    row = db.session.execute(db.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='user'")).fetchone()
    if row and row[0] and re.search(r'\bemail VARCHAR\(120\) NOT NULL', row[0]):
        _backup_sqlite('pre-discord-accounts')
        new_sql = re.sub(r'\bemail VARCHAR\(120\) NOT NULL', 'email VARCHAR(120)', row[0], count=1)
        new_sql = re.sub(r'^CREATE TABLE "?user"?', 'CREATE TABLE user_new', new_sql, count=1)
        db.session.execute(db.text("DROP TABLE IF EXISTS user_new"))
        db.session.execute(db.text(new_sql))
        db.session.execute(db.text("INSERT INTO user_new SELECT * FROM user"))
        db.session.execute(db.text("DROP TABLE user"))
        db.session.execute(db.text("ALTER TABLE user_new RENAME TO user"))
        db.session.commit()
        print('Migrated user.email to allow Discord-only accounts')

    dupes = db.session.execute(db.text(
        "SELECT discord_user_id FROM user WHERE discord_user_id IS NOT NULL "
        "GROUP BY discord_user_id HAVING COUNT(*) > 1")).fetchall()
    if dupes:
        print(f'⚠️  Not adding the unique Discord index: duplicate ids {[d[0] for d in dupes]}')
    else:
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_user_discord_user_id ON user (discord_user_id)"))
        db.session.commit()


def _backfill_title_normalized():
    """One-time fill of movie.title_normalized for rows created before the column existed."""
    from scrapers.base import normalize_title
    movies = Movie.query.filter(Movie.title_normalized.is_(None)).all()
    for m in movies:
        m.title_normalized = normalize_title(m.title)
    if movies:
        db.session.commit()


def _migrate_poll_vote_ranked_constraint():
    """Recreate poll_vote with UNIQUE(category_id, user_id, rank) to support ranked voting."""
    import re
    row = db.session.execute(db.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='poll_vote'"
    )).fetchone()
    if not row or not row[0]:
        return
    create_sql = row[0].lower()
    # Check if there's a UNIQUE constraint on (category_id, user_id) without rank
    needs_migration = False
    for match in re.finditer(r'unique\s*\(([^)]+)\)', create_sql):
        cols = [c.strip() for c in match.group(1).split(',')]
        if 'category_id' in cols and 'user_id' in cols and 'rank' not in cols:
            needs_migration = True
            break
    if not needs_migration:
        return
    db.session.execute(db.text("DROP TABLE IF EXISTS poll_vote_new"))
    db.session.execute(db.text("""
        CREATE TABLE poll_vote_new (
            id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES poll_category(id),
            user_id INTEGER NOT NULL REFERENCES user(id),
            option_id INTEGER NOT NULL REFERENCES poll_option(id),
            confidence INTEGER DEFAULT 1,
            rank INTEGER,
            created_at DATETIME,
            UNIQUE (category_id, user_id, rank)
        )
    """))
    db.session.execute(db.text("INSERT OR IGNORE INTO poll_vote_new SELECT * FROM poll_vote"))
    db.session.execute(db.text("DROP TABLE poll_vote"))
    db.session.execute(db.text("ALTER TABLE poll_vote_new RENAME TO poll_vote"))
    db.session.commit()


def seed_theatres():
    """Upsert theatres from the scraper registry; deactivate ones no longer registered
    (e.g. the closed E Street Cinema) without deleting their showtime history."""
    from scrapers import THEATRE_REGISTRY

    registry_slugs = set()
    for cfg in THEATRE_REGISTRY:
        registry_slugs.add(cfg.slug)
        theatre = Theatre.query.filter_by(slug=cfg.slug).first()
        if not theatre:
            theatre = Theatre(slug=cfg.slug)
            db.session.add(theatre)
        theatre.name = cfg.name
        theatre.short_name = cfg.short_name
        theatre.address = cfg.address
        theatre.website = cfg.website
        theatre.color = cfg.color
        theatre.is_active = cfg.enabled
        theatre.latitude, theatre.longitude = cfg.lat, cfg.lon

    for theatre in Theatre.query.all():
        if theatre.slug not in registry_slugs:
            theatre.is_active = False

    db.session.commit()


def seed_admin():
    """A fresh install's first admin and default club, from ADMIN_EMAIL (and
    ADMIN_NAME) in the environment; without them there's nothing to seed."""
    email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    if not email:
        return
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            name=os.environ.get('ADMIN_NAME', '').strip() or 'Admin',
            avatar_color='#e8a838',
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()

    # Seed the default group
    slug = 'motion-picture-hate-and-derision-society'
    group = Group.query.filter_by(slug=slug).first()
    if not group:
        group = Group(
            name='Motion Picture Hate and Derision Society',
            slug=slug,
            description='',
            created_by=user.id,
            is_public=True,
        )
        db.session.add(group)
        db.session.flush()

    # Ensure admin membership exists
    existing_membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
    if not existing_membership:
        membership = GroupMembership(user_id=user.id, group_id=group.id, role='admin', status='active')
        db.session.add(membership)

    db.session.commit()
    # (A one-time backfill that moved club-less RSVPs into this group used to
    # run here on every start. Club-less RSVPs are now people's private
    # personal plans (R5b) and must never be moved: removed in R5c.)


# ─── WAL mode for better concurrency ─────────────────────────────────────────

@app.before_request
def enable_wal():
    if not getattr(app, '_wal_enabled', False):
        try:
            db.session.execute(db.text("PRAGMA journal_mode=WAL"))
            db.session.execute(db.text("PRAGMA busy_timeout=5000"))
            app._wal_enabled = True
        except Exception:
            pass


# ─── Keeping the public pages warm (R7b) ─────────────────────────────────────
# Building Discover from scratch takes seconds on the NAS, so the first visitor
# after a quiet spell waited (and the app could give up). Each server process
# rebuilds the common public responses every few minutes instead, in the
# background. Turned on by WARM_PUBLIC_CACHE=1 (the Docker entrypoint).

WARM_EVERY_SECONDS = 240


def _warm_urls(today):
    """The public views most visits open first (the same URLs the site asks for)."""
    days = lambda n: (today + timedelta(days=n)).isoformat()
    return ['/api/discover', '/api/discover/browse?when=week', '/api/theatres-overview',
            '/api/discover/doubles', '/api/discover/spotlights',
            f'/api/discover/calendar?from={today.isoformat()}&to={days(6)}',      # Week
            f'/api/discover/calendar?from={today.isoformat()}&to={days(13)}']     # Agenda


def start_warming():
    import threading

    def loop():
        time.sleep(3)
        while True:
            client = app.test_client()
            for url in _warm_urls(datetime.now().date()):
                try:
                    client.get(url, headers={'X-Internal-Token': INTERNAL_API_TOKEN, 'X-Warm': '1'})
                except Exception as e:            # never let warming take a worker down
                    print(f'warm-up of {url} failed: {e}')
            time.sleep(WARM_EVERY_SECONDS)
    threading.Thread(target=loop, name='warm-public-pages', daemon=True).start()


if os.environ.get('WARM_PUBLIC_CACHE') == '1':
    start_warming()


# ─── Routes ───────────────────────────────────────────────────────────────────
# Each area registers its routes on `app` when imported (routes/*.py).
from routes import (alerts, auth, clubs, discord, internal, people, plans, polls,  # noqa: E402,F401
                    schedule, social)



if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        migrate()
        seed_theatres()
        seed_admin()
    app.run(debug=True, port=5001)
