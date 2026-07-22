from flask import Flask, jsonify, request, session, make_response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
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
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///cinemaclub.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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


# ─── Email Helper ─────────────────────────────────────────────────────────────

def send_email(to, subject, html_body):
    """Send an email via Gmail SMTP. Falls back to console if SMTP not configured."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"\n📧 EMAIL (console fallback — set SMTP_EMAIL & SMTP_PASSWORD to send for real)")
        print(f"   To: {to}")
        print(f"   Subject: {subject}")
        print(f"   Body: {html_body[:200]}...")
        print()
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
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    avatar_color = db.Column(db.String(20), default='#e8a838')
    avatar_url = db.Column(db.Text)
    bio = db.Column(db.Text, default='')
    favorite_genres = db.Column(db.Text, default='')
    invite_token = db.Column(db.String(64), unique=True)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    discord_user_id = db.Column(db.String(30), unique=True)
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
            'letterboxd_username': self.letterboxd_username or '',
        }


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_public = db.Column(db.Boolean, default=True)
    theatres = db.Column(db.String(200), default='')  # comma-separated theatre slugs
    # Theatres whose automated "new showtimes" Discord alerts are silenced.
    # Distinct from `theatres` — a muted theatre still shows in the calendar/
    # commands; only the noisy channel drop announcement is suppressed.
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


class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    purchase_link = db.Column(db.String(500))
    is_sold_out = db.Column(db.Boolean, default=False)
    is_cancelled = db.Column(db.Boolean, default=False)
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

    session['user_id'] = user.id

    # Auto-add to groups if invited with a group association
    # Check if there's a pending membership waiting
    pending = GroupMembership.query.filter_by(user_id=user.id, status='pending').all()
    for m in pending:
        m.status = 'active'
    db.session.commit()

    return jsonify({'user': user.to_dict()})


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').strip().lower()
    user = User.query.filter_by(email=email, is_active=True).first()
    if not user:
        return jsonify({'error': 'No active account for this email. Sign up or ask for an invite!'}), 403
    session['user_id'] = user.id
    return jsonify({'user': user.to_dict()})


@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email', '').strip().lower()
    name = data.get('name', '').strip()

    if not email or not name:
        return jsonify({'error': 'Email and name are required'}), 400

    existing = User.query.filter_by(email=email).first()

    if existing and existing.is_active:
        return jsonify({'error': 'Account already exists. Try logging in!'}), 409

    if existing and not existing.is_active:
        # Orphaned invite — activate the account
        existing.name = name
        existing.is_active = True
        existing.invite_token = None
        db.session.commit()
        session['user_id'] = existing.id
        # Auto-activate any pending memberships from invites
        pending = GroupMembership.query.filter_by(user_id=existing.id, status='pending').all()
        for m in pending:
            m.status = 'active'
        db.session.commit()
        return jsonify({'user': existing.to_dict()})

    # Brand new user
    user = User(
        email=email,
        name=name,
        avatar_color=random.choice(AVATAR_COLORS),
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
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
    if 'bio' in data:
        user.bio = (data['bio'] or '')[:500]
    if 'avatar_color' in data and data['avatar_color'] in AVATAR_COLORS:
        user.avatar_color = data['avatar_color']
    if 'favorite_genres' in data:
        # Validate genres
        genres = [g.strip().lower() for g in data['favorite_genres'].split(',') if g.strip().lower() in GENRE_LIST]
        user.favorite_genres = ','.join(genres)
    if 'letterboxd_username' in data:
        handle = re.sub(r'[^A-Za-z0-9_]', '', (data['letterboxd_username'] or ''))[:60]
        user.letterboxd_username = handle or None

    db.session.commit()
    return jsonify({'user': user.to_dict()})


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
    data = request.json
    email = data.get('email', '').strip().lower()
    group_id = data.get('group_id')

    if not email:
        return jsonify({'error': 'Email required'}), 400

    group = db.session.get(Group, group_id) if group_id else None
    group_name = group.name if group else 'Cinema Club DC'
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
    d = group.to_dict(include_members=bool(membership))
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
    data = request.json
    showtime_id = data.get('showtime_id')
    status = data.get('status')
    group_id = data.get('group_id')

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
    data = request.json
    showtime_id = data.get('showtime_id')
    group_id = data.get('group_id')
    emoji = data.get('emoji')

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
    data = request.json
    showtime_id = data.get('showtime_id')
    group_id = data.get('group_id')
    body = (data.get('body') or '').strip()

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


@app.route('/api/internal/digest')
@require_internal
def internal_digest():
    group_id = request.args.get('group_id', type=int)
    days = request.args.get('days', 7, type=int)
    group = db.session.get(Group, group_id) if group_id else None

    now = datetime.now()
    showtimes = (_group_showtime_query(group)
                 .filter(Showtime.start_time >= now,
                         Showtime.start_time <= now + timedelta(days=days))
                 .order_by(Showtime.start_time).limit(500).all())

    open_polls = []
    if group:
        open_polls = [p.to_dict() for p in
                      Poll.query.filter_by(group_id=group.id, status='open').all()]

    recent_drops = [e.to_dict() for e in ScrapeEvent.query.filter(
        ScrapeEvent.event_type == 'new_drop',
        ScrapeEvent.created_at > _utcnow_naive() - timedelta(days=days),
    ).order_by(ScrapeEvent.created_at.desc()).limit(10).all()]

    return jsonify({
        'group': group.to_dict() if group else None,
        'showtimes': [s.to_dict(group_id=group_id) for s in showtimes],
        'open_polls': open_polls,
        'recent_drops': recent_drops,
    })


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

    # One site account per Discord account
    for other in User.query.filter_by(discord_user_id=discord_user_id).all():
        if other.id != user.id:
            other.discord_user_id = None

    user.discord_user_id = discord_user_id
    user.discord_link_code = None
    user.discord_link_code_expires = None
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route('/api/internal/users/by-discord/<discord_id>')
@require_internal
def internal_user_by_discord(discord_id):
    user = User.query.filter_by(discord_user_id=str(discord_id)).first()
    if not user or not user.is_active:
        return jsonify({'error': 'Not linked'}), 404
    return jsonify(user.to_dict())


@app.route('/api/internal/rsvp', methods=['POST'])
@require_internal
def internal_rsvp():
    data = request.json or {}
    user = User.query.filter_by(discord_user_id=str(data.get('discord_user_id') or '')).first()
    if not user or not user.is_active:
        return jsonify({'error': 'Not linked'}), 404

    group_id = data.get('group_id')
    showtime, err = apply_rsvp(user, data.get('showtime_id'), data.get('status'), group_id)
    if err:
        return err
    result = showtime.to_dict(user_id=user.id, group_id=group_id)
    result['user'] = user.to_dict()
    return jsonify(result)


@app.route('/api/internal/watch-matches')
@require_internal
def internal_watch_matches():
    """Watchlist hits for a scrape event's new showtimes. Discord-linked
    watchers are returned for the bot to @-mention; unlinked watchers get an
    email right here. 7-day per-(user,movie) re-notify suppression."""
    event = db.session.get(ScrapeEvent, request.args.get('event_id', type=int))
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    import json as _json
    payload = _json.loads(event.payload_json or '{}')
    movie_ids = payload.get('movie_ids') or []
    if not movie_ids:
        return jsonify([])

    cutoff = _utcnow_naive() - timedelta(days=7)
    now = datetime.now()
    matches = []
    for w in Watchlist.query.filter(Watchlist.movie_id.in_(movie_ids)).all():
        if w.last_notified_at and w.last_notified_at > cutoff:
            continue
        if not w.user or not w.user.is_active or not w.movie:
            continue
        first_st = (Showtime.query
                    .filter(Showtime.movie_id == w.movie_id,
                            Showtime.theatre_id == event.theatre_id,
                            Showtime.start_time > now,
                            Showtime.is_cancelled.isnot(True))
                    .order_by(Showtime.start_time).first())
        if not first_st:
            continue
        w.last_notified_at = _utcnow_naive()

        if w.user.discord_user_id:
            matches.append({
                'discord_user_id': w.user.discord_user_id,
                'user_name': w.user.name,
                'movie_title': w.movie.title,
                'theatre_name': payload.get('theatre_name', ''),
                'first_showtime': first_st.start_time.isoformat(),
                'showtime_id': first_st.id,
            })
        else:
            when = first_st.start_time.strftime('%A %b %-d at %-I:%M %p')
            send_email(w.user.email,
                       f"{w.movie.title} just got showtimes",
                       f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
                       <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
                       <p><strong>{w.movie.title}</strong> — a movie on your watchlist — just got showtimes
                       at <strong>{payload.get('theatre_name', 'a theatre')}</strong>, starting {when}.</p>
                       <p><a href="{FRONTEND_URL}/?showtime={first_st.id}" style="display:inline-block;padding:12px 24px;
                       background:#e8a838;color:#0d0c09;text-decoration:none;border-radius:6px;font-weight:bold;">
                       See showtimes</a></p></div>""")

    db.session.commit()
    return jsonify(matches)


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
    user = User.query.filter_by(discord_user_id=str(data.get('discord_user_id') or '')).first()
    if not user or not user.is_active:
        return jsonify({'error': 'Not linked'}), 404
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
    caller = User.query.filter_by(discord_user_id=str(request.args.get('discord_user_id') or '')).first()
    if not caller or not caller.is_active:
        return jsonify({'error': 'Not linked'}), 404

    member_id = request.args.get('member_id', type=int)
    target = db.session.get(User, member_id) if member_id else caller
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


