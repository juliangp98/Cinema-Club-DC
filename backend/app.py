from flask import Flask, jsonify, request, session, make_response, redirect
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
import re
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from dotenv import load_dotenv

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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
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
            'discord_username': self.discord_username or '',
            'discord_only': self.email is None,
            'letterboxd_username': self.letterboxd_username or '',
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
        }
        if include_members:
            d['members'] = [m.to_dict() for m in self.memberships if m.status == 'active']
            d['pending'] = [m.to_dict() for m in self.memberships if m.status == 'pending']
        return d


class GroupMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # 'admin', 'member'
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


class Watchlist(db.Model):
    """'I want to see this' — drives Discord pings when new showtimes appear."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_notified_at = db.Column(db.DateTime)
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
    __table_args__ = (db.UniqueConstraint('user_id', 'showtime_id', 'group_id'),)


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
    user = db.relationship('User', lazy=True)


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
        if user_id:
            user_votes = [v for v in self.votes if v.user_id == user_id]
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
        # Vote distribution (visible after user has voted or poll closed)
        if user_id or show_winner:
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
    """Sign `user` in for PERMANENT_SESSION_LIFETIME. Clears any previous
    session first so a pre-existing cookie can't carry over."""
    session.clear()
    session.permanent = True
    session['user_id'] = user.id


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
    db.session.add(LoginToken(token_hash=_hash_token(token), email=email, purpose=purpose,
                              name=name, request_ip=ip, expires_at=now + SIGNIN_LINK_TTL))
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

    user = User.query.filter_by(email=rec.email).first()
    if rec.purpose == 'signup':
        if not user:
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
    mode = 'connect' if request.args.get('mode') == 'connect' and current_user() else 'login'
    state = secrets.token_urlsafe(24)
    session['discord_oauth'] = {'state': state, 'mode': mode}
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
        return redirect(f"{FRONTEND_URL}/?{urlencode(params)}")

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

    user = existing
    if user and not user.is_active:
        return back(discord_error='inactive')
    if not user:
        user = User(discord_user_id=discord_id, name=name, avatar_color=random.choice(AVATAR_COLORS),
                    is_active=True)
        db.session.add(user)
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

    db.session.delete(target)
    db.session.commit()
    return jsonify({'message': 'Member removed'})


# ─── Routes: Theatres ─────────────────────────────────────────────────────────

@app.route('/api/theatres')
@require_auth
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
    return jsonify([
        s.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)
        for s in showtimes
    ])


@app.route('/api/showtimes/<int:showtime_id>')
@require_auth
def get_showtime(showtime_id):
    """Single showtime — used by ?showtime= deep links from Discord embeds."""
    user = current_user()
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    showtime = db.session.get(Showtime, showtime_id)
    if not showtime:
        return jsonify({'error': 'Showtime not found'}), 404
    return jsonify(showtime.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres))


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
            existing.status = status
        else:
            new_rsvp = RSVP(user_id=user.id, showtime_id=showtime_id, group_id=group_id, status=status)
            db.session.add(new_rsvp)
        db.session.commit()
    else:
        return None, (jsonify({'error': 'Invalid status'}), 400)

    return db.session.get(Showtime, showtime_id), None


def emit_rsvp_activity(user, showtime, status):
    """Queue a Discord announcement for a site RSVP (bot polls activity-events)."""
    import json as _json
    payload = {
        'user_name': user.name,
        'discord_user_id': user.discord_user_id,
        'status': status,
        'movie_title': showtime.movie.title if showtime.movie else '',
        'theatre_name': showtime.theatre.name if showtime.theatre else '',
        'start_time': showtime.start_time.isoformat() if showtime.start_time else None,
        'showtime_id': showtime.id,
    }
    db.session.add(ActivityEvent(kind='rsvp', payload_json=_json.dumps(payload)))
    db.session.commit()


