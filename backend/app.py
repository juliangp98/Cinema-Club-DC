from flask import Flask, jsonify, request, session, make_response, redirect
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
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
TMDB_API_TOKEN = os.environ.get('TMDB_API_TOKEN', '')
OMDB_API_KEY = os.environ.get('OMDB_API_KEY', '')
INTERNAL_API_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')
# "Sign in with Discord" — the bot's own application (OAuth2 tab in the portal).
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
DISCORD_API = 'https://discord.com/api/v10'


# ─── Email Helper ─────────────────────────────────────────────────────────────

def send_email(to, subject, html_body):
    """Send an email via Gmail SMTP. Falls back to console if SMTP not configured."""
    if not to:
        return  # Discord-only accounts have no email address
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


def email_invite(to_email, group_name, invite_url):
    send_email(to_email, f"You're invited to {group_name} on Cinema Club DC",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>You've been invited to join <strong>{group_name}</strong> on Cinema Club DC!</p>
        <p><a href="{invite_url}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Accept Invite</a></p>
        <p style="color:#888;font-size:13px;">Or copy this link: {invite_url}</p>
        </div>""")


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


def email_added_to_group(to_email, group_name):
    send_email(to_email, f"You've been added to {group_name}",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>You've been added to <strong>{group_name}</strong>. Open Cinema Club DC to check out upcoming showtimes!</p>
        <p><a href="{FRONTEND_URL}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Open Cinema Club DC</a></p>
        </div>""")


def email_join_request(admin_email, requester_name, group_name):
    send_email(admin_email, f"{requester_name} wants to join {group_name}",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p><strong>{requester_name}</strong> has requested to join <strong>{group_name}</strong>.</p>
        <p>Log in to Cinema Club DC to approve or deny the request.</p>
        <p><a href="{FRONTEND_URL}/groups" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Manage Group</a></p>
        </div>""")


def email_approved(to_email, group_name):
    send_email(to_email, f"Welcome to {group_name}!",
        f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
        <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
        <p>Your request to join <strong>{group_name}</strong> has been approved! 🎉</p>
        <p><a href="{FRONTEND_URL}" style="display:inline-block;padding:12px 24px;background:#e8a838;color:#0d0c09;
        text-decoration:none;border-radius:6px;font-weight:bold;">Open Cinema Club DC</a></p>
        </div>""")


# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # None for Discord-only accounts: created automatically the first time a
    # server member uses a personal bot command, or by "Sign in with Discord".
    email = db.Column(db.String(120), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    avatar_color = db.Column(db.String(20), default='#e8a838')
    avatar_url = db.Column(db.Text)
    bio = db.Column(db.Text, default='')
    favorite_genres = db.Column(db.Text, default='')
    invite_token = db.Column(db.String(64), unique=True)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    discord_user_id = db.Column(db.String(30), unique=True)
    discord_username = db.Column(db.String(40))   # @handle, for display
    # R3d: what to do with your site actions in Discord, per kind:
    # {"rsvp"|"poll"|"comment": "ask"|"always"|"never"} (missing = ask)
    share_prefs = db.Column(db.Text)
    # R5b: a guest profile — made automatically on a visitor's first RSVP,
    # watchlist add or reaction; private to them until they keep it.
    is_guest = db.Column(db.Boolean, default=False)
    last_seen_at = db.Column(db.DateTime)           # guests: for idle expiry
    guest_ip_hash = db.Column(db.String(64), index=True)   # guests: creation cap (a hash, not the address)
    discord_link_code = db.Column(db.String(12))
    discord_link_code_expires = db.Column(db.DateTime)
    letterboxd_username = db.Column(db.String(60))
    rsvps = db.relationship('RSVP', backref='user', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'avatar_color': self.avatar_color,
            'avatar_url': self.avatar_url,
            'bio': self.bio or '',
            'favorite_genres': self.favorite_genres or '',
            'discord_linked': bool(self.discord_user_id),
            'on_discord': on_discord(self),     # linked and in the club's server
            'discord_username': self.discord_username or '',
            'discord_only': self.email is None,
            'letterboxd_username': self.letterboxd_username or '',
            'share_prefs': share_prefs(self),
            'is_guest': bool(self.is_guest),
        }


class LoginToken(db.Model):
    """A one-time emailed sign-in link. Only a SHA-256 hash of the token is
    stored, so a leaked database can't be used to sign in."""
    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    purpose = db.Column(db.String(10), nullable=False)  # 'login' | 'signup'
    name = db.Column(db.String(100))                    # display name, for signups
    request_ip = db.Column(db.String(64), index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    guest_user_id = db.Column(db.Integer)           # R5b: the guest who asked for it (kept on redeem)


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_public = db.Column(db.Boolean, default=True)
    theatres = db.Column(db.String(200), default='')  # comma-separated theatre slugs
    # Theatres whose new-showtime drops the bot announces in Discord (opt-in:
    # empty means none — new showtimes reach people through the weekly digest).
    # Doesn't affect the calendar or commands.
    announce_enabled_theatres = db.Column(db.String(400), default='')
    # Superseded by announce_enabled_theatres (alerts are now opt-in); kept
    # only because SQLite can't drop columns.
    announce_muted_theatres = db.Column(db.String(400), default='')
    memberships = db.relationship('GroupMembership', backref='group', lazy=True)

    def to_dict(self, include_members=False):
        d = {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description or '',
            'is_public': self.is_public,
            'theatres': [t.strip() for t in (self.theatres or '').split(',') if t.strip()],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'member_count': sum(1 for m in self.memberships if m.status == 'active'),
            'discord': discord_group(self.id),        # the club's Discord server's group
        }
        if include_members:
            d['members'] = [m.to_dict() for m in self.memberships if m.status == 'active']
            d['pending'] = [m.to_dict() for m in self.memberships if m.status == 'pending']
        return d


class GroupMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # see ROLE_RANK: viewer, member, organizer, admin
    status = db.Column(db.String(20), default='active')  # 'active', 'pending'
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship('User', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'group_id'),)

    def to_dict(self):
        return {
            'id': self.id,
            'user': self.user.to_dict() if self.user else None,
            'role': self.role,
            'status': self.status,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
        }


class Theatre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    address = db.Column(db.String(200))
    website = db.Column(db.String(200))
    color = db.Column(db.String(20), default='#e8a838')
    short_name = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    showtimes = db.relationship('Showtime', backref='theatre', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'address': self.address,
            'website': self.website,
            'color': self.color,
            'short_name': self.short_name or self.name,
            'is_active': bool(self.is_active),
        }


class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    director = db.Column(db.String(100))
    release_year = db.Column(db.String(10))
    runtime_minutes = db.Column(db.Integer)
    starring = db.Column(db.Text)
    description = db.Column(db.Text)
    trailer_link = db.Column(db.String(500))
    poster_url = db.Column(db.String(500))
    genres = db.Column(db.Text, default='')
    title_normalized = db.Column(db.String(220), index=True)
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # TMDB / OMDb enrichment fields
    tmdb_id = db.Column(db.Integer)
    imdb_id = db.Column(db.String(20))
    backdrop_url = db.Column(db.String(500))
    tagline = db.Column(db.String(500))
    vote_average = db.Column(db.Float)
    content_rating = db.Column(db.String(10))
    cast_json = db.Column(db.Text)       # JSON: [{name, character, profile_path}]
    crew_json = db.Column(db.Text)       # JSON: [{name, job}]
    awards = db.Column(db.String(500))
    ratings_json = db.Column(db.Text)    # JSON: [{source, value}]
    trailer_key = db.Column(db.String(50))  # YouTube video key
    # Last TMDB lookup that found nothing; retried weekly, not every scrape.
    enrich_attempted_at = db.Column(db.DateTime)
    showtimes = db.relationship('Showtime', backref='movie', lazy=True)

    def to_dict(self):
        import json as _json
        return {
            'id': self.id,
            'title': self.title,
            'director': self.director,
            'release_year': self.release_year,
            'runtime_minutes': self.runtime_minutes,
            'starring': self.starring,
            'description': self.description,
            'trailer_link': self.trailer_link,
            'poster_url': self.poster_url,
            'genres': self.genres or '',
            'tmdb_id': self.tmdb_id,
            'imdb_id': self.imdb_id,
            'backdrop_url': self.backdrop_url,
            'tagline': self.tagline,
            'vote_average': self.vote_average,
            'content_rating': self.content_rating,
            'cast': _json.loads(self.cast_json) if self.cast_json else [],
            'crew': _json.loads(self.crew_json) if self.crew_json else [],
            'awards': self.awards,
            'ratings': _json.loads(self.ratings_json) if self.ratings_json else [],
            'trailer_key': self.trailer_key,
        }


class MovieAlias(db.Model):
    """Every venue label ever seen for a film ('LICORICE PIZZA in 70mm',
    'LICORICE PIZZA (Digital)') → its Movie. The scraper recognises known labels
    without another TMDB lookup, and display titles can be cleaned up or
    duplicate films merged without breaking that recognition."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), unique=True, nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False, index=True)
    movie = db.relationship('Movie', lazy=True)


class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    purchase_link = db.Column(db.String(500))
    is_sold_out = db.Column(db.Boolean, default=False)
    is_cancelled = db.Column(db.Boolean, default=False)
    # From the venue's label: '70mm', 'Digital', '70mm · IMAX'…
    format_label = db.Column(db.String(60))
    # The venue's own title when it differs from the film's ('EPIC SUNDAY: BATMAN BEGINS').
    event_label = db.Column(db.String(200))
    rsvps = db.relationship('RSVP', backref='showtime', lazy=True)
    reactions = db.relationship('Reaction', backref='showtime', lazy=True)
    messages = db.relationship('Message', backref='showtime', lazy=True)

    def to_dict(self, user_id=None, group_id=None, user_genres=None):
        # Filter RSVPs by group if provided
        rsvps = self.rsvps
        if group_id:
            rsvps = [r for r in rsvps if r.group_id == group_id]

        attendees = [
            {'id': r.user.id, 'name': r.user.name, 'avatar_color': r.user.avatar_color}
            for r in rsvps if r.status == 'going'
        ]
        maybes = [
            {'id': r.user.id, 'name': r.user.name, 'avatar_color': r.user.avatar_color}
            for r in rsvps if r.status == 'maybe'
        ]
        user_rsvp = None
        if user_id:
            rsvp = next((r for r in rsvps if r.user_id == user_id), None)
            user_rsvp = rsvp.status if rsvp else None

        # Reactions summary by group
        group_reactions = self.reactions
        if group_id:
            group_reactions = [r for r in group_reactions if r.group_id == group_id]
        reaction_summary = {}
        for r in group_reactions:
            if r.emoji not in reaction_summary:
                reaction_summary[r.emoji] = {'count': 0, 'users': [], 'user_reacted': False}
            reaction_summary[r.emoji]['count'] += 1
            reaction_summary[r.emoji]['users'].append({'id': r.user.id, 'name': r.user.name})
            if user_id and r.user_id == user_id:
                reaction_summary[r.emoji]['user_reacted'] = True

        # Message count by group
        group_messages = self.messages
        if group_id:
            group_messages = [m for m in group_messages if m.group_id == group_id]

        # Smart suggestion
        recommended = False
        if user_genres and self.movie.genres:
            user_set = set(g.strip().lower() for g in user_genres.split(',') if g.strip())
            movie_set = set(g.strip().lower() for g in self.movie.genres.split(',') if g.strip())
            if user_set & movie_set:
                recommended = True

        return {
            'id': self.id,
            'movie': self.movie.to_dict(),
            'theatre': self.theatre.to_dict(),
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'purchase_link': self.purchase_link,
            'is_sold_out': self.is_sold_out,
            'format_label': self.format_label,
            'event_label': self.event_label,
            'attendees': attendees,
            'maybes': maybes,
            'user_rsvp': user_rsvp,
            'reactions': reaction_summary,
            'message_count': len(group_messages),
            'recommended': recommended,
        }


class ScrapeRun(db.Model):
    """One scraper execution for one theatre, with diff stats."""
    id = db.Column(db.Integer, primary_key=True)
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='ok')  # 'ok', 'empty', 'error'
    movies_found = db.Column(db.Integer, default=0)
    new_movies = db.Column(db.Integer, default=0)
    new_showtimes = db.Column(db.Integer, default=0)
    cancelled_showtimes = db.Column(db.Integer, default=0)
    prev_max_date = db.Column(db.DateTime)
    new_max_date = db.Column(db.DateTime)
    error_text = db.Column(db.Text)
    theatre = db.relationship('Theatre', lazy=True)


class ScrapeEvent(db.Model):
    """A notable change detected by a scrape (schedule drop, error) for the bot to announce."""
    id = db.Column(db.Integer, primary_key=True)
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'), nullable=False)
    run_id = db.Column(db.Integer, db.ForeignKey('scrape_run.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    event_type = db.Column(db.String(30), nullable=False)  # 'new_drop', 'new_showtimes', 'scrape_error'
    payload_json = db.Column(db.Text)
    announced_at = db.Column(db.DateTime)
    theatre = db.relationship('Theatre', lazy=True)
    run = db.relationship('ScrapeRun', lazy=True)

    def to_dict(self):
        import json as _json
        return {
            'id': self.id,
            'theatre_slug': self.theatre.slug if self.theatre else None,
            'event_type': self.event_type,
            'payload': _json.loads(self.payload_json) if self.payload_json else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'announced_at': self.announced_at.isoformat() if self.announced_at else None,
        }


class ActivityEvent(db.Model):
    """A user action on the site worth announcing in Discord (e.g. an RSVP).
    The bot polls these the same way it polls ScrapeEvents."""
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False)  # 'rsvp'
    payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    announced_at = db.Column(db.DateTime)

    def to_dict(self):
        import json as _json
        return {
            'id': self.id,
            'kind': self.kind,
            'payload': _json.loads(self.payload_json) if self.payload_json else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Quote(db.Model):
    """A line the bot drops for "what is thy wisdom", /wisdom and ambient
    triggers. Only `text` is ever shown in the channel; movie and character are
    the silent source, kept for accuracy and visible only when managing quotes.
    Removal is soft (deleted_at) so a mistaken delete can be undone."""
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    movie = db.Column(db.String(200))
    character = db.Column(db.String(200))
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))     # None for the original list
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    deleted_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    author = db.relationship('User', foreign_keys=[added_by], lazy=True)

    def to_dict(self):
        return {
            'id': self.id, 'text': self.text, 'movie': self.movie or '', 'character': self.character or '',
            'added_by': {'id': self.author.id, 'name': self.author.name,
                         'discord_user_id': self.author.discord_user_id} if self.author else None,
        }


class BotSetting(db.Model):
    """Small settings the Discord bot persists here (it has no storage of its
    own), e.g. the /llm model overrides."""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, default='')


class DiscordServerMember(db.Model):
    """Who's in the club's Discord server right now; the bot keeps this current.
    Only members who've linked Discord and are in here ever appear there."""
    discord_user_id = db.Column(db.String(30), primary_key=True)
    seen_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Watchlist(db.Model):
    """'I want to see this' — drives Discord pings when new showtimes appear."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_notified_at = db.Column(db.DateTime)
    # May the digest name or ping you about this one? None = not chosen yet
    # (your "watchlist" sharing choice decides; see watch_shared).
    share_discord = db.Column(db.Boolean)
    user = db.relationship('User', lazy=True)
    movie = db.relationship('Movie', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'movie_id'),)


class RSVP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    status = db.Column(db.String(20), nullable=False)  # 'going', 'maybe', 'not_going'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))  # last status change
    __table_args__ = (db.UniqueConstraint('user_id', 'showtime_id', 'group_id'),)


class Attendance(db.Model):
    """Whether someone actually made it to a screening, answered afterwards (an
    RSVP is only the plan). Personal, not per group. status None means the bot
    asked by DM and there's no answer yet."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    status = db.Column(db.String(10))          # 'went' | 'missed' | None
    source = db.Column(db.String(10))          # 'site' | 'discord'
    prompted_at = db.Column(db.DateTime)       # when the bot DMed about it
    answered_at = db.Column(db.DateTime)
    showtime = db.relationship('Showtime', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'showtime_id'),)