@app.route('/api/internal/alert-mutes')
@require_internal
def internal_alert_mutes():
    """Theatres whose automated new-showtime announcements are silenced for a
    group. The bot's announce loop skips drop embeds for these slugs."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    slugs = [s.strip() for s in ((group.announce_muted_theatres if group else '') or '').split(',') if s.strip()]
    names = {}
    if slugs:
        names = {t.slug: (t.short_name or t.name)
                 for t in Theatre.query.filter(Theatre.slug.in_(slugs)).all()}
    return jsonify({
        'slugs': slugs,
        'muted': [{'slug': s, 'name': names.get(s, s)} for s in slugs],
    })


@app.route('/api/internal/alert-mutes', methods=['POST'])
@require_internal
def internal_alert_mutes_update():
    data = request.json or {}
    group = db.session.get(Group, data.get('group_id')) if data.get('group_id') else None
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    slug = (data.get('theatre_slug') or '').strip()
    action = (data.get('action') or '').lower()
    theatre = Theatre.query.filter_by(slug=slug).first()
    if not theatre:
        return jsonify({'error': 'Theatre not found'}), 404

    current = [s.strip() for s in (group.announce_muted_theatres or '').split(',') if s.strip()]
    if action == 'mute':
        if slug not in current:
            current.append(slug)
        muted = True
    elif action == 'unmute':
        current = [s for s in current if s != slug]
        muted = False
    else:
        return jsonify({'error': 'action must be mute or unmute'}), 400
    group.announce_muted_theatres = ','.join(current)
    db.session.commit()
    return jsonify({'theatre_slug': slug, 'theatre_name': theatre.short_name or theatre.name,
                    'muted': muted, 'slugs': current})


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
    ]
    for sql in stmts:
        try:
            db.session.execute(db.text(sql))
        except Exception:
            pass  # column already exists
    db.session.commit()
    _migrate_poll_vote_ranked_constraint()
    _backfill_title_normalized()


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