@app.route('/api/rsvp', methods=['POST'])
@require_auth
def rsvp():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    status = data.get('status')
    group_id = _as_int(data.get('group_id'))
    err = require_group_member(group_id)
    if err:
        return err

    prev = RSVP.query.filter_by(user_id=user.id, showtime_id=showtime_id, group_id=group_id).first()
    prev_status = prev.status if prev else None

    showtime, err = apply_rsvp(user, showtime_id, status, group_id)
    if err:
        return err

    # Announce positive RSVPs from the site, but only on an actual change so
    # re-submitting the same status doesn't repost. (RSVPs made via the Discord
    # /rsvp command are announced by the command itself, not here.)
    if status in ('going', 'maybe') and status != prev_status and showtime:
        emit_rsvp_activity(user, showtime, status)

    return jsonify(showtime.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres))


# ─── Routes: Reactions ────────────────────────────────────────────────────────

@app.route('/api/reactions', methods=['POST'])
@require_auth
def toggle_reaction():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    group_id = _as_int(data.get('group_id'))
    emoji = data.get('emoji')
    err = require_group_member(group_id)
    if err:
        return err

    if not showtime_id or not emoji:
        return jsonify({'error': 'showtime_id and emoji required'}), 400

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
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.filter(Message.created_at > since_dt)
        except ValueError:
            pass

    messages = query.order_by(Message.created_at.asc()).limit(100).all()
    return jsonify([{
        'id': m.id,
        'user': {'id': m.user.id, 'name': m.user.name, 'avatar_color': m.user.avatar_color},
        'body': m.body,
        'created_at': m.created_at.isoformat(),
    } for m in messages])


@app.route('/api/messages', methods=['POST'])
@require_auth
def post_message():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    group_id = _as_int(data.get('group_id'))
    body = (data.get('body') or '').strip()
    err = require_group_member(group_id)
    if err:
        return err

    if not showtime_id or not body:
        return jsonify({'error': 'showtime_id and body required'}), 400

    if len(body) > 2000:
        return jsonify({'error': 'Message too long'}), 400

    msg = Message(user_id=user.id, showtime_id=showtime_id, group_id=group_id, body=body)
    db.session.add(msg)
    db.session.commit()

    return jsonify({
        'id': msg.id,
        'user': {'id': user.id, 'name': user.name, 'avatar_color': user.avatar_color},
        'body': msg.body,
        'created_at': msg.created_at.isoformat(),
    }), 201


# ─── Routes: Calendar Export ──────────────────────────────────────────────────

@app.route('/api/showtimes/<int:sid>/ical')
@require_auth
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
@require_auth
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
    return jsonify([p.to_dict() for p in polls])