class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship('User', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'showtime_id', 'group_id', 'emoji'),)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Where it was written: 'site', 'discord' (typed in a screening thread), or
    # 'discord_bot' (posted by the bot for a member via /discuss or a Discuss
    # button). None = from before threads existed.
    source = db.Column(db.String(12))
    discord_message_id = db.Column(db.String(30), index=True)   # its copy/original in the thread
    # R3d: site comments go to the screening's Discord thread only when the
    # writer leaves "also post in Discord" on (None = from before the choice).
    to_discord = db.Column(db.Boolean)
    user = db.relationship('User', lazy=True)

    @property
    def deletable_on_site(self):
        """The bot can remove its own posts from Discord, but not a member's typed
        message — those are deleted in Discord (which then removes the site copy)."""
        return self.source != 'discord'


class ShowtimeThread(db.Model):
    """A screening's discussion thread in the club's #movies channel, mirrored
    with the site discussion for one group. Created on the first comment."""
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    guild_id = db.Column(db.String(30), nullable=False)
    channel_id = db.Column(db.String(30), nullable=False)
    thread_id = db.Column(db.String(30), nullable=False, unique=True)
    starter_message_id = db.Column(db.String(30))
    card_dirty = db.Column(db.Boolean, default=False)       # RSVPs changed: refresh the starter card
    card_refreshed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('showtime_id', 'group_id'),)

    @property
    def url(self):
        return f'https://discord.com/channels/{self.guild_id}/{self.thread_id}'


class DiscordPost(db.Model):
    """Something a member chose to post in the club's #movies channel from the
    site (R3d): their RSVPs (batched), a "who's in?" invite for a screening, a
    poll announcement or its results, or a request to start a screening's
    thread. The bot posts it once `post_at` passes, keeps it up to date while
    `dirty`, and deletes it when what it shows is gone."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    kind = db.Column(db.String(16), nullable=False)        # rsvp | invite | poll | poll_results | thread
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ref_id = db.Column(db.Integer)                          # showtime (invite, thread) or poll id
    note = db.Column(db.String(200))
    status = db.Column(db.String(12), default='pending')    # pending | posted | removed | cancelled
    post_at = db.Column(db.DateTime, nullable=False)        # local time, like showtimes
    dirty = db.Column(db.Boolean, default=False)
    message_id = db.Column(db.String(30))
    jump_url = db.Column(db.String(200))
    posted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)
    user = db.relationship('User', lazy=True)
    rsvps = db.relationship('SharedRsvp', backref='post', lazy=True, cascade='all, delete-orphan')


class PollDraft(db.Model):
    """An AI-drafted poll (R6a), kept so the editor (site) or "Create now"
    (Discord) can pick it up. Becomes a poll only when someone creates it."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prompt = db.Column(db.String(300), nullable=False)
    data_json = db.Column(db.Text, nullable=False)
    poll_id = db.Column(db.Integer)                 # once created
    created_at = db.Column(db.DateTime, default=datetime.now)


class SharedRsvp(db.Model):
    """One screening in an RSVP post (several quick RSVPs share one post)."""
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('discord_post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)


class DiscordDeletion(db.Model):
    """A site-deleted comment whose copy in a Discord thread the bot must remove."""
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.String(30), nullable=False)
    discord_message_id = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    done_at = db.Column(db.DateTime)


# ─── Poll Models ─────────────────────────────────────────────────────────────

class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    poll_type = db.Column(db.String(20), default='standard')  # 'standard' | 'prediction'
    scoring_mode = db.Column(db.String(20), default='none')   # 'none' | 'single' | 'ranked' | 'confidence'
    status = db.Column(db.String(20), default='open')         # 'open' | 'closed' | 'scored'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = db.Column(db.DateTime, nullable=True)
    scored_at = db.Column(db.DateTime, nullable=True)

    group = db.relationship('Group', lazy=True)
    creator = db.relationship('User', lazy=True)
    categories = db.relationship('PollCategory', backref='poll', lazy=True, cascade='all, delete-orphan',
                                 order_by='PollCategory.sort_order')

    def to_dict(self, include_categories=False, user_id=None):
        d = {
            'id': self.id,
            'group_id': self.group_id,
            'created_by': self.created_by,
            'creator_name': self.creator.name if self.creator else None,
            'title': self.title,
            'description': self.description or '',
            'poll_type': self.poll_type,
            'scoring_mode': self.scoring_mode,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'category_count': len(self.categories),
        }
        if include_categories:
            d['categories'] = [c.to_dict(user_id=user_id, show_winner=self.status == 'scored') for c in self.categories]
        return d


class PollCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    correct_option_id = db.Column(db.Integer, nullable=True)

    options = db.relationship('PollOption', backref='category', lazy=True, cascade='all, delete-orphan',
                              order_by='PollOption.sort_order')
    votes = db.relationship('PollVote', backref='category', lazy=True, cascade='all, delete-orphan')

    def to_dict(self, user_id=None, show_winner=False):
        d = {
            'id': self.id,
            'title': self.title,
            'sort_order': self.sort_order,
            'options': [o.to_dict() for o in self.options],
            'correct_option_id': self.correct_option_id if show_winner else None,
            'vote_count': len(self.votes),
        }
        user_votes = [v for v in self.votes if v.user_id == user_id] if user_id else []
        if user_id:
            if user_votes:
                if self.poll.scoring_mode == 'ranked':
                    d['user_votes'] = sorted(
                        [{'option_id': v.option_id, 'rank': v.rank} for v in user_votes],
                        key=lambda x: x['rank'] or 99
                    )
                else:
                    uv = user_votes[0]
                    d['user_vote'] = {
                        'option_id': uv.option_id,
                        'confidence': uv.confidence,
                        'rank': uv.rank,
                    }
        # How everyone voted: only once you've picked here, or voting has closed,
        # so nobody is swayed before choosing.
        if user_votes or show_winner or self.poll.status != 'open':
            dist = {}
            for v in self.votes:
                dist[v.option_id] = dist.get(v.option_id, 0) + 1
            d['vote_distribution'] = dist
        return d


class PollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('poll_category.id'), nullable=False)
    text = db.Column(db.String(300), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    extra_data = db.Column(db.Text, nullable=True)  # JSON: poster_url, details, etc.

    def to_dict(self):
        import json as _json
        extra = {}
        if self.extra_data:
            try:
                extra = _json.loads(self.extra_data)
            except Exception:
                pass
        return {
            'id': self.id,
            'text': self.text,
            'sort_order': self.sort_order,
            'extra': extra,
        }


class PollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('poll_category.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_option.id'), nullable=False)
    confidence = db.Column(db.Integer, default=1)  # 1-10 for confidence scoring
    rank = db.Column(db.Integer, nullable=True)     # for ranked scoring
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship('User', lazy=True)
    option = db.relationship('PollOption', lazy=True)
    __table_args__ = (db.UniqueConstraint('category_id', 'user_id', 'rank'),)


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


def _start_session(user):
    """Sign `user` in. Clears any previous session first so a pre-existing
    cookie can't carry over."""
    session.clear()
    session.permanent = True
    session['user_id'] = user.id
    session['guest'] = bool(user.is_guest)
    session['seen'] = int(time.time())


MEMBER_IDLE_LIMIT = timedelta(days=30)   # members: signed out after this long away
GUEST_IDLE_LIMIT = timedelta(days=90)    # guests: the profile is deleted after this long away


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


def guest_blocked(user):
    """Clubs see names, so joining or starting one needs a kept profile."""
    if user and user.is_guest:
        return jsonify({'error': 'Keep your profile first (add an email or Discord) to join a club.', 'code': 'guest'}), 403
    return None


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
    email_signin_link(email, f"{FRONTEND_URL}/auth/verify?token={token}", purpose)
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