@app.route('/api/groups/<int:group_id>/polls', methods=['POST'])
@require_auth
def create_poll(group_id):
    user, membership = _require_group_member(group_id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json
    poll = Poll(
        group_id=group_id,
        created_by=user.id,
        title=data.get('title', '').strip(),
        description=data.get('description', ''),
        poll_type=data.get('poll_type', 'standard'),
        scoring_mode=data.get('scoring_mode', 'none'),
    )
    if not poll.title:
        return jsonify({'error': 'Title required'}), 400
    db.session.add(poll)
    db.session.flush()  # get poll.id

    for i, cat_data in enumerate(data.get('categories', [])):
        cat = PollCategory(
            poll_id=poll.id,
            title=cat_data.get('title', '').strip(),
            sort_order=i,
        )
        db.session.add(cat)
        db.session.flush()
        for j, opt_data in enumerate(cat_data.get('options', [])):
            extra = opt_data.get('extra')
            opt = PollOption(
                category_id=cat.id,
                text=opt_data.get('text', '').strip(),
                sort_order=j,
                extra_data=_json.dumps(extra) if extra else None,
            )
            db.session.add(opt)

    db.session.commit()
    return jsonify(poll.to_dict(include_categories=True)), 201


@app.route('/api/groups/<int:group_id>/polls/oscars', methods=['POST'])
@require_auth
def create_oscars_poll(group_id):
    user, membership = _require_group_member(group_id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

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
    return jsonify(poll.to_dict(include_categories=True, user_id=user.id))


@app.route('/api/polls/<int:poll_id>', methods=['PUT'])
@require_auth
def update_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

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
    db.session.commit()
    return jsonify(poll.to_dict())


@app.route('/api/polls/<int:poll_id>', methods=['DELETE'])
@require_auth
def delete_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    db.session.delete(poll)
    db.session.commit()
    return jsonify({'message': 'Poll deleted'})


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

    data = request.json  # { votes: [{ category_id, option_id, confidence?, rank? }] }
    votes_data = data.get('votes', [])

    # Validate all votes first, then delete-and-insert per category
    valid_votes = []
    seen_cats = set()
    for v in votes_data:
        cat_id = v.get('category_id')
        opt_id = v.get('option_id')
        confidence = max(1, min(10, int(v.get('confidence', 1))))
        rank = v.get('rank')

        cat = db.session.get(PollCategory, cat_id)
        if not cat or cat.poll_id != poll.id:
            continue
        opt = db.session.get(PollOption, opt_id)
        if not opt or opt.category_id != cat_id:
            continue

        valid_votes.append((cat_id, opt_id, confidence, rank))
        seen_cats.add(cat_id)

    # Delete existing votes for each mentioned category (handles ranked re-submissions cleanly)
    for cat_id in seen_cats:
        PollVote.query.filter_by(category_id=cat_id, user_id=user.id).delete()

    for cat_id, opt_id, confidence, rank in valid_votes:
        db.session.add(PollVote(
            category_id=cat_id,
            user_id=user.id,
            option_id=opt_id,
            confidence=confidence,
            rank=rank,
        ))

    db.session.commit()
    return jsonify({'message': 'Votes submitted', 'count': len(valid_votes)})


@app.route('/api/polls/<int:poll_id>/categories/<int:cat_id>/winner', methods=['PUT'])
@require_auth
def set_category_winner(poll_id, cat_id):
    """Set (or clear) the correct answer for a single category – used for live scoring."""
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

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

    db.session.commit()
    return jsonify({'category_id': cat_id, 'correct_option_id': cat.correct_option_id})


@app.route('/api/polls/<int:poll_id>/score', methods=['POST'])
@require_auth
def score_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership or membership.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json  # { winners: { category_id: option_id } }
    winners = data.get('winners', {})

    for cat_id_str, opt_id in winners.items():
        cat_id = int(cat_id_str)
        cat = db.session.get(PollCategory, cat_id)
        if cat and cat.poll_id == poll.id:
            cat.correct_option_id = opt_id

    poll.status = 'scored'
    poll.closed_at = poll.closed_at or datetime.now(timezone.utc)
    db.session.commit()

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

    # Calculate scores per user
    scores = {}
    for cat in poll.categories:
        correct_id = cat.correct_option_id
        for vote in cat.votes:
            uid = vote.user_id
            if uid not in scores:
                scores[uid] = {'correct': 0, 'kernels': 0, 'total': 0}
            scores[uid]['total'] += 1
            if correct_id and vote.option_id == correct_id:
                scores[uid]['correct'] += 1
                if poll.scoring_mode == 'confidence':
                    scores[uid]['kernels'] += vote.confidence
                elif poll.scoring_mode == 'single':
                    scores[uid]['kernels'] += 1
                elif poll.scoring_mode == 'ranked':
                    # For ranked: award points based on rank (lower rank = more points)
                    scores[uid]['kernels'] += max(1, 4 - (vote.rank or 1))
            elif correct_id and poll.scoring_mode == 'confidence':
                # Wrong answer with confidence scoring: deduct the confidence value
                scores[uid]['kernels'] -= vote.confidence

    # Build leaderboard
    leaderboard = []
    for uid, s in scores.items():
        u = db.session.get(User, uid)
        if u:
            leaderboard.append({
                'user': u.to_dict(),
                'correct': s['correct'],
                'kernels': s['kernels'],
                'total': s['total'],
            })

    leaderboard.sort(key=lambda x: (-x['kernels'], -x['correct']))
    return jsonify(leaderboard)


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
        if vote.option_id == cat.correct_option_id:
            correct += 1
            if poll.scoring_mode == 'confidence':
                total += vote.confidence
            elif poll.scoring_mode == 'single':
                total += 1
            elif poll.scoring_mode == 'ranked':
                total += max(1, 4 - (vote.rank or 1))
        elif poll.scoring_mode == 'confidence':
            # Wrong answer with confidence scoring: deduct the confidence value
            total -= vote.confidence
    return total, correct


@app.route('/api/users/<int:user_id>/kernels', methods=['GET'])
@require_auth
def user_kernels(user_id):
    """Get total popcorn kernels earned across all scored polls."""
    total, _ = calc_user_kernels(user_id)
    return jsonify({'user_id': user_id, 'kernels': total})


def build_leaderboard(group):
    now = datetime.now()
    rows = []
    for m in group.memberships:
        if m.status != 'active' or not m.user:
            continue
        kernels, correct = calc_user_kernels(m.user_id, group_id=group.id)
        attendance = (RSVP.query.join(Showtime)
                      .filter(RSVP.user_id == m.user_id,
                              RSVP.group_id == group.id,
                              RSVP.status == 'going',
                              Showtime.start_time < now)
                      .count())
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
    if existing:
        db.session.delete(existing)
        watching = False
    else:
        db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
        watching = True
    db.session.commit()
    return jsonify({'movie_id': movie.id, 'watching': watching})


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
            'next_showtime': next_st.to_dict() if next_st else None,
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

    limit = min(request.args.get('limit', 200, type=int), 500)
    showtimes = q.order_by(Showtime.start_time).limit(limit).all()
    return jsonify([s.to_dict(group_id=group_id) for s in showtimes])


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

        attended_q = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
                      .filter(RSVP.user_id == user.id, RSVP.status == 'going',
                              Showtime.start_time < now))
        if group:
            attended_q = attended_q.filter(RSVP.group_id == group.id)
        seen, attended = set(), []
        for r in attended_q.order_by(Showtime.start_time.desc()).limit(60).all():
            m = r.showtime.movie
            if not m or m.title in seen:
                continue
            seen.add(m.title)
            attended.append({
                'title': m.title,
                'year': m.release_year,
                'theatre': r.showtime.theatre.short_name or r.showtime.theatre.name,
                'date': r.showtime.start_time.strftime('%Y-%m-%d'),
            })
            if len(attended) >= 20:
                break
        out['attended'] = attended

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
REPERTORY_AGE_YEARS = 5                  # "rare screening" = a film at least this old...
FILM_FORMATS = ('70mm', '35mm', '16mm')  # ...or projected on film


def _showtime_brief(s):
    return {'showtime_id': s.id, 'title': s.movie.title, 'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label}


@app.route('/api/internal/digest')
@require_internal
def internal_digest():
    """The weekly digest's sections, computed here so the bot gets a small payload:
      whos_going — screenings in the window with group RSVPs,
      rare       — repertory (older) films and screenings on film, one per film,
      new_titles — films added by each theatre's schedule drops this past week,
      watchlist  — watchlisted films playing in the window with their watchers
                   (`fresh`: not tagged about that film in the last two weeks),
      open_polls."""
    import json as _json
    group_id = request.args.get('group_id', type=int)
    days = request.args.get('days', 7, type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()

    showtimes = (_group_showtime_query(group)
                 .filter(Showtime.start_time >= now,
                         Showtime.start_time <= now + timedelta(days=days))
                 .order_by(Showtime.start_time).all())

    whos_going = []
    for s in showtimes:
        going = [r.user.name for r in s.rsvps
                 if r.status == 'going' and r.user and (not group or r.group_id == group.id)]
        if going:
            whos_going.append({**_showtime_brief(s), 'going': going})

    showings = {}
    for s in showtimes:
        showings[s.movie_id] = showings.get(s.movie_id, 0) + 1
    rare, listed = [], set()
    for s in showtimes:
        year = _as_int((s.movie.release_year or '')[:4])
        repertory = year is not None and year <= now.year - REPERTORY_AGE_YEARS
        on_film = any(f in (s.format_label or '') for f in FILM_FORMATS)
        if (repertory or on_film) and s.movie_id not in listed:
            listed.add(s.movie_id)
            rare.append({**_showtime_brief(s), 'year': s.movie.release_year,
                         'showings': showings[s.movie_id]})

    new_titles = {}
    for e in (ScrapeEvent.query
              .filter(ScrapeEvent.event_type.in_(('new_drop', 'new_showtimes')),
                      ScrapeEvent.created_at > _utcnow_naive() - timedelta(days=days))
              .order_by(ScrapeEvent.created_at)):
        p = _json.loads(e.payload_json or '{}')
        theatre = p.get('theatre_name') or (e.theatre.name if e.theatre else '')
        entry = new_titles.setdefault(theatre, {'theatre': theatre, 'showtimes': 0, 'titles': []})
        entry['showtimes'] += p.get('new_showtime_count') or 0
        for movie in Movie.query.filter(Movie.id.in_(p.get('movie_ids') or [])):
            if movie.title not in entry['titles']:
                entry['titles'].append(movie.title)

    first_showing = {}
    for s in showtimes:
        first_showing.setdefault(s.movie_id, s)
    members = ({m.user_id for m in group.memberships if m.status == 'active'} if group else None)
    retag_before = _utcnow_naive() - DIGEST_RETAG_AFTER
    watchers_by_movie = {}
    for w in (Watchlist.query.filter(Watchlist.movie_id.in_(first_showing)).all()
              if first_showing else []):
        if w.user and w.user.is_active and (members is None or w.user_id in members):
            watchers_by_movie.setdefault(w.movie_id, []).append({
                'watchlist_id': w.id, 'name': w.user.name,
                'discord_user_id': w.user.discord_user_id,
                'fresh': not w.last_notified_at or w.last_notified_at < retag_before,
            })
    watchlist = sorted(({**_showtime_brief(first_showing[mid]), 'watchers': ws}
                        for mid, ws in watchers_by_movie.items()),
                       key=lambda item: item['start_time'])

    open_polls = ([p.to_dict() for p in Poll.query.filter_by(group_id=group.id, status='open')]
                  if group else [])

    return jsonify({
        'group_name': group.name if group else None,
        'days': days,
        'whos_going': whos_going,
        'rare': rare,
        'new_titles': sorted(new_titles.values(), key=lambda t: -t['showtimes']),
        'watchlist': watchlist,
        'open_polls': open_polls,
    })


@app.route('/api/internal/digest/delivered', methods=['POST'])
@require_internal
def internal_digest_delivered():
    """Called once the weekly digest has been posted with these watchlist
    entries tagged: marks them notified (no re-tag for two weeks) and emails
    watchers who aren't on Discord the same news."""
    ids = [i for i in (request.json or {}).get('watchlist_ids') or [] if isinstance(i, int)]
    now = _utcnow_naive()
    by_user = {}
    for w in (Watchlist.query.filter(Watchlist.id.in_(ids)).all() if ids else []):
        w.last_notified_at = now
        if w.user and w.user.email and not w.user.discord_user_id and w.movie:
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

    group_id = data.get('group_id')
    showtime, err = apply_rsvp(user, data.get('showtime_id'), data.get('status'), group_id)
    if err:
        return err
    result = showtime.to_dict(user_id=user.id, group_id=group_id)
    result['user'] = user.to_dict()
    return jsonify(result)


@app.route('/api/internal/polls')
@require_internal
def internal_polls():
    group_id = request.args.get('group_id', type=int)
    if not group_id:
        return jsonify({'error': 'group_id required'}), 400
    polls = Poll.query.filter_by(group_id=group_id, status='open').all()
    return jsonify([p.to_dict() for p in polls])


@app.route('/api/internal/leaderboard')
@require_internal
def internal_leaderboard():
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    return jsonify(build_leaderboard(group))


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

    existing = Watchlist.query.filter_by(user_id=user.id, movie_id=movie.id).first()
    if action == 'add':
        if not existing:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
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
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
            watching = True
    db.session.commit()
    return jsonify({'movie_title': movie.title, 'watching': watching, 'user_name': user.name})


@app.route('/api/internal/members')
@require_internal
def internal_members():
    """Active members of a group, for the /watch member picker."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    if not group:
        return jsonify([])
    members = [m.user for m in group.memberships
               if m.status == 'active' and m.user and m.user.is_active]
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
            'next_showtime': next_st.to_dict() if next_st else None,
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
        if not user or not user.is_active:
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
    ]
    for sql in stmts:
        try:
            db.session.execute(db.text(sql))
        except Exception:
            pass  # column already exists
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

    # Backfill any existing RSVPs without a group_id
    if group:
        RSVP.query.filter_by(group_id=None).update({'group_id': group.id})
        db.session.commit()


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