def parse_utc(value):
    """Inverse of utc_iso for query params: naive UTC, comparable with columns."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def resolve_discord_user(data):
    """The account behind a Discord user, for the bot's internal endpoints.

    Discord members don't need a site account: the first time someone uses a
    personal command in the club's server (the bot sends create=True only
    there), they get a Discord-only account — no email, no site login unless
    they "Sign in with Discord" — and join that server's group. Discord-only
    accounts follow the member's current Discord name. Returns (user, error).
    """
    discord_id = str(data.get('discord_user_id') or '').strip()
    if not discord_id.isdigit():
        return None, (jsonify({'error': 'discord_user_id required'}), 400)
    create = str(data.get('create', '')).lower() in ('1', 'true')
    name = (data.get('discord_name') or '').strip()[:100]

    user = User.query.filter_by(discord_user_id=discord_id).first()
    if user is None:
        if not create:
            return None, (jsonify({'error': 'no_account'}), 404)
        user = User(discord_user_id=discord_id, name=name or 'Discord member',
                    avatar_color=random.choice(AVATAR_COLORS), is_active=True)
        db.session.add(user)
        try:
            db.session.flush()
        except IntegrityError:        # created by a simultaneous command
            db.session.rollback()
            user = User.query.filter_by(discord_user_id=discord_id).first()
    if not user or not user.is_active:
        return None, (jsonify({'error': 'no_account'}), 404)

    if user.email is None and name:
        user.name = name
    if data.get('discord_username'):
        user.discord_username = str(data['discord_username'])[:40]
    if data.get('discord_avatar') and (user.email is None or not user.avatar_url):
        user.avatar_url = str(data['discord_avatar'])[:500]

    # Being in the club's server is membership of its group.
    group = db.session.get(Group, _as_int(data.get('group_id'))) if create else None
    if group:
        membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
        if not membership:
            db.session.add(GroupMembership(user_id=user.id, group_id=group.id, role='member', status='active'))
        elif membership.status != 'active':
            membership.status = 'active'
    if create and not db.session.get(DiscordServerMember, discord_id):
        db.session.add(DiscordServerMember(discord_user_id=discord_id))   # they're using it in the server
        _present_changed()
    db.session.commit()
    return user, None


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

def require_internal(f):
    """Auth for /api/internal/* — shared-secret header used by the Discord bot
    over the Docker network. Rejects everything when the token is unset."""
    @wraps(f)
    def decorated(*args, **kwargs):
        supplied = request.headers.get('X-Internal-Token', '')
        if not INTERNAL_API_TOKEN or not secrets.compare_digest(supplied, INTERNAL_API_TOKEN):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

def slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return slug[:50]

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
    return bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET)


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
        'client_id': DISCORD_CLIENT_ID, 'response_type': 'code', 'scope': 'identify',
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
                              auth=(DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET),
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
        user.avatar_url = user.avatar_url or avatar
        db.session.commit()
        return back(discord='connected')

    viewer = current_user()
    guest = viewer if viewer and viewer.is_guest else None
    user = existing
    if user and not user.is_active:
        return back(discord_error='inactive')
    if not user and guest:                 # the guest profile becomes the account
        user = keep_guest(guest, discord_user_id=discord_id, name=name, avatar_url=avatar)
        guest = None
    elif not user:
        user = User(discord_user_id=discord_id, name=name, avatar_color=random.choice(AVATAR_COLORS),
                    is_active=True)
        db.session.add(user)
    if guest:                              # signing into an existing account: bring the guest's plans
        absorb_guest(user, guest)
    if user.email is None:             # Discord-only accounts track Discord
        user.name, user.avatar_url = name, avatar or user.avatar_url
    user.discord_username = (me.get('username') or '')[:40] or None
    db.session.commit()
    _start_session(user)
    return back(discord='signed_in')


@app.route('/api/users/<int:user_id>/profile')
@require_auth
def get_user_profile(user_id):
    target = db.session.get(User, user_id)
    if not target or not target.is_active:
        return jsonify({'error': 'User not found'}), 404

    me = current_user()
    if me.id == target.id:
        return jsonify(target.to_dict())

    # Privacy: must share at least one group with active membership
    my_groups = {m.group_id for m in GroupMembership.query.filter_by(user_id=me.id, status='active').all()}
    their_groups = {m.group_id for m in GroupMembership.query.filter_by(user_id=target.id, status='active').all()}
    if not my_groups & their_groups:
        return jsonify({'error': 'You do not share a group with this user'}), 403

    return jsonify(target.to_dict())


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
    d = group.to_dict(include_members=bool(membership and membership.status == 'active'))
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
        result.append(m.to_dict())

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
    return jsonify(target.to_dict())


# ─── Routes: Theatres ─────────────────────────────────────────────────────────

@app.route('/api/theatres')
def get_theatres():
    theatres = Theatre.query.filter(Theatre.is_active.isnot(False)).order_by(Theatre.name).all()
    return jsonify([t.to_dict() for t in theatres])


# ─── Routes: Showtimes ────────────────────────────────────────────────────────

@app.route('/api/showtimes')
@require_auth
def get_showtimes():
    user = current_user()
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    theatre_slug = request.args.get('theatre')
    movie_id = request.args.get('movie_id')
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err

    query = Showtime.query.join(Movie).join(Theatre).filter(Showtime.is_cancelled.isnot(True))

    if start_str:
        query = query.filter(Showtime.start_time >= datetime.fromisoformat(start_str))
    if end_str:
        query = query.filter(Showtime.start_time <= datetime.fromisoformat(end_str))
    if theatre_slug:
        query = query.filter(Theatre.slug == theatre_slug)
    if movie_id:
        query = query.filter(Showtime.movie_id == int(movie_id))

    showtimes = query.order_by(Showtime.start_time).all()
    return jsonify(_with_attendance(user, showtimes, [
        s.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)
        for s in showtimes
    ], group_id))


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


@app.route('/api/showtimes/<int:showtime_id>')
def get_showtime(showtime_id):
    """Single showtime — the screening sheet and ?showtime= deep links.
    Club mode with ?group_id, public mode without."""
    user, group, err = view_scope()
    if err:
        return err
    group_id = group.id if group else None
    showtime = db.session.get(Showtime, showtime_id)
    if not showtime or showtime.is_cancelled:
        return jsonify({'error': 'Showtime not found'}), 404
    if not group:
        return jsonify(public_showtimes([showtime], user)[0])
    return jsonify(_with_attendance(user, [showtime], [
        showtime.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)], group_id)[0])


@app.route('/api/movies')
@require_auth
def get_movies():
    movies = Movie.query.all()
    return jsonify([m.to_dict() for m in movies])


@app.route('/api/movies/<int:movie_id>')
@require_auth
def get_movie_detail(movie_id):
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return jsonify({'error': 'Movie not found'}), 404
    return jsonify(movie.to_dict())


def _brief_user(u):
    return {'id': u.id, 'name': u.name, 'avatar_color': u.avatar_color}


@app.route('/api/films/<int:movie_id>')
def film_detail(movie_id):
    """A film's page: its details, every upcoming screening at the group's
    theatres (with the viewer's RSVPs and who's going), where the club stands
    on it (want to see / going / seen), and whether this week's screenings
    are rare. Public mode (no ?group_id): every tracked theatre, anonymous
    interest only, no club section."""
    user, group, err = view_scope()
    if err:
        return err
    group_id = group.id if group else None
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return jsonify({'error': 'Film not found'}), 404
    now = datetime.now()

    base = _group_showtime_query(group).filter(Showtime.movie_id == movie_id)
    upcoming = base.filter(Showtime.start_time >= now).order_by(Showtime.start_time).all()
    if group:
        showtimes = _with_attendance(user, upcoming, [
            s.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres) for s in upcoming
        ], group_id)
    else:
        showtimes = public_showtimes(upcoming, user)
    for d in showtimes:
        d.pop('movie', None)          # the page has it once, at the top

    members = {m.user_id: m.user for m in GroupMembership.query.filter_by(group_id=group_id, status='active') if m.user}
    watchers = {w.user_id for w in Watchlist.query.filter_by(movie_id=movie_id)}
    going = {r.user_id for s in upcoming for r in s.rsvps if r.group_id == group_id and r.status == 'going'}
    past = {s.id for s in base.filter(Showtime.start_time < now)}
    seen = {uid for uid in members if past and past & attended_showtime_ids(uid, {group_id})}

    rare = None
    week = [s for s in upcoming if s.start_time <= now + timedelta(days=7)]
    if week:
        venues = len({s.theatre_id for s in week})
        score, why = max((rarity(s, len(week), venues, now.year) for s in week), key=lambda x: x[0])
        if score >= RARE_MIN_SCORE:
            rare = {'score': score, 'reasons': why}

    if not group:
        want, _ = interest_counts([movie_id])
        return jsonify({
            'movie': movie.to_dict(), 'showtimes': showtimes, 'club': None, 'rare': rare,
            'interest': {'want': want.get(movie_id)},
            'viewer_wants': bool(user and Watchlist.query.filter_by(user_id=user.id, movie_id=movie_id).first()),
        })

    def people(ids):
        return [_brief_user(members[i]) for i in ids if i in members]

    return jsonify({
        'movie': movie.to_dict(),
        'showtimes': showtimes,
        'club': {'wanters': people(watchers), 'going': people(going), 'seen': people(seen)},
        'viewer_wants': user.id in watchers,
        'rare': rare,
    })


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


def view_scope():
    """(viewer or None, group or None, error). No group_id → public mode."""
    user = current_user()
    group_id = request.args.get('group_id', type=int)
    if not group_id:
        return user, None, None
    if not user:
        return None, None, (jsonify({'error': 'Not authenticated'}), 401)
    if not _active_membership(user, group_id):
        return user, None, (jsonify({'error': 'Not a member of this group'}), 403)
    return user, db.session.get(Group, group_id), None


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


def _cards_in(obj):
    """Every Discover card (a dict with 'movie' and 'club') inside a response."""
    if isinstance(obj, dict):
        if 'movie' in obj and 'club' in obj:
            yield obj
        for v in obj.values():
            yield from _cards_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _cards_in(v)


def publicize_cards(payload):
    """Discover cards in public mode: drop the club block, add anonymous interest."""
    cards = list(_cards_in(payload))
    want, going = interest_counts({c['movie']['id'] for c in cards}, {c['next']['showtime_id'] for c in cards if c.get('next')})
    for c in cards:
        c.pop('club', None)
        c['interest'] = {'want': want.get(c['movie']['id']),
                         'going': going.get(c['next']['showtime_id']) if c.get('next') else None}
    return payload


def public_cached(key, build):
    """Anonymous public responses, cached briefly per worker."""
    hit = _public_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < PUBLIC_CACHE_SECONDS:
        return hit[1]
    value = build()
    if len(_public_cache) > 500:
        _public_cache.clear()
    _public_cache[key] = (now, value)
    return value


def _discover_group():
    """(viewer, group or None, error): club mode with ?group_id, public otherwise."""
    return view_scope()


@app.route('/api/discover')
def discover_page():
    """Club mode with ?group_id; public mode (cached for visitors) without."""
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    if group:
        return jsonify(discover.discover(group, user))
    build = lambda: publicize_cards(discover.discover(None, user))
    return jsonify(build() if user else public_cached(('discover',), build))


@app.route('/api/discover/browse')
def discover_browse():
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    params = {k: request.args.get(k) for k in BROWSE_PARAMS}
    offset = max(0, request.args.get('offset', 0, type=int))
    if not group and params.get('club') not in (None, 'mine'):   # public mode: only your own plans
        params['club'] = None
    try:
        if group:
            return jsonify(discover.browse(group, user, params, offset=offset))
        build = lambda: publicize_cards(discover.browse(None, user, params, offset=offset))
        key = ('browse', offset, tuple(sorted((k, v) for k, v in params.items() if v)))
        return jsonify(build() if user else public_cached(key, build))
    except ValueError:
        return jsonify({'error': 'Bad date'}), 400


BROWSE_PARAMS = ('when', 'from', 'to', 'theatres', 'regions', 'genres', 'decade', 'format', 'time', 'rarity',
                 'club', 'runtime', 'mood', 'shelf', 'q', 'sort')


@app.route('/api/discover/calendar')
def discover_calendar():
    """The Calendar's screenings: every showing of the films matching Browse's
    filters (same parameters, from/to = the days shown), each marked rare as
    Discover would, plus facet counts for the Filters sheet."""
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    params = {k: request.args.get(k) for k in BROWSE_PARAMS}
    if not group and params.get('club') not in (None, 'mine'):   # public mode: only your own plans
        params['club'] = None

    def build():
        films, ctx, reasons, start, end = discover.select(group, user, params)
        rare = {f.movie.id: f.rare_reasons for f in films if f.rare_score >= ctx['rare_min']}
        shows = sorted((s for f in films for s in f.shows), key=lambda s: s.start_time)
        if group:
            dicts = _with_attendance(user, shows, [
                s.to_dict(user_id=user.id, group_id=group.id, user_genres=user.favorite_genres) for s in shows], group.id)
        else:
            dicts = public_showtimes(shows, user)
        for s, d in zip(shows, dicts):
            d['rare'] = rare.get(s.movie_id)
            d['shelf_reasons'] = reasons.get(s.movie_id)
        return {'showtimes': dicts, 'total': len(films), 'facets': discover.facets(films),
                'regions': discover.REGIONS,
                'title': discover.SHELF_TITLES.get(params.get('shelf'))
                or discover.MOODS.get(params.get('mood') or '', {}).get('label')}
    try:
        if group or user:
            return jsonify(build())
        return jsonify(public_cached(('calendar', tuple(sorted((k, v) for k, v in params.items() if v))), build))
    except ValueError:
        return jsonify({'error': 'Bad date'}), 400


@app.route('/api/discover/surprise')
def discover_surprise():
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    exclude = [_as_int(x) for x in (request.args.get('exclude') or '').split(',') if _as_int(x)]
    pick = discover.surprise(group, user, request.args.get('when', 'tonight'), exclude)
    if pick and not group:
        pick = publicize_cards(pick)
    return jsonify(pick or {'error': 'nothing_playing'}), (200 if pick else 404)


# ─── Link previews (Open Graph) ───────────────────────────────────────────────
# Discord (and other chat apps) fetch a link to show a preview card, but the
# site is a single-page app with one generic <head>. nginx sends those
# crawlers here instead (see frontend/nginx.conf); people never see these
# pages. Only public schedule information is used — never who's going.

def _og_page(title, description, image, path, large=False):
    import html as _html
    esc = _html.escape
    url = f"{FRONTEND_URL}{path}"
    image_tags = (f'<meta property="og:image" content="{esc(image)}">\n'
                  f'<meta name="twitter:image" content="{esc(image)}">') if image else ''
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{esc(title if title == 'Cinema Club DC' else f'{title} · Cinema Club DC')}</title>
<meta property="og:site_name" content="Cinema Club DC">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">
{image_tags}
<meta name="twitter:card" content="{'summary_large_image' if large else 'summary'}">
<meta name="theme-color" content="#dcb15c">
<meta http-equiv="refresh" content="0; url={esc(url)}">
</head><body><a href="{esc(url)}">{esc(title)}</a></body></html>"""
    resp = make_response(body)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Cache-Control'] = 'public, max-age=900'
    return resp


def _when_text(dt):
    return dt.strftime('%a %b %-d · %-I:%M %p')


def _blurb(text, limit=180):
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rsplit(' ', 1)[0] + '…'


@app.route('/api/og/films/<int:movie_id>')
def og_film(movie_id):
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return _og_page('Cinema Club DC', "DC's repertory and new-release screenings, together.", None, '/')
    now = datetime.now()
    upcoming = (Showtime.query.join(Theatre).filter(
        Showtime.movie_id == movie_id, Showtime.start_time >= now,
        Showtime.is_cancelled.isnot(True), Theatre.is_active.isnot(False))
        .order_by(Showtime.start_time).all())
    year = f" ({movie.release_year[:4]})" if movie.release_year else ''
    bits = []
    if upcoming:
        s = upcoming[0]
        fmt = f" · {s.format_label}" if s.format_label else ''
        bits.append(f"Next: {_when_text(s.start_time)} @ {s.theatre.short_name or s.theatre.name}{fmt}")
        theatres = len({x.theatre_id for x in upcoming})
        bits.append(f"{len(upcoming)} showing{'s' if len(upcoming) != 1 else ''}"
                    + (f" at {theatres} theatres" if theatres > 1 else ''))
    else:
        bits.append('No upcoming showings')
    if movie.director:
        bits.append(f"Dir. {movie.director}")
    description = ' · '.join(bits) + (f"\n{_blurb(movie.description)}" if movie.description else '')
    return _og_page(f"{movie.title}{year}", description, movie.backdrop_url or movie.poster_url,
                    f"/films/{movie_id}", large=bool(movie.backdrop_url))


@app.route('/api/og/showtimes/<int:showtime_id>')
def og_showtime(showtime_id):
    s = db.session.get(Showtime, showtime_id)
    if not s or not s.movie:
        return _og_page('Cinema Club DC', "DC's repertory and new-release screenings, together.", None, '/')
    bits = [s.theatre.name]
    if s.format_label:
        bits.append(s.format_label)
    if s.event_label and s.event_label != s.movie.title:
        bits.append(s.event_label)
    if s.is_cancelled:
        bits.append('cancelled')
    elif s.is_sold_out:
        bits.append('sold out')
    description = ' · '.join(bits) + (f"\n{_blurb(s.movie.description)}" if s.movie.description else '')
    return _og_page(f"{s.movie.title} — {_when_text(s.start_time)}", description,
                    s.movie.backdrop_url or s.movie.poster_url, f"/calendar?showtime={showtime_id}",
                    large=bool(s.movie.backdrop_url))


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


def _present_changed():
    from flask import g, has_request_context
    if has_request_context():
        g.discord_present = None


def on_discord(user):
    """Linked to Discord and in the club's server: the only people Discord sees."""
    return bool(user and user.discord_user_id and user.discord_user_id in _present()[0])


def present_user_ids():
    return _present()[1]


def can_share(user, group_id):
    """May this member's own actions go to the server at all?"""
    return discord_group(group_id) and on_discord(user)


def members_synced():
    """Has the bot reported the server's members yet? Until it has, nothing is posted."""
    return db.session.get(BotSetting, 'discord_members_synced_at') is not None


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


def poll_posts_changed(poll_id):
    """A poll was edited, closed, scored, un-scored or deleted: refresh (or
    remove) its announcement and results posts."""
    DiscordPost.query.filter(DiscordPost.kind.in_(('poll', 'poll_results')), DiscordPost.ref_id == poll_id,
                             DiscordPost.status == 'posted').update({'dirty': True}, synchronize_session=False)


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


def _can_manage_post(user, p):
    """Whoever shared it, an organizer for poll posts, or an admin."""
    if p.user_id == user.id:
        return True
    m = GroupMembership.query.filter_by(user_id=user.id, group_id=p.group_id, status='active').first()
    return role_at_least(m, 'organizer' if p.kind in ('poll', 'poll_results') else 'admin')


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


@app.route('/api/rsvp', methods=['POST'])
@require_auth
def rsvp():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    status = data.get('status')
    group_id = _as_int(data.get('group_id'))
    # No club: a personal RSVP (R5b) — only you ever see it.
    if group_id:
        _, err = require_role(user, group_id, 'member')
        if err:
            return err

    prev = RSVP.query.filter_by(user_id=user.id, showtime_id=showtime_id, group_id=group_id).first()
    prev_status = prev.status if prev else None

    showtime, err = apply_rsvp(user, showtime_id, status, group_id)
    if err:
        return err

    # Going / maybe (a real change) in the Discord server's group: share it if
    # they always do, or ask. (Discord's own /rsvp posts for itself.)
    prompt = False
    if status in ('going', 'maybe') and status != prev_status and showtime and can_share(user, group_id):
        pref = share_prefs(user)['rsvp']
        if pref == 'always':
            queue_rsvp_share(user, showtime.id, group_id)
        elif pref == 'ask':
            prompt = True

    if not group_id:
        return jsonify(public_showtimes([showtime], user)[0])
    d = _with_attendance(user, [showtime], [
        showtime.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)], group_id)[0]
    if prompt and d.get('discord') and not d['discord']['my_share']:
        d['discord']['prompt'] = True
    return jsonify(d)


@app.route('/api/discord/prefs', methods=['GET', 'PUT'])
@require_auth
def discord_prefs():
    """Your "Ask / Always / Never" choice per kind, and whether sharing is
    available to you: in the club tied to the Discord server, with Discord
    linked, and in that server. `reason` says what's missing."""
    user = current_user()
    if request.method == 'PUT':
        for kind, value in (request.json or {}).items():
            set_share_pref(user, kind, value)
        db.session.commit()
    reason = ('no_club' if _active_membership(user, DISCORD_GROUP_ID) is None
              else 'not_linked' if not user.discord_user_id
              else 'not_in_server' if not on_discord(user) else None)
    return jsonify({'prefs': share_prefs(user), 'available': reason is None, 'reason': reason})


@app.route('/api/discord/shares', methods=['POST'])
@require_auth
def create_share():
    """Share to #movies: kind rsvp (your going/maybe), invite ("who's in?"),
    poll / poll_results (group admins), or thread (start a screening's
    thread). Optional post_at (local time) schedules invites and polls;
    remember=true makes "always" your choice for that kind."""
    user = current_user()
    data = request.json or {}
    kind, group_id = data.get('kind'), _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'member')
    if err:
        return err
    if not discord_group(group_id):
        return jsonify({'error': 'This group has no Discord server'}), 400
    if not on_discord(user):
        return jsonify({'error': "Only members in the club's Discord server (with Discord linked) can share there",
                        'code': 'not_on_discord'}), 403
    now = datetime.now()
    post_at = _parse_post_at(data.get('post_at'), now)
    if post_at is None:
        return jsonify({'error': 'Pick a time in the next 60 days'}), 400

    if kind in ('rsvp', 'invite', 'thread'):
        showtime = db.session.get(Showtime, _as_int(data.get('showtime_id')) or 0)
        if not showtime:
            return jsonify({'error': 'Showtime not found'}), 404
        if kind == 'rsvp':
            r = RSVP.query.filter_by(user_id=user.id, showtime_id=showtime.id, group_id=group_id).first()
            if not r or r.status not in ('going', 'maybe'):
                return jsonify({'error': 'RSVP going or maybe first'}), 400
            if data.get('remember'):
                set_share_pref(user, 'rsvp', 'always')
            return jsonify(post_dict(queue_rsvp_share(user, showtime.id, group_id, now))), 201
        if kind == 'thread':
            t = ShowtimeThread.query.filter_by(showtime_id=showtime.id, group_id=group_id).first()
            if t:
                return jsonify({'thread_url': t.url}), 200
            post_at = now
        existing = _live_post(kind, showtime.id, group_id)
        # A finished thread request doesn't count: the thread itself (checked
        # above) does, and it may have been deleted in Discord since.
        if existing and (kind == 'invite' or existing.status == 'pending'):
            return jsonify(post_dict(existing)), 200
        post = DiscordPost(group_id=group_id, kind=kind, user_id=user.id, ref_id=showtime.id, post_at=post_at,
                           note=(data.get('note') or '').strip()[:200] or None)
    elif kind in ('poll', 'poll_results'):
        poll = db.session.get(Poll, _as_int(data.get('poll_id')) or 0)
        if not poll or poll.group_id != group_id:
            return jsonify({'error': 'Poll not found'}), 404
        if not role_at_least(_active_membership(user, group_id), 'organizer'):
            return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403
        if kind == 'poll_results' and poll.status != 'scored':
            return jsonify({'error': 'Score the poll first'}), 400
        if data.get('remember'):
            set_share_pref(user, 'poll', 'always')
            db.session.commit()
        return jsonify(post_dict(queue_poll_post(poll, user, kind, post_at))), 201
    else:
        return jsonify({'error': 'Unknown kind'}), 400
    db.session.add(post)
    db.session.commit()
    return jsonify(post_dict(post)), 201


def _manageable_post(post_id):
    user = current_user()
    p = db.session.get(DiscordPost, post_id)
    if not p or not _active_membership(user, p.group_id):
        return None, (jsonify({'error': 'Not found'}), 404)
    if not _can_manage_post(user, p):
        return None, (jsonify({'error': 'Only whoever shared it (or a group admin) can change it'}), 403)
    return p, None


@app.route('/api/discord/shares/<int:post_id>/now', methods=['POST'])
@require_auth
def share_now(post_id):
    """Post a scheduled share right away."""
    p, err = _manageable_post(post_id)
    if err:
        return err
    if p.status == 'pending':
        p.post_at = datetime.now()
        db.session.commit()
    return jsonify(post_dict(p))


@app.route('/api/discord/shares/<int:post_id>', methods=['DELETE'])
@require_auth
def unshare(post_id):
    """Cancel a share that hasn't gone out, or take a posted one down. For an
    RSVP post, ?showtime_id= takes out just that screening."""
    p, err = _manageable_post(post_id)
    if err:
        return err
    showtime_id = request.args.get('showtime_id', type=int)
    if p.kind == 'rsvp' and showtime_id:
        unshare_rsvp(p.user_id, showtime_id, p.group_id)
    elif p.status == 'pending':
        p.status = 'cancelled'
    elif p.status == 'posted':
        p.status, p.dirty = 'removing', True
    db.session.commit()
    return jsonify(post_dict(p))


# ─── Discord posts: the bot's queue ───────────────────────────────────────────

@app.route('/api/internal/discord/posts/due')
@require_internal
def internal_posts_due():
    """What the bot should do now: post shares whose time has come, update
    posted ones whose content changed, delete ones with nothing left to show.
    Each item: {id, kind, action: post|edit|delete, message_id, data}.
    Nothing until the bot has reported who's in the server."""
    group_id = request.args.get('group_id', type=int)
    now = datetime.now()
    out = []
    if not members_synced():
        return jsonify(out)
    for p in (DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.status == 'pending',
                                       DiscordPost.post_at <= now)
              .order_by(DiscordPost.post_at, DiscordPost.id).limit(10)):
        data = render_post(p, now) if on_discord(p.user) else None
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
    """Who's in the club's server, from the bot: {ids: [...], full: true} is
    the whole list (on start, and every half hour); {joined: [...]} /
    {left: [...]} are changes as they happen. Screenings whose Discord cards
    list someone who joined or left are refreshed."""
    data = request.json or {}
    clean = lambda key: {str(i) for i in data.get(key) or [] if str(i).isdigit()}
    current = {r[0] for r in db.session.query(DiscordServerMember.discord_user_id)}
    if data.get('full'):
        ids = clean('ids')
        joined, left = ids - current, current - ids
    else:
        joined, left = clean('joined') - current, clean('left') & current
    if left:
        DiscordServerMember.query.filter(DiscordServerMember.discord_user_id.in_(left)).delete(synchronize_session=False)
    for i in joined:
        db.session.add(DiscordServerMember(discord_user_id=i))
    changed = joined | left
    if changed:
        users = [u.id for u in User.query.filter(User.discord_user_id.in_(changed))]
        upcoming = {r.showtime_id for r in RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id).filter(
            RSVP.user_id.in_(users), RSVP.group_id == DISCORD_GROUP_ID, Showtime.start_time >= datetime.now())} \
            if users else set()
        if upcoming:
            ShowtimeThread.query.filter(ShowtimeThread.group_id == DISCORD_GROUP_ID,
                                        ShowtimeThread.showtime_id.in_(upcoming)) \
                .update({'card_dirty': True}, synchronize_session=False)
            DiscordPost.query.filter(DiscordPost.group_id == DISCORD_GROUP_ID, DiscordPost.kind == 'invite',
                                     DiscordPost.ref_id.in_(upcoming), DiscordPost.status == 'posted') \
                .update({'dirty': True}, synchronize_session=False)
    if data.get('full'):
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
        p.status, p.posted_at = 'posted', datetime.now()
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


def watchlist_items(user):
    """A member's watchlist, newest first, each with its next showing (if any)."""
    rows = Watchlist.query.filter_by(user_id=user.id).order_by(Watchlist.created_at.desc()).all()
    nxt = next_showings({w.movie_id for w in rows})
    return [{'movie': {'id': w.movie.id, 'title': w.movie.title, 'release_year': w.movie.release_year,
                       'poster_url': w.movie.poster_url},
             'added_at': w.created_at.isoformat() if w.created_at else None,
             'next': _screening_item(nxt[w.movie_id]) if w.movie_id in nxt else None}
            for w in rows if w.movie]


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


@app.route('/api/users/<int:user_id>/watchlist')
@require_auth
def user_watchlist(user_id):
    me, target, _, err = _profile_target(user_id)
    if err:
        return err
    return jsonify({'own': me.id == target.id, 'items': watchlist_items(target)})


@app.route('/api/users/<int:user_id>/rsvps')
@require_auth
def user_rsvps(user_id):
    """Upcoming screenings a member is going to (or might), from groups you share."""
    me, target, groups, err = _profile_target(user_id)
    if err:
        return err
    own = me.id == target.id
    return jsonify({'own': own,
                    'items': [_screening_item(s, st) for s, st in upcoming_rsvps(target, groups, personal=own)]})


@app.route('/api/users/<int:user_id>/compare')
@require_auth
def user_compare(user_id):
    me, target, groups, err = _profile_target(user_id)
    if err:
        return err
    if me.id == target.id:
        return jsonify({'error': 'Pick someone else to compare with'}), 400
    return jsonify(compare_members(me, target, groups))


# ─── Feed ─────────────────────────────────────────────────────────────────────
# Built straight from the source tables (RSVPs, check-ins, comments, reactions,
# watchlists, polls, memberships), so undoing something — an un-RSVP, a removed
# watchlist film — simply drops it, and Discord activity shows up like any other.
# Activity is grouped into one card per screening / film / poll / day of joins,
# ordered by its latest activity.

FEED_DAYS = 90
FEED_PAGE = 20


def _feed_user(u):
    return {'id': u.id, 'name': u.name, 'avatar_color': u.avatar_color, 'discord_only': u.email is None}


def _went_visible_in(group_id, rows):
    """Check-ins aren't per group, so a "went" shows in a group's feed only if the
    RSVP was made there, or there was no RSVP anywhere (logged directly) — a
    check-in never reveals plans made in another group."""
    if not rows:
        return []
    pairs = {(r.user_id, r.showtime_id) for r in rows}
    rsvp_groups = {}
    for r in RSVP.query.filter(RSVP.user_id.in_({p[0] for p in pairs}),
                               RSVP.showtime_id.in_({p[1] for p in pairs})):
        rsvp_groups.setdefault((r.user_id, r.showtime_id), set()).add(r.group_id)
    return [r for r in rows if (r.user_id, r.showtime_id) not in rsvp_groups
            or group_id in rsvp_groups[(r.user_id, r.showtime_id)]]


def feed_events(group_id, since):
    """(kind, card_key, at, user_id, detail) for the group's activity since `since`."""
    member_ids = {m.user_id for m in GroupMembership.query.filter_by(group_id=group_id, status='active')}
    ev = []
    for r in RSVP.query.filter(RSVP.group_id == group_id, RSVP.status.in_(('going', 'maybe')),
                               RSVP.updated_at >= since):
        ev.append(('rsvp', f's{r.showtime_id}', r.updated_at, r.user_id, r.status))
    for m in Message.query.filter(Message.group_id == group_id, Message.created_at >= since):
        ev.append(('comment', f's{m.showtime_id}', m.created_at, m.user_id, None))
    for r in Reaction.query.filter(Reaction.group_id == group_id, Reaction.created_at >= since):
        ev.append(('reaction', f's{r.showtime_id}', r.created_at, r.user_id, r.emoji))
    if member_ids:
        went = Attendance.query.filter(Attendance.user_id.in_(member_ids), Attendance.status == 'went',
                                       Attendance.answered_at >= since).all()
        for a in _went_visible_in(group_id, went):
            ev.append(('went', f's{a.showtime_id}', a.answered_at, a.user_id, None))
        for w in Watchlist.query.filter(Watchlist.user_id.in_(member_ids), Watchlist.created_at >= since):
            ev.append(('watch', f'w{w.movie_id}', w.created_at, w.user_id, None))
    for m in GroupMembership.query.filter(GroupMembership.group_id == group_id, GroupMembership.status == 'active',
                                          GroupMembership.joined_at >= since):
        ev.append(('joined', f'j{m.joined_at.date().isoformat()}', m.joined_at, m.user_id, None))
    ev = [e for e in ev if e[3] in member_ids]   # people who've since left drop out
    for p in Poll.query.filter_by(group_id=group_id):
        for kind, at in (('poll_opened', p.created_at), ('poll_closed', p.closed_at), ('poll_scored', p.scored_at)):
            if at and at >= since:
                ev.append((kind, f'p{p.id}', at, p.created_by, None))
    return ev, member_ids


def feed_skeletons(group_id):
    """Cards (key, latest activity time, their events), newest first."""
    events, member_ids = feed_events(group_id, _utcnow_naive() - timedelta(days=FEED_DAYS))
    cards = {}
    for e in events:
        cards.setdefault(e[1], {'key': e[1], 'events': []})['events'].append(e)
    for c in cards.values():
        c['events'].sort(key=lambda e: e[2], reverse=True)
        c['at'] = c['events'][0][2]
    return sorted(cards.values(), key=lambda c: (c['at'], c['key']), reverse=True), member_ids


def _feed_screening(viewer, group_id, sid, events, users, member_ids):
    s = db.session.get(Showtime, sid)
    if not s or not s.movie:
        return None
    showtime = _with_attendance(viewer, [s], [
        s.to_dict(user_id=viewer.id, group_id=group_id, user_genres=viewer.favorite_genres)], group_id)[0]
    went_rows = [a for a in Attendance.query.filter_by(showtime_id=sid, status='went') if a.user_id in member_ids]
    went_ids = [a.user_id for a in _went_visible_in(group_id, went_rows)]
    went = User.query.filter(User.id.in_(went_ids)).all() if went_ids else []
    last = (Message.query.filter_by(showtime_id=sid, group_id=group_id)
            .order_by(Message.created_at.desc()).first())
    activity, seen = [], set()
    for kind, _, at, uid, detail in events:
        if (uid, kind) in seen or uid not in users:
            continue
        seen.add((uid, kind))
        activity.append({'kind': kind, 'user': _feed_user(users[uid]), 'detail': detail, 'at': utc_iso(at)})
    return {'type': 'screening', 'showtime': showtime, 'went': [_feed_user(u) for u in went],
            'latest_comment': {'user': _feed_user(last.user), 'body': last.body[:280],
                               'at': utc_iso(last.created_at)} if last else None,
            'activity': activity[:4]}


def _feed_watchlist(viewer, movie_id, events, users, member_ids):
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return None
    adders = list(dict.fromkeys(e[3] for e in events if e[3] in users))
    nxt = next_showings({movie_id}).get(movie_id)
    return {'type': 'watchlist',
            'movie': {'id': movie.id, 'title': movie.title, 'release_year': movie.release_year,
                      'poster_url': movie.poster_url},
            'users': [_feed_user(users[u]) for u in adders],
            'wanters': Watchlist.query.filter(Watchlist.movie_id == movie_id,
                                              Watchlist.user_id.in_(member_ids)).count() if member_ids else 0,
            'viewer_wants': Watchlist.query.filter_by(user_id=viewer.id, movie_id=movie_id).first() is not None,
            'next': _screening_item(nxt) if nxt else None}


def _feed_poll(viewer, poll_id):
    p = db.session.get(Poll, poll_id)
    if not p:
        return None
    cat_ids = [c.id for c in p.categories]
    voters = {v.user_id for v in PollVote.query.filter(PollVote.category_id.in_(cat_ids))} if cat_ids else set()
    return {'type': 'poll',
            'poll': {'id': p.id, 'title': p.title, 'status': p.status, 'poll_type': p.poll_type,
                     'categories': len(cat_ids), 'creator': p.creator.name if p.creator else None},
            'voters': len(voters), 'you_voted': viewer.id in voters}


def hydrate_feed(viewer, group_id, skeletons, member_ids):
    uids = {e[3] for c in skeletons for e in c['events']}
    users = {u.id: u for u in User.query.filter(User.id.in_(uids))} if uids else {}
    out = []
    for c in skeletons:
        kind, ref = c['key'][0], c['key'][1:]
        if kind == 's':
            card = _feed_screening(viewer, group_id, int(ref), c['events'], users, member_ids)
        elif kind == 'w':
            card = _feed_watchlist(viewer, int(ref), c['events'], users, member_ids)
        elif kind == 'p':
            card = _feed_poll(viewer, int(ref))
        else:
            joined = list(dict.fromkeys(e[3] for e in c['events'] if e[3] in users))
            card = {'type': 'joined', 'users': [_feed_user(users[u]) for u in joined]}
        if card:
            out.append({'key': c['key'], 'at': utc_iso(c['at']), **card})
    return out


@app.route('/api/feed')
@require_auth
def feed():
    """The group's recent activity as cards, FEED_PAGE at a time (?offset=)."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    offset = max(0, request.args.get('offset', 0, type=int))
    skeletons, member_ids = feed_skeletons(group_id)
    page = skeletons[offset:offset + FEED_PAGE]
    more = len(skeletons) > offset + FEED_PAGE
    return jsonify({'cards': hydrate_feed(current_user(), group_id, page, member_ids),
                    'next_offset': offset + FEED_PAGE if more else None, 'days': FEED_DAYS})


@app.route('/api/club/week')
@require_auth
def club_week():
    """Discover's "This week in the club" strip: screenings members are going
    to in the next 7 days (most-attended first), open polls, and how many
    comments others left this week (with the latest)."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    viewer, now = current_user(), datetime.now()
    rows = (db.session.query(RSVP, Showtime).join(Showtime, RSVP.showtime_id == Showtime.id)
            .filter(RSVP.group_id == group_id, RSVP.status == 'going',
                    Showtime.start_time >= now, Showtime.start_time <= now + timedelta(days=7)).all())
    by_show = {}
    for r, s in rows:
        by_show.setdefault(s.id, (s, []))[1].append(r.user)
    plans = sorted(by_show.values(), key=lambda x: (-len(x[1]), x[0].start_time))[:4]

    polls = Poll.query.filter_by(group_id=group_id, status='open').order_by(Poll.created_at.desc()).limit(3).all()
    open_polls = []
    for p in polls:
        cat_ids = [c.id for c in p.categories]
        voted = bool(cat_ids) and PollVote.query.filter(PollVote.category_id.in_(cat_ids),
                                                        PollVote.user_id == viewer.id).first() is not None
        open_polls.append({'id': p.id, 'title': p.title, 'you_voted': voted})

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    recent = (Message.query.filter(Message.group_id == group_id, Message.user_id != viewer.id,
                                   Message.created_at >= since)
              .order_by(Message.created_at.desc()))
    latest = recent.first()
    return jsonify({
        'plans': [{'showtime_id': s.id, 'start_time': s.start_time.isoformat(),
                   'movie': {'id': s.movie.id, 'title': s.movie.title, 'poster_url': s.movie.poster_url},
                   'theatre': s.theatre.short_name or s.theatre.name,
                   'going': [_brief_user(u) for u in users], 'you_going': any(u.id == viewer.id for u in users)}
                  for s, users in plans],
        'polls': open_polls,
        'comments': {'count': recent.count(),
                     'latest': {'showtime_id': latest.showtime_id, 'movie': db.session.get(Showtime, latest.showtime_id).movie.title,
                                'user': latest.user.name, 'body': latest.body[:140]} if latest else None},
    })


@app.route('/api/attendance/pending')
@require_auth
def attendance_pending():
    """The signed-in member's "Did you make it?" list."""
    return jsonify([_screening_item(s) for s in pending_attendance(current_user())])


@app.route('/api/attendance', methods=['POST'])
@require_auth
def attendance_set():
    data = request.json or {}
    showtime, err = set_attendance(current_user(), data.get('showtime_id'), data.get('status'), 'site')
    if err:
        return err
    return jsonify({'showtime_id': showtime.id, 'status': data.get('status')})


@app.route('/api/users/<int:user_id>/history')
@require_auth
def user_history(user_id):
    me, target, groups, err = _profile_target(user_id)
    if err:
        return err
    if me.id == target.id:
        return jsonify({'own': True, 'items': history_items(target, True)})
    # Others see RSVP-based attendance only from groups you share.
    return jsonify({'own': False, 'items': history_items(target, False, groups)})


# ─── Routes: Reactions ────────────────────────────────────────────────────────

@app.route('/api/reactions', methods=['POST'])
@require_auth
def toggle_reaction():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    group_id = _as_int(data.get('group_id'))
    emoji = data.get('emoji')
    if group_id:                       # no club: a personal reaction, public only as a count (R5b)
        _, err = require_role(user, group_id, 'member')
        if err:
            return err

    if not showtime_id or not emoji:
        return jsonify({'error': 'showtime_id and emoji required'}), 400
    if not db.session.get(Showtime, _as_int(showtime_id) or 0):
        return jsonify({'error': 'Showtime not found'}), 404

    if emoji not in CINEMA_EMOJIS:
        return jsonify({'error': 'Invalid emoji'}), 400

    existing = Reaction.query.filter_by(
        user_id=user.id, showtime_id=showtime_id, group_id=group_id, emoji=emoji
    ).first()

    if existing:
        db.session.delete(existing)
    else:
        reaction = Reaction(user_id=user.id, showtime_id=showtime_id, group_id=group_id, emoji=emoji)
        db.session.add(reaction)
    db.session.commit()

    if not group_id:
        return jsonify(public_reactions([_as_int(showtime_id)], user).get(_as_int(showtime_id), {}))
    # Return updated reactions for this showtime+group
    reactions = Reaction.query.filter_by(showtime_id=showtime_id, group_id=group_id).all()
    summary = {}
    for r in reactions:
        if r.emoji not in summary:
            summary[r.emoji] = {'count': 0, 'users': [], 'user_reacted': False}
        summary[r.emoji]['count'] += 1
        summary[r.emoji]['users'].append({'id': r.user.id, 'name': r.user.name})
        if r.user_id == user.id:
            summary[r.emoji]['user_reacted'] = True

    return jsonify(summary)


@app.route('/api/reactions')
@require_auth
def get_reactions():
    showtime_id = request.args.get('showtime_id', type=int)
    group_id = request.args.get('group_id', type=int)
    user = current_user()
    err = require_group_member(group_id)
    if err:
        return err

    if not showtime_id:
        return jsonify({'error': 'showtime_id required'}), 400

    reactions = Reaction.query.filter_by(showtime_id=showtime_id, group_id=group_id).all()
    summary = {}
    for r in reactions:
        if r.emoji not in summary:
            summary[r.emoji] = {'count': 0, 'users': [], 'user_reacted': False}
        summary[r.emoji]['count'] += 1
        summary[r.emoji]['users'].append({'id': r.user.id, 'name': r.user.name})
        if r.user_id == user.id:
            summary[r.emoji]['user_reacted'] = True

    return jsonify(summary)


# ─── Routes: Messages ─────────────────────────────────────────────────────────

@app.route('/api/messages')
@require_auth
def get_messages():
    showtime_id = request.args.get('showtime_id', type=int)
    group_id = request.args.get('group_id', type=int)
    since = request.args.get('since')
    err = require_group_member(group_id)
    if err:
        return err

    if not showtime_id:
        return jsonify({'error': 'showtime_id required'}), 400

    query = Message.query.filter_by(showtime_id=showtime_id, group_id=group_id)
    since_dt = parse_utc(since) if since else None
    if since_dt:
        query = query.filter(Message.created_at > since_dt)

    messages = query.order_by(Message.created_at.asc()).limit(100).all()
    viewer = current_user()
    return jsonify([_message_dict(m, viewer) for m in messages])


def _message_dict(m, viewer):
    return {
        'id': m.id,
        'user': {'id': m.user.id, 'name': m.user.name, 'avatar_color': m.user.avatar_color},
        'body': m.body,
        'created_at': utc_iso(m.created_at),
        'via_discord': m.source in ('discord', 'discord_bot'),
        'can_delete': m.user_id == viewer.id and m.deletable_on_site,
    }


@app.route('/api/messages', methods=['POST'])
@require_auth
def post_message():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    group_id = _as_int(data.get('group_id'))
    body = (data.get('body') or '').strip()
    _, err = require_role(user, group_id, 'member')
    if err:
        return err

    if not showtime_id or not body:
        return jsonify({'error': 'showtime_id and body required'}), 400

    if len(body) > 2000:
        return jsonify({'error': 'Message too long'}), 400

    if not db.session.get(Showtime, _as_int(showtime_id)):
        return jsonify({'error': 'Showtime not found'}), 404
    # source='site' queues it for the screening's Discord thread — only if it
    # has one, the writer is in the club's server, and they left "also post in
    # Discord" on (R3d).
    to_discord = data.get('to_discord')
    if not isinstance(to_discord, bool):
        to_discord = share_prefs(user)['comment'] != 'never'
    to_discord = to_discord and can_share(user, _as_int(group_id))
    msg = Message(user_id=user.id, showtime_id=showtime_id, group_id=group_id, body=body, source='site',
                  to_discord=to_discord)
    db.session.add(msg)
    db.session.commit()
    return jsonify(_message_dict(msg, user)), 201


@app.route('/api/messages/<int:message_id>', methods=['DELETE'])
@require_auth
def delete_message(message_id):
    """Delete your own comment. If it has a copy in the Discord thread, the bot
    removes that too. Comments typed in Discord are deleted there instead."""
    user = current_user()
    msg = db.session.get(Message, message_id)
    if not msg or msg.user_id != user.id:
        return jsonify({'error': 'Not found'}), 404
    if not msg.deletable_on_site:
        return jsonify({'error': 'This was posted in Discord — delete it there.'}), 400
    if msg.discord_message_id:
        thread = ShowtimeThread.query.filter_by(showtime_id=msg.showtime_id, group_id=msg.group_id).first()
        if thread:
            db.session.add(DiscordDeletion(thread_id=thread.thread_id, discord_message_id=msg.discord_message_id))
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'deleted': message_id})


# ─── Routes: Calendar Export ──────────────────────────────────────────────────

@app.route('/api/showtimes/<int:sid>/ical')
def showtime_ical(sid):
    showtime = db.session.get(Showtime, sid)
    if not showtime:
        return jsonify({'error': 'Showtime not found'}), 404

    movie = showtime.movie
    theatre = showtime.theatre
    start = showtime.start_time
    end = showtime.end_time or (start + timedelta(minutes=(movie.runtime_minutes or 120) + 20))

    def fmt_dt(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    desc_parts = []
    if movie.director:
        desc_parts.append(f"Dir. {movie.director}")
    if movie.runtime_minutes:
        desc_parts.append(f"{movie.runtime_minutes} min")
    if showtime.purchase_link:
        desc_parts.append(f"Tickets: {showtime.purchase_link}")
    description = ' | '.join(desc_parts)

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CinemaClubDC//EN
BEGIN:VEVENT
DTSTART:{fmt_dt(start)}
DTEND:{fmt_dt(end)}
SUMMARY:{movie.title}
LOCATION:{theatre.name} - {theatre.address or ''}
DESCRIPTION:{description}
URL:{showtime.purchase_link or theatre.website or ''}
END:VEVENT
END:VCALENDAR"""

    response = make_response(ics)
    response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{movie.title}.ics"'
    return response


@app.route('/api/showtimes/<int:sid>/gcal-url')
def showtime_gcal_url(sid):
    showtime = db.session.get(Showtime, sid)
    if not showtime:
        return jsonify({'error': 'Showtime not found'}), 404

    movie = showtime.movie
    theatre = showtime.theatre
    start = showtime.start_time
    end = showtime.end_time or (start + timedelta(minutes=(movie.runtime_minutes or 120) + 20))

    def fmt_gcal(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    details = []
    if movie.director:
        details.append(f"Dir. {movie.director}")
    if showtime.purchase_link:
        details.append(f"Tickets: {showtime.purchase_link}")

    from urllib.parse import quote
    url = (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(movie.title)}"
        f"&dates={fmt_gcal(start)}/{fmt_gcal(end)}"
        f"&location={quote(theatre.name + ', ' + (theatre.address or ''))}"
        f"&details={quote(' | '.join(details))}"
    )

    return jsonify({'url': url})


# ─── Routes: Polls ────────────────────────────────────────────────────────────

import json as _json

def _require_group_member(group_id):
    """Return (user, membership) or abort with JSON error."""
    user = current_user()
    membership = GroupMembership.query.filter_by(
        user_id=user.id, group_id=group_id, status='active'
    ).first()
    return user, membership


@app.route('/api/groups/<int:group_id>/polls', methods=['GET'])
@require_auth
def get_group_polls(group_id):
    user, membership = _require_group_member(group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403
    polls = Poll.query.filter_by(group_id=group_id).order_by(Poll.created_at.desc()).all()
    # For the list (R6a): how many voted, and how far you've got.
    cat_poll = {c.id: c.poll_id for c in PollCategory.query.filter(PollCategory.poll_id.in_([p.id for p in polls]))} if polls else {}
    voters, mine = {}, {}
    for cat_id, uid in (db.session.query(PollVote.category_id, PollVote.user_id)
                        .filter(PollVote.category_id.in_(cat_poll)).distinct() if cat_poll else []):
        pid = cat_poll[cat_id]
        voters.setdefault(pid, set()).add(uid)
        if uid == user.id:
            mine.setdefault(pid, set()).add(cat_id)
    return jsonify([{**p.to_dict(), 'voters': len(voters.get(p.id, ())), 'you_picked': len(mine.get(p.id, ()))}
                    for p in polls])


@app.route('/api/groups/<int:group_id>/polls', methods=['POST'])
@require_auth
def create_poll(group_id):
    user, membership = _require_group_member(group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403
    data = request.json or {}
    poll, err = build_poll(group_id, user, data)
    if err:
        return err
    draft = db.session.get(PollDraft, _as_int(data.get('draft_id')) or 0)
    if draft and draft.group_id == group_id:          # made from an AI draft (R6a)
        draft.poll_id = poll.id
        db.session.commit()
    announce_new_poll(poll, user, data)
    return jsonify(poll.to_dict(include_categories=True)), 201


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


@app.route('/api/groups/<int:group_id>/polls/draft', methods=['POST'])
@require_auth
def draft_poll(group_id):
    """{prompt} → an editable draft (not a poll yet). Organizers and admins."""
    user = current_user()
    _, err = require_role(user, group_id, 'organizer')
    if err:
        return err
    data = request.json or {}
    body, status = _draft_poll(user, db.session.get(Group, group_id), data.get('prompt'), data.get('scope') or 'playing')
    return jsonify(body), status


@app.route('/api/poll-drafts/<int:draft_id>')
@require_auth
def get_poll_draft(draft_id):
    """A saved draft for the editor (e.g. "Open in editor" from Discord)."""
    user = current_user()
    d = db.session.get(PollDraft, draft_id)
    if not d:
        return jsonify({'error': 'Draft not found'}), 404
    _, err = require_role(user, d.group_id, 'organizer')
    if err:
        return err
    return jsonify({'id': d.id, 'group_id': d.group_id, 'prompt': d.prompt, 'poll_id': d.poll_id, **_json.loads(d.data_json)})


@app.route('/api/internal/polls/draft', methods=['POST'])
@require_internal
def internal_draft_poll():
    """The bot's /poll make: — organizers only, same rules as the site."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group_id = _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'organizer')
    if err:
        return err
    body, status = _draft_poll(user, db.session.get(Group, group_id), data.get('prompt'), data.get('scope') or 'playing')
    return jsonify(body), status


@app.route('/api/internal/poll-drafts/<int:draft_id>/create', methods=['POST'])
@require_internal
def internal_create_from_draft(draft_id):
    """Discord's "Create now": the draft becomes an open poll, announced in #movies."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    d = db.session.get(PollDraft, draft_id)
    if not d:
        return jsonify({'error': 'draft_not_found'}), 404
    _, err = require_role(user, d.group_id, 'organizer')
    if err:
        return err
    if d.poll_id and db.session.get(Poll, d.poll_id):
        return jsonify({'error': 'already_created', 'poll_id': d.poll_id}), 409
    draft = _json.loads(d.data_json)
    poll, err = build_poll(d.group_id, user, draft)
    if err:
        return err
    d.poll_id = poll.id
    db.session.commit()
    announce_new_poll(poll, user, {'announce': 'now'})
    return jsonify(poll.to_dict(include_categories=True)), 201


@app.route('/api/groups/<int:group_id>/polls/oscars', methods=['POST'])
@require_auth
def create_oscars_poll(group_id):
    user, membership = _require_group_member(group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    # Load template
    template_path = os.path.join(os.path.dirname(__file__), 'oscars_2026.json')
    if not os.path.exists(template_path):
        return jsonify({'error': 'Oscars template not found'}), 404

    with open(template_path) as f:
        tmpl = _json.load(f)

    data = request.json or {}
    scoring_mode = data.get('scoring_mode', 'confidence')

    poll = Poll(
        group_id=group_id,
        created_by=user.id,
        title=tmpl.get('title', 'Oscar Predictions'),
        description=tmpl.get('description', ''),
        poll_type='prediction',
        scoring_mode=scoring_mode,
    )
    db.session.add(poll)
    db.session.flush()

    for i, cat_data in enumerate(tmpl.get('categories', [])):
        cat = PollCategory(
            poll_id=poll.id,
            title=cat_data['title'],
            sort_order=i,
        )
        db.session.add(cat)
        db.session.flush()
        for j, nom in enumerate(cat_data.get('nominees', [])):
            extra = nom.get('extra')
            opt = PollOption(
                category_id=cat.id,
                text=nom['text'],
                sort_order=j,
                extra_data=_json.dumps(extra) if extra else None,
            )
            db.session.add(opt)

    db.session.commit()
    announce_new_poll(poll, user, data)
    return jsonify(poll.to_dict(include_categories=True)), 201


@app.route('/api/polls/<int:poll_id>', methods=['GET'])
@require_auth
def get_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403
    d = poll.to_dict(include_categories=True, user_id=user.id)
    if can_share(user, poll.group_id):
        live = {k: _live_post(k, poll.id, poll.group_id) for k in ('poll', 'poll_results')}
        d['discord'] = {'announce': post_dict(live['poll']) if live['poll'] else None,
                        'results': post_dict(live['poll_results']) if live['poll_results'] else None}
    return jsonify(d)


@app.route('/api/polls/<int:poll_id>', methods=['PUT'])
@require_auth
def update_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    data = request.json
    if 'title' in data:
        poll.title = data['title'].strip()
    if 'description' in data:
        poll.description = data['description']
    if 'poll_type' in data and data['poll_type'] in ('standard', 'prediction'):
        poll.poll_type = data['poll_type']
    if 'scoring_mode' in data and data['scoring_mode'] in ('none', 'single', 'ranked', 'confidence'):
        poll.scoring_mode = data['scoring_mode']
    if 'status' in data and data['status'] in ('open', 'closed'):
        poll.status = data['status']
        if data['status'] == 'closed':
            poll.closed_at = datetime.now(timezone.utc)
    poll_posts_changed(poll.id)
    db.session.commit()
    return jsonify(poll.to_dict())


@app.route('/api/polls/<int:poll_id>', methods=['DELETE'])
@require_auth
def delete_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    poll_posts_changed(poll.id)            # its Discord posts come down
    DiscordPost.query.filter(DiscordPost.kind.in_(('poll', 'poll_results')), DiscordPost.ref_id == poll.id,
                             DiscordPost.status == 'pending').update({'status': 'cancelled'}, synchronize_session=False)
    db.session.delete(poll)
    db.session.commit()
    return jsonify({'message': 'Poll deleted'})


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


def poll_ballot(user, poll):
    """Everything a Discord ballot shows, for one member: each category's
    nominees, their picks, the vote split (once they've picked, or voting has
    closed), and — once scored — the winners, their kernels and their place."""
    mine = {}
    for v in PollVote.query.join(PollCategory).filter(PollCategory.poll_id == poll.id,
                                                       PollVote.user_id == user.id):
        mine.setdefault(v.category_id, []).append(v)
    scored = poll.status == 'scored'
    cats = []
    for c in poll.categories:
        votes = sorted(mine.get(c.id, []), key=lambda v: v.rank or 0)
        d = {'id': c.id, 'title': c.title,
             'options': [{'id': o.id, 'text': o.text} for o in c.options],
             'picks': [{'option_id': v.option_id, 'confidence': v.confidence, 'rank': v.rank} for v in votes],
             'correct_option_id': c.correct_option_id if scored else None}
        if votes or poll.status != 'open':
            # Picks per nominee (ranked: any rank), out of the members who voted here.
            d['voters'] = len({v.user_id for v in c.votes})
            d['split'] = {}
            for v in c.votes:
                d['split'][str(v.option_id)] = d['split'].get(str(v.option_id), 0) + 1
        if scored and c.correct_option_id and votes:
            d['kernels'] = sum(vote_kernels(poll.scoring_mode, v, c.correct_option_id) for v in votes)
        cats.append(d)
    out = {'poll': {'id': poll.id, 'title': poll.title, 'status': poll.status,
                    'scoring_mode': poll.scoring_mode, 'poll_type': poll.poll_type,
                    'ranked_picks': RANKED_PICKS},
           'categories': cats, 'answered': sum(1 for c in cats if c['picks'])}
    if scored:
        board = poll_scores(poll)
        place = next((i for i, s in enumerate(board) if s['user'].id == user.id), None)
        out['score'] = ({'kernels': board[place]['kernels'], 'correct': board[place]['correct'],
                         'place': place + 1, 'of': len(board)} if place is not None else None)
    return out


@app.route('/api/polls/<int:poll_id>/vote', methods=['POST'])
@require_auth
def submit_votes(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    if poll.status != 'open':
        return jsonify({'error': 'Poll is not open for voting'}), 400
    user, membership = _require_group_member(poll.group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403
    _, err = require_role(user, poll.group_id, 'member')
    if err:
        return err

    # { votes: [{ category_id, option_id, confidence?, rank? }], clear: [category_id] }
    data = request.json or {}
    count = apply_votes(user, poll, data.get('votes'), data.get('clear'))
    return jsonify({'message': 'Votes submitted', 'count': count})


@app.route('/api/polls/<int:poll_id>/categories/<int:cat_id>/winner', methods=['PUT'])
@require_auth
def set_category_winner(poll_id, cat_id):
    """Set (or clear) the correct answer for a single category – used for live scoring."""
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    cat = db.session.get(PollCategory, cat_id)
    if not cat or cat.poll_id != poll.id:
        return jsonify({'error': 'Category not found'}), 404

    data = request.json  # { option_id: int | null }
    opt_id = data.get('option_id')
    if opt_id:
        opt = db.session.get(PollOption, opt_id)
        if not opt or opt.category_id != cat_id:
            return jsonify({'error': 'Invalid option'}), 400
        cat.correct_option_id = opt_id
    else:
        cat.correct_option_id = None

    poll_posts_changed(poll.id)            # posted results follow corrections
    db.session.commit()
    return jsonify({'category_id': cat_id, 'correct_option_id': cat.correct_option_id})


@app.route('/api/polls/<int:poll_id>/score', methods=['POST'])
@require_auth
def score_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    data = request.json  # { winners: { category_id: option_id } }
    winners = data.get('winners', {})

    for cat_id_str, opt_id in winners.items():
        cat_id = int(cat_id_str)
        cat = db.session.get(PollCategory, cat_id)
        if cat and cat.poll_id == poll.id:
            cat.correct_option_id = opt_id

    first_scoring = poll.status != 'scored'
    poll.status = 'scored'
    poll.closed_at = poll.closed_at or datetime.now(timezone.utc)
    poll.scored_at = datetime.now(timezone.utc)
    poll_posts_changed(poll.id)            # a correction updates results already posted
    db.session.commit()
    # Results go to Discord when asked for, or right away for "always" sharers.
    if can_share(user, poll.group_id) and (data.get('post_results') is True or (
            first_scoring and data.get('post_results') is None and share_prefs(user)['poll'] == 'always')):
        queue_poll_post(poll, user, 'poll_results', datetime.now())

    return jsonify(poll.to_dict(include_categories=True))


@app.route('/api/polls/<int:poll_id>/leaderboard', methods=['GET'])
@require_auth
def poll_leaderboard(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403

    return jsonify([{**s, 'user': s['user'].to_dict()} for s in poll_scores(poll)])


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


@app.route('/api/users/<int:user_id>/kernels', methods=['GET'])
@require_auth
def user_kernels(user_id):
    """Get total popcorn kernels earned across all scored polls."""
    total, _ = calc_user_kernels(user_id)
    return jsonify({'user_id': user_id, 'kernels': total})


def build_leaderboard(group):
    rows = []
    for m in group.memberships:
        if m.status != 'active' or not m.user:
            continue
        kernels, correct = calc_user_kernels(m.user_id, group_id=group.id)
        attendance = len(attended_showtime_ids(m.user_id, {group.id}))
        rows.append({
            'user': m.user.to_dict(),
            'kernels': kernels,
            'correct': correct,
            'attendance': attendance,
        })
    rows.sort(key=lambda r: (-r['kernels'], -r['correct'], -r['attendance']))
    return rows


@app.route('/api/groups/<int:group_id>/leaderboard')
@require_auth
def group_leaderboard(group_id):
    """Season-long standings: kernels across all scored polls + attendance."""
    group = db.session.get(Group, group_id)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    err = require_group_member(group_id)
    if err:
        return err
    return jsonify(build_leaderboard(group))


# ─── Routes: Watchlist ────────────────────────────────────────────────────────

@app.route('/api/watchlist', methods=['POST'])
@require_auth
def toggle_watchlist():
    user = current_user()
    movie_id = (request.json or {}).get('movie_id')
    movie = db.session.get(Movie, movie_id) if movie_id else None
    if not movie:
        return jsonify({'error': 'Movie not found'}), 404

    existing = Watchlist.query.filter_by(user_id=user.id, movie_id=movie.id).first()
    prompt = False
    if existing:
        db.session.delete(existing)
        watching = False
    else:
        # The digest may mention it in Discord only if you say so: "always" /
        # "never" decide now; "ask" asks (members in the club's server only).
        pref = share_prefs(user)['watchlist']
        db.session.add(Watchlist(user_id=user.id, movie_id=movie.id,
                                 share_discord={'always': True, 'never': False}.get(pref)))
        prompt = pref == 'ask' and can_share(user, DISCORD_GROUP_ID) \
            and _active_membership(user, DISCORD_GROUP_ID) is not None
        watching = True
    db.session.commit()
    return jsonify({'movie_id': movie.id, 'watching': watching, 'discord_prompt': prompt})


@app.route('/api/watchlist/<int:movie_id>/discord', methods=['PUT'])
@require_auth
def watchlist_discord(movie_id):
    """Answer "mention you in the Discord digest when it's playing?" for one
    film: {share: bool, remember: bool} (remember makes it your choice for all)."""
    user = current_user()
    w = Watchlist.query.filter_by(user_id=user.id, movie_id=movie_id).first()
    if not w:
        return jsonify({'error': 'Not on your watchlist'}), 404
    data = request.json or {}
    w.share_discord = bool(data.get('share'))
    if data.get('remember'):
        set_share_pref(user, 'watchlist', 'always' if w.share_discord else 'never')
    db.session.commit()
    return jsonify({'movie_id': movie_id, 'discord_share': watch_shared(w), 'prefs': share_prefs(user)})


@app.route('/api/watchlist')
@require_auth
def get_watchlist():
    user = current_user()
    now = datetime.now()
    items = []
    for w in Watchlist.query.filter_by(user_id=user.id).all():
        next_st = (Showtime.query
                   .filter(Showtime.movie_id == w.movie_id,
                           Showtime.start_time > now,
                           Showtime.is_cancelled.isnot(True))
                   .order_by(Showtime.start_time).first())
        items.append({
            'movie': w.movie.to_dict() if w.movie else None,
            'added_at': w.created_at.isoformat() if w.created_at else None,
            'discord_share': watch_shared(w),       # may the Discord digest mention you about it
            # Public serializer: the old one listed every club's attendees here.
            'next_showtime': public_showtimes([next_st], user)[0] if next_st else None,
        })
    items.sort(key=lambda i: i['next_showtime']['start_time'] if i['next_showtime'] else '9999')
    return jsonify(items)


# ─── Routes: Internal API (Discord bot) ───────────────────────────────────────
# Consumed by the bot container over the Docker network, authed by
# X-Internal-Token (see require_internal). No session/cookies involved.

def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


@app.route('/api/internal/showtimes')
@require_internal
def internal_showtimes():
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    q = _group_showtime_query(group)

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    search = (request.args.get('q') or '').strip()
    if start_str:
        q = q.filter(Showtime.start_time >= datetime.fromisoformat(start_str))
    if end_str:
        q = q.filter(Showtime.start_time <= datetime.fromisoformat(end_str))
    if search:
        q = q.filter(Movie.title.ilike(f'%{search}%'))
    movie_id = request.args.get('movie_id', type=int)
    if movie_id:
        q = q.filter(Showtime.movie_id == movie_id)

    limit = min(request.args.get('limit', 200, type=int), 500)
    showtimes = q.order_by(Showtime.start_time).limit(limit).all()
    return jsonify([for_discord(s.to_dict(group_id=group_id)) for s in showtimes])


def for_discord(d):
    """A showtime dict as the bot may show it: attendees / maybes name only
    members in the club's server (attendees_more / maybes_more count the rest),
    and reactions are counts only."""
    shown = present_user_ids()
    for key in ('attendees', 'maybes'):
        people = d.get(key) or []
        d[key] = [p for p in people if p['id'] in shown]
        d[f'{key}_more'] = len(people) - len(d[key])
    for r in (d.get('reactions') or {}).values():
        r['users'] = [u for u in r.get('users', []) if u['id'] in shown]
    return d


@app.route('/api/internal/chat-context')
@require_internal
def internal_chat_context():
    """Compact per-user + what's-playing bundle powering the bot's @-mention
    chatbot. Everything is bounded to keep the prompt small, and the bot is
    told to treat `upcoming` as the ONLY source of real screenings."""
    discord_id = str(request.args.get('discord_user_id') or '').strip()
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()

    user = User.query.filter_by(discord_user_id=discord_id).first() if discord_id else None
    out = {'user': {'linked': bool(user)}}

    if user:
        out['user'].update({
            'name': user.name,
            'favorite_genres': user.favorite_genres or '',
            'letterboxd_username': user.letterboxd_username or '',
            'bio': (user.bio or '')[:300],
        })

        kernels, correct = calc_user_kernels(user.id, group_id=group.id if group else None)
        standing = {'kernels': kernels, 'correct_picks': correct}
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

    return jsonify(out)


# ─── Discover in Discord (R3b) ───────────────────────────────────────────────
# /find and /surprise. Anyone can use them; an existing account (never created
# here) personalizes "For you", "Your list" and the you-are-going marks.

def _internal_discover_args():
    discord_id = str(request.args.get('discord_user_id') or '').strip()
    viewer = User.query.filter_by(discord_user_id=discord_id, is_active=True).first() if discord_id.isdigit() else None
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    return viewer, group


@app.route('/api/internal/discover/options')
@require_internal
def internal_discover_options():
    import discover
    _, group = _internal_discover_args()
    if not group:
        return jsonify({'error': 'group not found'}), 404
    return jsonify({'types': discover.find_types(group),
                    'regions': [{'value': f'region:{k}', 'label': v} for k, v in discover.REGION_KEYS.items()]})


@app.route('/api/internal/discover/find')
@require_internal
def internal_discover_find():
    import discover
    viewer, group = _internal_discover_args()
    if not group:
        return jsonify({'error': 'group not found'}), 404
    a = request.args
    params = discover.find_params(a.get('type'), a.get('where'), a.get('when'), a.get('q'))
    limit = max(1, min(a.get('limit', 8, type=int), 25))
    result = discover.browse(group, viewer, params, limit=limit)
    names = {t.slug: t.short_name or t.name for t in Theatre.query.filter(
        Theatre.slug.in_([x for x in params.get('theatres', '').split(',') if x]))}
    if params.get('theatres'):
        params['_theatre_label'] = ', '.join(names.get(x, x) for x in params['theatres'].split(','))
    result.pop('facets', None)
    result.pop('regions', None)
    return jsonify({**result, 'params': {k: v for k, v in params.items() if not k.startswith('_')},
                    'label': discover.describe(params, result.get('title')),
                    'browse_path': discover.browse_path(params)})


@app.route('/api/internal/discover/surprise')
@require_internal
def internal_discover_surprise():
    import discover
    viewer, group = _internal_discover_args()
    if not group:
        return jsonify({'error': 'group not found'}), 404
    a = request.args
    params = discover.find_params(where=a.get('where'))
    theatres = {x for x in params.get('theatres', '').split(',') if x} | \
        {s for s, r in discover.REGIONS.items() if r.lower() in params.get('regions', '').split(',')}
    exclude = [_as_int(x) for x in (a.get('exclude') or '').split(',') if _as_int(x)]
    when = a.get('when') if a.get('when') in discover.WHEN else 'tonight'
    pick = discover.surprise(group, viewer, when, exclude, theatres=theatres or None)
    return jsonify(pick or {'error': 'nothing_playing'}), (200 if pick else 404)


@app.route('/api/internal/theatres')
@require_internal
def internal_theatres():
    """Active theatres for the bot's theatre autocomplete. Scoped to a group's
    theatre list when a group_id is given (all active theatres otherwise)."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    theatres = Theatre.query.filter(Theatre.is_active.isnot(False)).order_by(Theatre.name).all()
    if group:
        slugs = [t.strip() for t in (group.theatres or '').split(',') if t.strip()]
        if slugs:
            theatres = [t for t in theatres if t.slug in slugs]
    return jsonify([t.to_dict() for t in theatres])


@app.route('/api/internal/showtime-facets')
@require_internal
def internal_showtime_facets():
    """Distinct dates + theatres available for the current filter selection,
    powering dependent autocompletes (pick a movie -> only its dates/theatres).
    Computed with DISTINCT so it's complete and cheap regardless of volume.
    Optional filters: q (movie title), theatre (slug), start/end (ISO)."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()
    q = _group_showtime_query(group)

    start = request.args.get('start')
    end = request.args.get('end')
    q = q.filter(Showtime.start_time >= (datetime.fromisoformat(start) if start else now))
    q = q.filter(Showtime.start_time <= (datetime.fromisoformat(end) if end
                                         else now + timedelta(days=60)))
    title = (request.args.get('q') or '').strip()
    if title:
        q = q.filter(Movie.title.ilike(f'%{title}%'))
    theatre = (request.args.get('theatre') or '').strip()
    if theatre:
        q = q.filter(Theatre.slug == theatre)

    date_rows = q.with_entities(db.func.date(Showtime.start_time)).distinct().all()
    dates = sorted({r[0] for r in date_rows if r[0]})

    th_rows = q.with_entities(Theatre.slug, Theatre.short_name, Theatre.name).distinct().all()
    theatres, seen = [], set()
    for slug, short, name in th_rows:
        if slug in seen:
            continue
        seen.add(slug)
        theatres.append({'slug': slug, 'name': name, 'short_name': short or name})
    theatres.sort(key=lambda t: (t['name'] or '').lower())

    return jsonify({'dates': dates, 'theatres': theatres})


DIGEST_RETAG_AFTER = timedelta(days=14)  # tag someone about a watchlisted film at most fortnightly
RARE_MIN_SCORE = 4                       # a screening needs this rarity score to be called rare
PLAN_MIN_WATCHERS = 2                    # "make plans": members wanting a film nobody's going to yet
LAST_CHANCE_MARGIN = timedelta(days=3)   # the theatre's schedule must run this far past the last showing
DIGEST_CAPS = {'plans': 2, 'rare': 5, 'last_chance': 3, 'opening': 4}   # keep it short enough to read
EVENT_WORDS = [                          # special-event billing -> (pattern, how the digest says it)
    (r'q\s*&\s*a', 'Q&A'), (r'in[- ]person', 'in person'), (r'\bintro', 'intro'), (r'premiere', 'premiere'),
    (r'anniversary', 'anniversary'), (r'double[- ]feature', 'double feature'), (r'marathon', 'marathon'),
    (r'\bguest', 'guest'), (r'conversation with', 'conversation'),
]


def _showtime_brief(s):
    return {'showtime_id': s.id, 'title': s.movie.title, 'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label}


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
    run continues. Instead: the last day that still has at least half the
    theatre's typical daily showtimes (median of the coming week)."""
    rows = (_group_showtime_query(group)
            .with_entities(Showtime.theatre_id, db.func.date(Showtime.start_time), db.func.count(Showtime.id))
            .filter(Showtime.start_time >= now, Showtime.start_time < now + timedelta(days=90))
            .group_by(Showtime.theatre_id, db.func.date(Showtime.start_time)).all())
    per_day = {}
    for tid, day, n in rows:
        per_day.setdefault(tid, {})[(datetime.fromisoformat(str(day)).date() - now.date()).days] = n
    horizons = {}
    for tid, days in per_day.items():
        week = sorted(days.get(d, 0) for d in range(7))
        threshold = max(1, week[3] / 2)
        full = [d for d, n in days.items() if n >= threshold]
        horizons[tid] = datetime.combine(now.date() + timedelta(days=max(full) if full else 0), datetime.max.time())
    return horizons


def digest_recap(group, members, now):
    """Last week in a line or two: check-ins, the most-discussed screening,
    and any poll that was scored."""
    week_ago = now - timedelta(days=7)
    recent = {s.id: s for s in _group_showtime_query(group)
              .filter(Showtime.start_time >= week_ago, Showtime.start_time < now)}
    per_film, checkins = {}, 0
    for uid in members or []:
        for sid in attended_showtime_ids(uid, {group.id}) & recent.keys():
            checkins += 1
            title = recent[sid].movie.title
            per_film[title] = per_film.get(title, 0) + 1
    top = max(per_film.items(), key=lambda kv: kv[1]) if per_film else None
    talk = (db.session.query(Message.showtime_id, db.func.count(Message.id))
            .filter(Message.group_id == group.id, Message.created_at >= _utcnow_naive() - timedelta(days=7))
            .group_by(Message.showtime_id).order_by(db.func.count(Message.id).desc()).first())
    discussed = None
    if talk and talk[1] >= 3:
        st = db.session.get(Showtime, talk[0])
        thread = ShowtimeThread.query.filter_by(showtime_id=talk[0], group_id=group.id).first()
        discussed = {'title': st.movie.title, 'comments': talk[1], 'url': thread.url if thread else None}
    poll = (Poll.query.filter(Poll.group_id == group.id, Poll.status == 'scored',
                              Poll.scored_at >= _utcnow_naive() - timedelta(days=7))
            .order_by(Poll.scored_at.desc()).first())
    board = poll_scores(poll) if poll else []
    return {'checkins': checkins, 'films': len(per_film),
            'top_film': {'title': top[0], 'count': top[1]} if top and top[1] > 1 else None,
            'discussed': discussed,
            'poll': {'title': poll.title, 'kernels': board[0]['kernels'],
                     'winner': board[0]['user'].name if on_discord(board[0]['user']) else None}
            if board else None}


@app.route('/api/internal/digest')
@require_internal
def internal_digest():
    """The weekly digest's sections, computed here so the bot gets a small,
    already-trimmed payload. Each film appears in at most one of plans / rare /
    last_chance / opening (in that priority):
      whos_going      — screenings in the window with group RSVPs
      plans           — films PLAN_MIN_WATCHERS+ members want, nobody's going to yet
      rare            — top screenings by rarity() score (>= RARE_MIN_SCORE), with reasons
      last_chance     — a film's final showing, when its theatre's schedule clearly runs on
      opening         — recent releases appearing on the club's theatres for the first time
      watchlist       — watchlisted films playing, with their watchers (`fresh`: taggable)
      open_polls, recap (last week), new_on_calendar (schedule-drop counts per theatre)."""
    import json as _json
    group_id = request.args.get('group_id', type=int)
    days = request.args.get('days', 7, type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()
    window_end = now + timedelta(days=days)

    showtimes = (_group_showtime_query(group)
                 .filter(Showtime.start_time >= now, Showtime.start_time <= window_end)
                 .order_by(Showtime.start_time).all())
    by_movie = {}
    for s in showtimes:
        by_movie.setdefault(s.movie_id, []).append(s)
    members = ({m.user_id for m in group.memberships if m.status == 'active'} if group else None)

    # Names are only members in the club's server (and, for watchlists, only
    # if they let the digest mention them); everyone else is a *_more count.
    whos_going, going_movies = [], set()
    for s in showtimes:
        going = [r.user for r in s.rsvps
                 if r.status == 'going' and r.user and (not group or r.group_id == group.id)]
        if going:
            # Members who never share their RSVPs are counted, not named.
            shown, more = split_present(going)
            quiet = [u for u in shown if share_prefs(u)['rsvp'] == 'never']
            shown, more = [u for u in shown if u not in quiet], more + len(quiet)
            whos_going.append({**_showtime_brief(s), 'going': [u.name for u in shown], 'going_more': more})
            going_movies.add(s.movie_id)

    retag_before = _utcnow_naive() - DIGEST_RETAG_AFTER
    watchers_by_movie = {}
    for w in (Watchlist.query.filter(Watchlist.movie_id.in_(by_movie)).all() if by_movie else []):
        if w.user and w.user.is_active and (members is None or w.user_id in members):
            watchers_by_movie.setdefault(w.movie_id, []).append({
                'watchlist_id': w.id, 'name': w.user.name,
                'discord_user_id': w.user.discord_user_id,
                'fresh': not w.last_notified_at or w.last_notified_at < retag_before,
                'shown': watch_shared(w),
            })

    def watchers_out(ws):
        """Watchers the digest may name; the rest are counted, and fresh ones
        are still marked (and emailed) when the digest goes out."""
        shown = [{k: w[k] for k in ('watchlist_id', 'name', 'discord_user_id', 'fresh')} for w in ws if w['shown']]
        return shown, len(ws) - len(shown), [w['watchlist_id'] for w in ws if not w['shown'] and w['fresh']]

    used = set()
    plans = []
    for mid, ws in sorted(watchers_by_movie.items(), key=lambda kv: (-len(kv[1]), by_movie[kv[0]][0].start_time)):
        if len(ws) >= PLAN_MIN_WATCHERS and mid not in going_movies and len(plans) < DIGEST_CAPS['plans']:
            shown, more, _ = watchers_out(ws)
            plans.append({**_showtime_brief(by_movie[mid][0]), 'wanters': [w['name'] for w in shown],
                          'wanters_more': more})
            used.add(mid)

    candidates = []
    for mid, shows in by_movie.items():
        if mid in used:
            continue
        venues = len({s.theatre_id for s in shows})
        best = max(((rarity(s, len(shows), venues, now.year), s) for s in shows),
                   key=lambda x: (x[0][0], -x[1].start_time.timestamp()))
        (score, why), s = best
        if score >= RARE_MIN_SCORE:
            candidates.append((mid, {**_showtime_brief(s), 'score': score, 'reasons': why}))
    candidates.sort(key=lambda c: (-c[1]['score'], c[1]['start_time']))
    rare = [entry for _, entry in candidates[:DIGEST_CAPS['rare']]]
    used.update(mid for mid, _ in candidates[:DIGEST_CAPS['rare']])

    base = _group_showtime_query(group)
    horizon = schedule_horizons(group, now)
    span = {mid: (first, last, n) for mid, first, last, n in base.with_entities(
        Showtime.movie_id, db.func.min(Showtime.start_time), db.func.max(Showtime.start_time),
        db.func.count(Showtime.id)).filter(Showtime.movie_id.in_(by_movie)).group_by(Showtime.movie_id)} \
        if by_movie else {}

    last_chance = []
    for mid, shows in sorted(by_movie.items(), key=lambda kv: kv[1][-1].start_time):
        first, last, total = span.get(mid, (None, None, 0))
        final = shows[-1]
        if mid in used or total < 3 or last != final.start_time or len(last_chance) >= DIGEST_CAPS['last_chance']:
            continue
        if is_last_chance(final.start_time, {x.theatre_id for x in shows}, horizon):
            last_chance.append(_showtime_brief(final))
            used.add(mid)

    opening = []
    for mid, shows in by_movie.items():
        first, last, total = span.get(mid, (None, None, 0))
        year = _as_int((shows[0].movie.release_year or '')[:4])
        if mid in used or not year or year < now.year - 1 or not first or first < now - timedelta(hours=12):
            continue
        opening.append({**_showtime_brief(shows[0]), 'theatres': len({s.theatre_id for s in shows})})
    # Widest openings first: a film opening at five theatres beats a one-off.
    opening = sorted(opening, key=lambda x: (-x['theatres'], x['start_time']))[:DIGEST_CAPS['opening']]

    planned = {p['showtime_id'] for p in plans}
    watchlist = []
    for mid, ws in watchers_by_movie.items():
        shown, more, quiet = watchers_out(ws)
        watchlist.append({**_showtime_brief(by_movie[mid][0]), 'watchers': shown, 'more': more,
                          'quiet_ids': quiet, 'planned': by_movie[mid][0].id in planned})
    watchlist.sort(key=lambda item: item['start_time'])

    new_on_calendar = {}
    for e in (ScrapeEvent.query
              .filter(ScrapeEvent.event_type.in_(('new_drop', 'new_showtimes')),
                      ScrapeEvent.created_at > _utcnow_naive() - timedelta(days=days))):
        p = _json.loads(e.payload_json or '{}')
        name = (e.theatre.short_name or e.theatre.name) if e.theatre else p.get('theatre_name', '')
        new_on_calendar[name] = new_on_calendar.get(name, 0) + (p.get('new_showtime_count') or 0)

    open_polls = ([p.to_dict() for p in Poll.query.filter_by(group_id=group.id, status='open')]
                  if group else [])

    return jsonify({
        'group_name': group.name if group else None,
        'days': days,
        'whos_going': whos_going,
        'plans': plans,
        'rare': rare,
        'last_chance': last_chance,
        'opening': opening,
        'watchlist': watchlist,
        'open_polls': open_polls,
        'recap': digest_recap(group, members, now) if group else None,
        'new_on_calendar': [{'theatre': t, 'showtimes': n}
                            for t, n in sorted(new_on_calendar.items(), key=lambda kv: -kv[1]) if n],
    })


@app.route('/api/internal/digest/delivered', methods=['POST'])
@require_internal
def internal_digest_delivered():
    """Called once the weekly digest has been posted with these watchlist
    entries tagged: marks them notified (no re-tag for two weeks) and emails
    watchers the digest didn't name (not on Discord, or not shared) the same news."""
    ids = [i for i in (request.json or {}).get('watchlist_ids') or [] if isinstance(i, int)]
    now = _utcnow_naive()
    by_user = {}
    for w in (Watchlist.query.filter(Watchlist.id.in_(ids)).all() if ids else []):
        w.last_notified_at = now
        if w.user and w.user.email and not watch_shared(w) and w.movie:
            by_user.setdefault(w.user.id, (w.user, []))[1].append(w.movie)
    db.session.commit()

    for user, movies in by_user.values():
        items = ''.join(f'<li><strong>{m.title}</strong></li>' for m in movies)
        send_email(user.email, 'Your watchlist is playing this week',
            f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
            <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
            <p>Films on your watchlist are showing this week:</p><ul>{items}</ul>
            <p><a href="{FRONTEND_URL}" style="display:inline-block;padding:12px 24px;background:#e8a838;
            color:#0d0c09;text-decoration:none;border-radius:6px;font-weight:bold;">See showtimes</a></p>
            </div>""")
    return jsonify({'marked': len(ids), 'emailed': len(by_user)})


@app.route('/api/internal/link/verify', methods=['POST'])
@require_internal
def internal_link_verify():
    data = request.json or {}
    code = (data.get('code') or '').strip().upper()
    discord_user_id = str(data.get('discord_user_id') or '').strip()
    if not code or not discord_user_id:
        return jsonify({'error': 'code and discord_user_id required'}), 400

    user = User.query.filter_by(discord_link_code=code).first()
    if not user:
        return jsonify({'error': 'Invalid code'}), 404
    if not user.discord_link_code_expires or user.discord_link_code_expires < _utcnow_naive():
        return jsonify({'error': 'Code expired — generate a new one on the site'}), 410

    # One site account per Discord account. A Discord-only account (made by
    # using the bot first) merges into this one; another site account just
    # loses the link.
    other = User.query.filter_by(discord_user_id=discord_user_id).first()
    if other and other.id != user.id:
        if other.email is None:
            merge_users(user, other)
        else:
            other.discord_user_id = None
            db.session.flush()

    user.discord_user_id = discord_user_id
    user.discord_username = (data.get('discord_username') or user.discord_username or '')[:40] or None
    user.discord_link_code = None
    user.discord_link_code_expires = None
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route('/api/internal/rsvp', methods=['POST'])
@require_internal
def internal_rsvp():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err

    group_id = _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'member')
    if err:
        return err
    showtime, err = apply_rsvp(user, data.get('showtime_id'), data.get('status'), group_id)
    if err:
        return err
    result = for_discord(showtime.to_dict(user_id=user.id, group_id=group_id))
    result['user'] = user.to_dict()
    return jsonify(result)


@app.route('/api/internal/polls')
@require_internal
def internal_polls():
    group_id = request.args.get('group_id', type=int)
    if not group_id:
        return jsonify({'error': 'group_id required'}), 400
    q = Poll.query.filter_by(group_id=group_id)
    if request.args.get('include_closed'):
        # /vote's picker: open polls, then ones that closed in the last 60 days
        # (to check your picks and results).
        recent = _utcnow_naive() - timedelta(days=60)
        ended = db.func.coalesce(Poll.scored_at, Poll.closed_at, Poll.created_at)
        polls = q.filter(db.or_(Poll.status == 'open', ended >= recent)).all()
        polls.sort(key=lambda p: (p.status != 'open', -(p.scored_at or p.closed_at or p.created_at).timestamp()))
    else:
        polls = q.filter_by(status='open').all()
    return jsonify([p.to_dict() for p in polls])


def _internal_poll_voter(poll_id, data):
    """(user, poll, error) for a Discord member acting on a poll of a group
    they belong to."""
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return None, None, (jsonify({'error': 'poll_not_found'}), 404)
    user, err = resolve_discord_user(data)
    if err:
        return None, None, err
    if not _active_membership(user, poll.group_id):
        return None, None, (jsonify({'error': 'not_member'}), 403)
    return user, poll, None


@app.route('/api/internal/polls/<int:poll_id>/ballot')
@require_internal
def internal_poll_ballot(poll_id):
    user, poll, err = _internal_poll_voter(poll_id, request.args)
    if err:
        return err
    return jsonify(poll_ballot(user, poll))


@app.route('/api/internal/polls/<int:poll_id>/vote', methods=['POST'])
@require_internal
def internal_poll_vote(poll_id):
    """Save picks from a Discord ballot; returns the refreshed ballot."""
    data = request.json or {}
    user, poll, err = _internal_poll_voter(poll_id, data)
    if err:
        return err
    _, err = require_role(user, poll.group_id, 'member')
    if err:
        return err
    if poll.status != 'open':
        return jsonify({'error': 'poll_closed', **poll_ballot(user, poll)}), 409
    apply_votes(user, poll, data.get('votes'), data.get('clear'))
    return jsonify(poll_ballot(user, poll))


# ─── Discussion threads (mirrored with Discord) ───────────────────────────────
# Each screening's discussion can have a thread in #movies. The bot owns all
# Discord calls; the backend keeps the mapping and an outbox: site comments not
# yet copied to Discord, site deletions to carry out, and starter cards whose
# RSVP list changed. Thread messages come back in as comments.

DISCUSSION_BACKFILL = 10                      # earlier comments copied into a new thread
OUTBOX_WINDOW = timedelta(hours=24)           # older unsent comments are backfilled instead
CARD_REFRESH_EVERY = timedelta(minutes=3)


def _in_server():
    """Site user ids of members in the club's Discord server (a subquery)."""
    return (db.session.query(User.id)
            .join(DiscordServerMember, DiscordServerMember.discord_user_id == User.discord_user_id))


def _pending_post(q):
    """Site comments the bot still has to copy into Discord (never ones their
    writer kept off Discord, or by anyone not in the club's server)."""
    return q.filter(Message.source == 'site', Message.discord_message_id.is_(None),
                    Message.to_discord.isnot(False), Message.user_id.in_(_in_server()),
                    Message.created_at >= _utcnow_naive() - OUTBOX_WINDOW)


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
        pending = {m.id for m in _pending_post(q)}
        earlier = [m for m in q.order_by(Message.created_at.desc(), Message.id.desc())
                   if m.id not in pending and m.to_discord is not False and m.user_id in present_user_ids()]
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
    posts = _pending_post(Message.query.filter(Message.group_id == group_id, Message.showtime_id.in_(threaded))) \
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


@app.route('/api/internal/leaderboard')
@require_internal
def internal_leaderboard():
    """/leaderboard: members in the club's server, with their real place;
    `hidden` counts the members on the site."""
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    shown_ids = present_user_ids()
    board = build_leaderboard(group)
    rows = [{'place': i + 1, 'user': {'name': r['user']['name']},
             **{k: r[k] for k in ('kernels', 'correct', 'attendance')}}
            for i, r in enumerate(board) if r['user']['id'] in shown_ids]
    return jsonify({'rows': rows, 'hidden': len(board) - len(rows)})


@app.route('/api/internal/watch', methods=['POST'])
@require_internal
def internal_watch():
    """Watchlist a movie from Discord's /watch command. `action` is
    'add' | 'remove' | 'toggle' (default toggle, for backwards compatibility)."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    title = (data.get('title') or '').strip()
    action = (data.get('action') or 'toggle').lower()
    movie = Movie.query.filter(Movie.title.ilike(title)).first() \
        or Movie.query.filter(Movie.title.ilike(f'%{title}%')).first()
    if not movie:
        return jsonify({'error': 'Movie not found'}), 404

    # Added in the server itself (and announced there): the digest may mention it.
    existing = Watchlist.query.filter_by(user_id=user.id, movie_id=movie.id).first()
    if action == 'add':
        if not existing:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id, share_discord=True))
        watching = True
    elif action == 'remove':
        if existing:
            db.session.delete(existing)
        watching = False
    else:  # toggle
        if existing:
            db.session.delete(existing)
            watching = False
        else:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id, share_discord=True))
            watching = True
    db.session.commit()
    return jsonify({'movie_title': movie.title, 'watching': watching, 'user_name': user.name})


@app.route('/api/internal/members')
@require_internal
def internal_members():
    """Active members of a group who are in the club's server, for the /watch
    member picker."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    if not group:
        return jsonify([])
    members = [m.user for m in group.memberships
               if m.status == 'active' and m.user and m.user.is_active and on_discord(m.user)]
    members.sort(key=lambda u: (u.name or '').lower())
    return jsonify([{'id': u.id, 'name': u.name} for u in members])


@app.route('/api/internal/watchlist')
@require_internal
def internal_watchlist():
    """A member's watchlist (+ each movie's next upcoming showtime), for
    /watch show. Defaults to the caller; any active member is viewable.
    Optional start/end (ISO) keep only movies with a showtime in that window."""
    member_id = request.args.get('member_id', type=int)
    if member_id:
        target = db.session.get(User, member_id)
        if not on_discord(target):            # someone else's: only members in the server
            target = None
    else:
        target, err = resolve_discord_user(request.args)
        if err:
            return err
    if not target or not target.is_active:
        return jsonify({'error': 'Member not found'}), 404

    start = request.args.get('start')
    end = request.args.get('end')
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    now = datetime.now()

    items = []
    for w in Watchlist.query.filter_by(user_id=target.id).all():
        if not w.movie:
            continue
        q = (Showtime.query
             .filter(Showtime.movie_id == w.movie_id,
                     Showtime.is_cancelled.isnot(True))
             .filter(Showtime.start_time > (start_dt or now)))
        if end_dt:
            q = q.filter(Showtime.start_time <= end_dt)
        next_st = q.order_by(Showtime.start_time).first()
        if (start_dt or end_dt) and not next_st:
            continue  # a window was requested and this movie has nothing in it
        items.append({
            'title': w.movie.title,
            'year': w.movie.release_year,
            'next_showtime': public_showtimes([next_st])[0] if next_st else None,   # no names needed
        })
    items.sort(key=lambda i: i['next_showtime']['start_time'] if i['next_showtime'] else '9999')
    return jsonify({'owner': target.name, 'items': items})


def _profile_payload(user):
    now = datetime.now()
    upcoming = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
                .filter(RSVP.user_id == user.id, RSVP.status == 'going', Showtime.start_time > now)
                .count())
    return {
        'user': user.to_dict(),
        'genres': [g for g in (user.favorite_genres or '').split(',') if g],
        'genre_options': GENRE_LIST,
        'watchlist_count': Watchlist.query.filter_by(user_id=user.id).count(),
        'upcoming_rsvps': upcoming,
        'site_account': user.email is not None,
    }


@app.route('/api/internal/profile')
@require_internal
def internal_profile():
    """A profile for Discord's /profile: someone else's (member_discord_id), or
    the caller's own — created on first use in the club's server."""
    other = request.args.get('member_discord_id')
    if other:
        user = User.query.filter_by(discord_user_id=str(other)).first()
        if not user or not user.is_active or not on_discord(user):
            return jsonify({'error': 'no_account'}), 404
    else:
        user, err = resolve_discord_user(request.args)
        if err:
            return err
    return jsonify(_profile_payload(user))


@app.route('/api/internal/profile', methods=['POST'])
@require_internal
def internal_profile_update():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    _update_profile_fields(user, data)
    db.session.commit()
    return jsonify(_profile_payload(user))


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


ATTENDANCE_DM_GAP = timedelta(hours=20)   # at most one "did you go?" DM per person per day


@app.route('/api/internal/attendance/prompts')
@require_internal
def internal_attendance_prompts():
    """Who the bot should DM "did you go?" now: members on Discord with
    screenings nobody has asked them about, skipping anyone DMed in the last 20
    hours (so it's at most a daily nudge). Up to 5 screenings each — one DM's
    worth of buttons. Quiet hours are the bot's call."""
    now = datetime.now()
    candidates = {r.user_id for r in RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id).filter(
        RSVP.status == 'going', Showtime.start_time >= now - ATTENDANCE_LOOKBACK, Showtime.start_time <= now)}
    recently_asked = {a.user_id for a in Attendance.query.filter(
        Attendance.prompted_at > _utcnow_naive() - ATTENDANCE_DM_GAP)}
    out = []
    users = (User.query.filter(User.id.in_(candidates - recently_asked), User.discord_user_id.isnot(None),
                               User.is_active.is_(True)).all() if candidates - recently_asked else [])
    for user in users:
        pending = pending_attendance(user, include_prompted=False)[:5]
        if pending:
            out.append({'discord_user_id': user.discord_user_id, 'name': user.name,
                        'screenings': [_screening_item(s) for s in pending]})
    return jsonify(out)


@app.route('/api/internal/attendance/prompted', methods=['POST'])
@require_internal
def internal_attendance_prompted():
    """The bot asked about these (DM sent, or DMs were closed): never re-ask."""
    data = request.json or {}
    user = User.query.filter_by(discord_user_id=str(data.get('discord_user_id') or '')).first()
    if not user:
        return jsonify({'error': 'no_account'}), 404
    now = _utcnow_naive()
    for sid in {i for i in data.get('showtime_ids') or [] if isinstance(i, int)}:
        row = Attendance.query.filter_by(user_id=user.id, showtime_id=sid).first() \
            or Attendance(user_id=user.id, showtime_id=sid)
        row.prompted_at = now
        db.session.add(row)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/attendance', methods=['POST'])
@require_internal
def internal_attendance_set():
    """A Went / Didn't-go button press from Discord."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    showtime, err = set_attendance(user, data.get('showtime_id'), data.get('status'), 'discord')
    if err:
        return err
    return jsonify(_screening_item(showtime, data.get('status')))


@app.route('/api/internal/history')
@require_internal
def internal_history():
    """Watch history for /history: someone else's (member_discord_id) or the
    caller's own. Only what they saw — RSVPs count from this group."""
    group_id = request.args.get('group_id', type=int)
    other = request.args.get('member_discord_id')
    if other:
        user = User.query.filter_by(discord_user_id=str(other)).first()
        if not user or not user.is_active or not on_discord(user):
            return jsonify({'error': 'no_account'}), 404
    else:
        user, err = resolve_discord_user(request.args)
        if err:
            return err
    items = history_items(user, False, {group_id} if group_id else None)
    return jsonify({'name': user.name, 'items': items})


@app.route('/api/internal/compare')
@require_internal
def internal_compare():
    """/compare @member: where the caller and a member line up (this group's RSVPs)."""
    me, err = resolve_discord_user(request.args)
    if err:
        return err
    other = User.query.filter_by(discord_user_id=str(request.args.get('member_discord_id') or '')).first()
    if not other or not other.is_active or not on_discord(other):
        return jsonify({'error': 'unknown_member'}), 404
    if other.id == me.id:
        return jsonify({'error': 'same_person'}), 400
    group_id = request.args.get('group_id', type=int)
    return jsonify(compare_members(me, other, {group_id} if group_id else set()))


# ─── Quotes (/quote, /wisdom) ─────────────────────────────────────────────────

def _quote_fields(data):
    """Validated text/movie/character from a request. Returns (fields, error)."""
    text = (data.get('text') or '').strip()
    if not text:
        return None, (jsonify({'error': 'The quote is empty'}), 400)
    if len(text) > 2000:   # Discord's message limit — the bot posts the line as-is
        return None, (jsonify({'error': "Quotes can't be longer than a Discord message (2,000 characters)"}), 400)
    return {'text': text,
            'movie': (data.get('movie') or '').strip()[:200] or None,
            'character': (data.get('character') or '').strip()[:200] or None}, None


def _duplicate_quote(text, exclude_id=None):
    q = Quote.query.filter(Quote.deleted_at.is_(None), db.func.lower(Quote.text) == text.lower())
    if exclude_id:
        q = q.filter(Quote.id != exclude_id)
    return q.first()


@app.route('/api/internal/quotes')
@require_internal
def internal_quotes():
    """Active quotes. With `q`: a search over text, movie and character (for
    /quote find and autocomplete). Without: the whole list, which the bot caches.
    `newest=1` puts recent additions first."""
    q = (request.args.get('q') or '').strip()
    limit = min(request.args.get('limit', 5000, type=int), 5000)
    query = Quote.query.filter(Quote.deleted_at.is_(None))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Quote.text.ilike(like), Quote.movie.ilike(like),
                                    Quote.character.ilike(like)))
    order = Quote.id.desc() if request.args.get('newest') else Quote.id
    return jsonify([row.to_dict() for row in query.order_by(order).limit(limit)])


@app.route('/api/internal/quotes/<int:quote_id>')
@require_internal
def internal_quote(quote_id):
    quote = db.session.get(Quote, quote_id)
    if not quote or quote.deleted_at:
        return jsonify({'error': 'Quote not found'}), 404
    return jsonify(quote.to_dict())


@app.route('/api/internal/quotes', methods=['POST'])
@require_internal
def internal_quote_add():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    fields, err = _quote_fields(data)
    if err:
        return err
    dupe = _duplicate_quote(fields['text'])
    if dupe:
        return jsonify({'error': 'duplicate', 'id': dupe.id}), 409
    quote = Quote(**fields, added_by=user.id)
    db.session.add(quote)
    db.session.commit()
    return jsonify(quote.to_dict()), 201


@app.route('/api/internal/quotes/<int:quote_id>', methods=['PUT'])
@require_internal
def internal_quote_edit(quote_id):
    """Any member can correct a quote or its source; the last editor is kept."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    quote = db.session.get(Quote, quote_id)
    if not quote or quote.deleted_at:
        return jsonify({'error': 'Quote not found'}), 404
    fields, err = _quote_fields(data)
    if err:
        return err
    dupe = _duplicate_quote(fields['text'], exclude_id=quote.id)
    if dupe:
        return jsonify({'error': 'duplicate', 'id': dupe.id}), 409
    for key, value in fields.items():
        setattr(quote, key, value)
    quote.updated_by, quote.updated_at = user.id, _utcnow_naive()
    db.session.commit()
    return jsonify(quote.to_dict())


@app.route('/api/internal/quotes/<int:quote_id>', methods=['DELETE'])
@require_internal
def internal_quote_remove(quote_id):
    """Removable by whoever added it, or a server admin (the bot sends is_admin
    for members with Manage Server) — so nobody can wipe the list on a whim.
    Soft delete: the row stays, recoverable."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    quote = db.session.get(Quote, quote_id)
    if not quote or quote.deleted_at:
        return jsonify({'error': 'Quote not found'}), 404
    if quote.added_by != user.id and not data.get('is_admin'):
        owner = quote.author.name if quote.author else 'the original list'
        return jsonify({'error': 'not_yours', 'added_by': owner}), 403
    quote.deleted_at, quote.deleted_by = _utcnow_naive(), user.id
    db.session.commit()
    return jsonify({'removed': quote.id})


@app.route('/api/internal/quotes/seed', methods=['POST'])
@require_internal
def internal_quotes_seed():
    """One-time import of the bot's built-in list (bot/quotes.py), sent by the
    bot at startup. It only runs while the table is completely empty, so it can
    never resurrect removed quotes or duplicate edited ones."""
    if Quote.query.first():
        return jsonify({'seeded': 0, 'skipped': []})
    seen, skipped = set(), []
    for item in (request.json or {}).get('quotes') or []:
        fields, err = _quote_fields(item)
        if not fields or fields['text'].lower() in seen:
            skipped.append((item.get('text') or '')[:60])
            continue
        seen.add(fields['text'].lower())
        db.session.add(Quote(**fields))
    db.session.commit()
    return jsonify({'seeded': len(seen), 'skipped': skipped})


# Keys the bot may store; anything else is rejected.
BOT_SETTING_KEYS = {'llm_primary', 'llm_fallback'}


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


@app.route('/api/internal/ai/chat', methods=['POST'])
@require_internal
def internal_ai_chat():
    """The bot's chatbot: {messages, max_tokens} → {text}; 429 with retry_after
    when the daily token cap is spent; 503 when no model can answer."""
    ai = _ai()
    data = request.json or {}
    try:
        text = ai.chat(data.get('messages') or [], max_tokens=min(int(data.get('max_tokens') or 300), 2000))
    except ai.RateLimited as e:
        return jsonify({'error': 'rate_limited', 'retry_after': e.retry_after_sec}), 429
    except ai.Unavailable as e:
        return jsonify({'error': 'unavailable', 'detail': str(e)}), 503
    except Exception as e:
        print(f'ai chat failed: {e}')
        return jsonify({'error': 'failed', 'detail': str(e)[:200]}), 502
    return jsonify({'text': text})


@app.route('/api/internal/ai/status')
@require_internal
def internal_ai_status():
    ai = _ai()
    s = ai.status()
    if not s['primary']:
        s = ai.refresh('first use')
    return jsonify(s)


@app.route('/api/internal/ai/refresh', methods=['POST'])
@require_internal
def internal_ai_refresh():
    """Re-pick models now (e.g. after /llm changes an override)."""
    return jsonify(_ai().refresh((request.json or {}).get('reason') or 'requested'))


@app.route('/api/internal/settings')
@require_internal
def internal_settings():
    keys = [k for k in (request.args.get('keys') or '').split(',') if k in BOT_SETTING_KEYS]
    rows = {r.key: r.value for r in BotSetting.query.filter(BotSetting.key.in_(keys)).all()} if keys else {}
    return jsonify({k: rows.get(k, '') for k in keys})


@app.route('/api/internal/settings', methods=['POST'])
@require_internal
def internal_settings_update():
    data = request.json or {}
    key, value = data.get('key'), (data.get('value') or '').strip()[:200]
    if key not in BOT_SETTING_KEYS:
        return jsonify({'error': 'Unknown setting'}), 400
    row = db.session.get(BotSetting, key) or BotSetting(key=key)
    row.value = value
    db.session.add(row)
    db.session.commit()
    return jsonify({key: value})


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
    db.session.execute(db.text("UPDATE rsvp SET updated_at = created_at WHERE updated_at IS NULL"))
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

    for theatre in Theatre.query.all():
        if theatre.slug not in registry_slugs:
            theatre.is_active = False

    db.session.commit()


def seed_admin():
    email = 'sunscinemafanclub@gmail.com'
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            name='Julian',
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


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        migrate()
        seed_theatres()
        seed_admin()
    app.run(debug=True, port=5001)
