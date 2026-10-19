"""The database: every table, as a SQLAlchemy model (R9b: split out of
app.py, which re-exports them, so `from app import User` still works)."""
import json

import app as core
from app import (datetime, db, timezone)


# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # None for Discord-only accounts: created automatically the first time a
    # server member uses a personal bot command, or by "Sign in with Discord".
    email = db.Column(db.String(120), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    avatar_color = db.Column(db.String(20), default='#e8a838')
    # The picture shown for you (R6b): avatar_kind is your choice — 'photo'
    # (an upload: avatar_url), 'emoji', 'initials' or 'discord'; None means you
    # haven't chosen, so your Discord picture shows if you have one.
    avatar_url = db.Column(db.Text)
    avatar_emoji = db.Column(db.String(16))
    avatar_kind = db.Column(db.String(10))
    discord_avatar_url = db.Column(db.Text)        # your Discord picture, for "use my Discord picture"
    bio = db.Column(db.Text, default='')
    favorite_genres = db.Column(db.Text, default='')   # before R13; moved to TasteItem (taste.py), unused
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
    calendar_token = db.Column(db.String(64), unique=True)   # R7a: your calendar subscription link
    discord_link_code = db.Column(db.String(12))
    discord_link_code_expires = db.Column(db.DateTime)
    letterboxd_username = db.Column(db.String(60))
    # Letterboxd diary sync (R10f), off until you connect it: what a diary
    # entry matching a screening you were going to does ('ask' | 'always' |
    # 'never'), and whether your ratings show with your check-ins.
    letterboxd_sync = db.Column(db.Boolean, default=False)
    letterboxd_checkin = db.Column(db.String(10), default='ask')
    letterboxd_ratings = db.Column(db.Boolean, default=False)
    letterboxd_clues = db.Column(db.Boolean, default=True)    # R15: diary reviews may be quiz clues (unnamed)
    letterboxd_synced_at = db.Column(db.DateTime)
    # Your Letterboxd watchlist, brought in from Letterboxd's export (an upload,
    # not a sync): on?, whether its films alert you like your site watchlist
    # (None = not asked yet), and when it was last imported.
    letterboxd_watch_on = db.Column(db.Boolean, default=False)
    letterboxd_watch_alerts = db.Column(db.Boolean)
    letterboxd_watch_imported_at = db.Column(db.DateTime)
    tour_seen_at = db.Column(db.DateTime)    # R11: the welcome tour, shown once (replay any time)
    tours_json = db.Column(db.Text)          # 7f: the page tours offered and done/declined (a JSON list of pages)
    # R13: show your taste (favorite genres, films, people…) on your profile to
    # people in your clubs. Off by default; recommendations use it either way.
    taste_public = db.Column(db.Boolean, default=False)
    # R8: where your alerts reach you and which ones you get (see notify.py);
    # JSON of only what you changed — the rest follows your account's defaults.
    notify_prefs = db.Column(db.Text)
    rsvps = db.relationship('RSVP', backref='user', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'avatar_color': self.avatar_color,
            'avatar_url': self.avatar_url,
            'avatar_emoji': self.avatar_emoji,
            'avatar_kind': self.avatar_kind or ('discord' if self.avatar_url else 'initials'),
            'discord_avatar_url': self.discord_avatar_url,
            'bio': self.bio or '',
            'discord_linked': bool(self.discord_user_id),
            'discord_clubs': core.discord_clubs(self),     # the clubs whose Discord server you're in
            'discord_username': self.discord_username or '',
            'discord_only': self.email is None,
            'letterboxd_username': self.letterboxd_username or '',
            'letterboxd_connected': bool(self.letterboxd_sync),      # diary sync on (R10f)
            'share_prefs': core.share_prefs(self),
            'is_guest': bool(self.is_guest),
            'tour_seen': self.tour_seen_at is not None,
            'tours_seen': self.tours_seen(),
            'taste_public': bool(self.taste_public),
        }

    # What other members see: no email (unless they're an admin of a club you
    # share), and none of your private settings.
    PRIVATE = ('email', 'share_prefs', 'discord_avatar_url', 'avatar_kind', 'tour_seen', 'tours_seen', 'taste_public')

    def tours_seen(self):
        try:
            return [p for p in json.loads(self.tours_json or '[]') if isinstance(p, str)]
        except ValueError:
            return []

    def public_dict(self, with_email=False):
        d = {k: v for k, v in self.to_dict().items() if k not in self.PRIVATE}
        if with_email:
            d['email'] = self.email
        return d


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
    # Its picture (R6b): a photo, or an emoji; short_name is what the top bar
    # shows when there's no room for the name (initials if blank).
    photo_url = db.Column(db.String(200))
    emoji = db.Column(db.String(16))
    short_name = db.Column(db.String(12))
    # Trivia (R10d), all off until a club admin turns it on: the question of
    # the day (trivia_enabled), posting it in Discord (trivia_discord, its own
    # yes), and extra questions whenever members ask (trivia_anytime).
    trivia_enabled = db.Column(db.Boolean, default=False)
    trivia_discord = db.Column(db.Boolean, default=False)      # before R14; moved to trivia_post, unused
    trivia_anytime = db.Column(db.Boolean, default=False)
    # Repertory bingo (R10e): a monthly card for the club, off until an admin turns it on.
    bingo_enabled = db.Column(db.Boolean, default=False)
    bingo_home = db.Column(db.Boolean, default=False)       # R15: Letterboxd diaries fill film squares
    trivia_source = db.Column(db.String(8), default='both')  # R15: local | tmdb | both (film_pool.SOURCES)
    quizzes_json = db.Column(db.Text)                        # R15: {game: on} — each quiz game's switch (quizzes.GAMES)
    # R14: what the games post in the club's Discord (game_posts.py), each its
    # own choice, all off by default: the question of the day and the month's
    # card 'never' | 'ask' (an admin OKs it first) | 'always'; wins 'never' | 'always'.
    trivia_post = db.Column(db.String(8), default='never')
    bingo_card_post = db.Column(db.String(8), default='never')
    bingo_wins_post = db.Column(db.String(8), default='never')
    # Screening notes (R10f): tags about the screening itself, off until an admin turns them on.
    notes_enabled = db.Column(db.Boolean, default=False)
    # The Monday digest: in the Feed and the bell, and in the club's Discord
    # server. Off for new clubs; on for the home club, which always had it.
    digest_enabled = db.Column(db.Boolean, default=False)
    memberships = db.relationship('GroupMembership', backref='group', lazy=True)

    def to_dict(self, include_members=False, with_email=False):
        d = {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description or '',
            'is_public': self.is_public,
            'theatres': [t.strip() for t in (self.theatres or '').split(',') if t.strip()],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'member_count': sum(1 for m in self.memberships if m.status == 'active'),
            'photo_url': self.photo_url,
            'emoji': self.emoji,
            'short_name': self.short_name or '',
            'discord': core.discord_group(self.id),        # the club's Discord server's group
            'trivia': {'enabled': bool(self.trivia_enabled), 'anytime': bool(self.trivia_anytime),
                       'post': self.trivia_post or 'never', 'source': self.trivia_source or 'both'},
            'bingo': {'enabled': bool(self.bingo_enabled), 'card_post': self.bingo_card_post or 'never',
                      'wins_post': self.bingo_wins_post or 'never', 'home': bool(self.bingo_home)},
            'notes': {'enabled': bool(self.notes_enabled)},
            'digest': {'enabled': bool(self.digest_enabled)},
            'quizzes': __import__('quizzes').switches(self),
            # 7g: theatres whose new showtimes the bot announces in #movies (the same as /announcements)
            'announce_theatres': [t.strip() for t in (self.announce_enabled_theatres or '').split(',') if t.strip()],
        }
        if include_members:
            d['members'] = [m.to_dict(with_email) for m in self.memberships if m.status == 'active']
            d['pending'] = [m.to_dict(with_email) for m in self.memberships if m.status == 'pending']
        return d


class GroupMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # see ROLE_RANK: viewer, member, organizer, admin
    status = db.Column(db.String(20), default='active')  # 'active', 'pending'
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    calendar_token = db.Column(db.String(64), unique=True)   # R7a: this member's club-plans link
    user = db.relationship('User', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'group_id'),)

    def to_dict(self, with_email=False):
        """A membership as other members see it; emails only for club admins."""
        return {
            'id': self.id,
            'user': self.user.public_dict(with_email) if self.user else None,
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
    latitude = db.Column(db.Float)                 # for the theatre page's map (R7a)
    longitude = db.Column(db.Float)
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
            'lat': self.latitude,
            'lon': self.longitude,
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
    original_language = db.Column(db.String(8))   # TMDB's ISO 639-1 code (R13: foreign-language films)
    details_refreshed_at = db.Column(db.DateTime)  # last time TMDB *and* OMDb both answered (backfill --refresh)
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
    is_cancelled = db.Column(db.Boolean, default=False)     # the venue said so (AMC); never guessed
    # When it vanished from the venue's site — off sale, most likely sold out
    # (AFI and others just drop a full show). It stays findable and
    # RSVP-able, counted as sold out, until it reappears.
    off_sale_at = db.Column(db.DateTime)
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
            {'id': r.user.id, 'name': r.user.name, **core.face(r.user)}
            for r in rsvps if r.status == 'going'
        ]
        maybes = [
            {'id': r.user.id, 'name': r.user.name, **core.face(r.user)}
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
        if user_genres and self.movie.genres:     # your favorite genres' keys (taste.genres)
            if set(user_genres) & {g.strip() for g in self.movie.genres.split(',')}:
                recommended = True

        return {
            'id': self.id,
            'movie': self.movie.to_dict(),
            'theatre': self.theatre.to_dict(),
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'purchase_link': self.purchase_link,
            'is_sold_out': self.is_sold_out,
            'off_sale': bool(self.off_sale_at),
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
    status = db.Column(db.String(20), default='ok')  # 'ok', 'partial' (took nothing off sale), 'empty', 'error'
    movies_found = db.Column(db.Integer, default=0)
    new_movies = db.Column(db.Integer, default=0)
    new_showtimes = db.Column(db.Integer, default=0)
    cancelled_showtimes = db.Column(db.Integer, default=0)     # the venue cancelled them
    off_sale_showtimes = db.Column(db.Integer, default=0)      # gone from the venue's site
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
    """A line the bot drops for "what is thy wisdom", /quote random and ambient
    triggers. Only `text` is ever shown in the channel; movie and character are
    the silent source, kept for accuracy and visible only when managing quotes.
    Removal is soft (deleted_at) so a mistaken delete can be undone."""
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    movie = db.Column(db.String(200))
    character = db.Column(db.String(200))
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))     # None for the original list
    # The club whose server it was added in (it shows only there); None = a classic, in every server
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    deleted_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    author = db.relationship('User', foreign_keys=[added_by], lazy=True)

    def to_dict(self):
        return {
            'id': self.id, 'text': self.text, 'movie': self.movie or '', 'character': self.character or '',
            'classic': self.group_id is None,
            'added_by': {'id': self.author.id, 'name': self.author.name,
                         'discord_user_id': self.author.discord_user_id} if self.author else None,
        }


class BotSetting(db.Model):
    """Small settings the Discord bot persists here (it has no storage of its
    own), e.g. the /llm model overrides."""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, default='')


class DiscordServer(db.Model):
    """A Discord server the bot is in, and the club it's connected to (one
    server, one club). A club admin connects it with /setup and a code from
    Club settings; the home server (DEFAULT_GROUP_ID's, the bot's first) is
    registered by the bot itself. group_id None: the bot is there, unconnected."""
    guild_id = db.Column(db.String(30), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), unique=True)
    channel_id = db.Column(db.String(30))               # drops, the digest, game posts, threads
    name = db.Column(db.String(100))
    channel_name = db.Column(db.String(100))
    home = db.Column(db.Boolean, default=False)          # /llm and the classic quotes are managed here
    linked_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    linked_at = db.Column(db.DateTime)
    missing_perms = db.Column(db.String(300))            # what the bot can't do in its channel (Club settings shows it)
    member_count = db.Column(db.Integer)
    reported_at = db.Column(db.DateTime)


class ClubDigest(db.Model):
    """A club's Monday digest as it was published (digest.py): the week's
    picks, kept so the Feed shows the same card all week."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    week_of = db.Column(db.Date, nullable=False)              # that Monday
    published_at = db.Column(db.DateTime, nullable=False)     # UTC
    payload_json = db.Column(db.Text, nullable=False)
    __table_args__ = (db.UniqueConstraint('group_id', 'week_of'),)


class DiscordSetupCode(db.Model):
    """A one-time code a club admin makes in Club settings and runs as
    /setup code:… in the server's channel (30 minutes)."""
    code = db.Column(db.String(12), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)


class DiscordServerMember(db.Model):
    """Who's in each connected Discord server right now; the bot keeps this
    current. Only members who've linked Discord and are in a club's server ever
    appear there. guild_id None: the home server, before the bot first reported
    its id (from before servers were per club)."""
    id = db.Column(db.Integer, primary_key=True)
    guild_id = db.Column(db.String(30), index=True)
    discord_user_id = db.Column(db.String(30), nullable=False, index=True)
    seen_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    __table_args__ = (db.UniqueConstraint('guild_id', 'discord_user_id'),)


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
    source = db.Column(db.String(12))      # None = added on the site (or Discord); 'letterboxd' = imported
    user = db.relationship('User', lazy=True)
    movie = db.relationship('Movie', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'movie_id'),)


class Announcement(db.Model):
    """A film a theatre has announced, with its date, before the showtimes
    and tickets are up (R8b: Suns posts films about a week ahead). Marked
    on sale once its showtimes appear."""
    id = db.Column(db.Integer, primary_key=True)
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False, index=True)
    expected_on = db.Column(db.Date, nullable=False)
    url = db.Column(db.String(500))
    first_seen_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    last_seen_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    on_sale_at = db.Column(db.DateTime)
    theatre = db.relationship('Theatre', lazy=True)
    movie = db.relationship('Movie', lazy=True)
    __table_args__ = (db.UniqueConstraint('theatre_id', 'movie_id'),)


class PushSubscription(db.Model):
    """A browser or phone that gets your alerts as push notifications (R8d)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(800), unique=True, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    user = db.relationship('User', lazy=True)


class KernelGift(db.Model):
    """Kernels a member gave (amount > 0) or took (< 0) for another member's
    activity at a screening (R10b) — one row per giver, recipient, screening,
    club and week, so the per-card and weekly limits are easy to hold."""
    id = db.Column(db.Integer, primary_key=True)
    giver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    week = db.Column(db.Date, nullable=False)              # the Monday it counts against
    amount = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    updated_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    __table_args__ = (db.UniqueConstraint('giver_id', 'recipient_id', 'group_id', 'showtime_id', 'week'),)


class LetterboxdEntry(db.Model):
    """A diary entry read from a member's Letterboxd feed (R10f) — kept so it
    isn't read twice, and (when it matched a screening) for the "Did you make
    it?" hint and the rating shown with the check-in. status: 'checked_in' |
    'suggested' | 'ignored' | 'already' (answered before) | 'unmatched'."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    guid = db.Column(db.String(80), nullable=False)
    watched_on = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(200))
    year = db.Column(db.Integer)
    tmdb_id = db.Column(db.Integer)
    rating = db.Column(db.Float)
    rewatch = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(300))
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), index=True)
    status = db.Column(db.String(12), nullable=False, default='unmatched')
    review = db.Column(db.Text)                     # R15: the review's words (a quiz clue, never named)
    genres = db.Column(db.Text)                     # R15 home bingo: the film's genres and runtime,
    runtime = db.Column(db.Integer)                 # from our films or TMDB (letterboxd.fill_details)
    details_at = db.Column(db.DateTime)             # when they were looked up
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    __table_args__ = (db.UniqueConstraint('user_id', 'guid'),)


class LetterboxdWatch(db.Model):
    """A film on a member's Letterboxd watchlist, from their last import (the
    export's watchlist.csv). It joins their watchlist here (a Watchlist row,
    source 'letterboxd') once the film is in our catalog — at import, or when
    a scrape or a TMDB search adds it (letterboxd.match_films). `dismissed`:
    they removed it here, so re-imports leave it out."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    title_key = db.Column(db.String(255), nullable=False, index=True)   # letterboxd.clean_title(title)
    year = db.Column(db.Integer)
    uri = db.Column(db.String(200))
    added_on = db.Column(db.Date)                    # when they added it on Letterboxd
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), index=True)
    dismissed = db.Column(db.Boolean, default=False)
    imported_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    movie = db.relationship('Movie', lazy=True)


class GamePost(db.Model):
    """Something a club game posts in Discord (R14, game_posts.py): today's
    trivia question (ref: the day), the month's bingo card (ref: the month) or
    a member's win (ref: month:user:line|full). 'waiting' for an admin's OK
    (Ask first), 'approved' (the bot posts it), 'posted', 'skipped' (by an
    admin) or 'expired' (nobody said yes in time)."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)          # 'trivia' | 'bingo_card' | 'bingo_win'
    ref = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(10), nullable=False, default='waiting')
    payload_json = db.Column(db.Text)                        # wins: {user_id, which}
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    decided_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    decided_at = db.Column(db.DateTime)
    posted_at = db.Column(db.DateTime)
    message_id = db.Column(db.String(30))
    __table_args__ = (db.UniqueConstraint('group_id', 'kind', 'ref'),)


class TasteItem(db.Model):
    """One thing in someone's taste (R13, see taste.py): a favorite genre, a
    genre they're not into, a way they like to watch, a favorite theatre,
    film or person, or a film they said is not for them. `key` identifies it
    within its kind; `label` is what to show."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    key = db.Column(db.String(200), nullable=False)
    label = db.Column(db.String(200))
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'))
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    movie = db.relationship('Movie', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'kind', 'key'),)


class ScreeningNote(db.Model):
    """A quick tag about a screening from someone who checked in (R10f): the
    print, the sound, the crowd… (see notes.py)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False, index=True)
    tag = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    __table_args__ = (db.UniqueConstraint('user_id', 'showtime_id', 'tag'),)


class BingoCard(db.Model):
    """A club's repertory bingo card for a month (R10e): 8 squares around a
    free middle, the same for every member, filled in from check-ins (see
    bingo.py). Kept once made, so it doesn't change as the calendar does."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    month = db.Column(db.String(7), nullable=False)            # 'YYYY-MM'
    squares_json = db.Column(db.Text, nullable=False)          # 8 square keys, in grid order (the middle is free)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    __table_args__ = (db.UniqueConstraint('group_id', 'month'),)


class TriviaQuestion(db.Model):
    """A trivia question (R10d), made from the films and quotes we have (see
    trivia.py): the club's question of the day (slot 'daily'), or one a member
    asked for (asked_by; slot '<user id>:<n>'). `answer` is the right option's
    index."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)
    slot = db.Column(db.String(30), nullable=False, default='daily')
    asked_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    kind = db.Column(db.String(20), nullable=False)           # director | first | cast | tagline | quote
    prompt = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Integer, nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'))
    ref = db.Column(db.String(200))                           # what it's about, so it isn't asked again soon
    discord_message_id = db.Column(db.String(30))
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    difficulty = db.Column(db.String(8))                      # easy | medium | hard (R15; None: before, = medium)
    tmdb_id = db.Column(db.Integer)                           # about a film from the TMDB pool, not one of ours
    __table_args__ = (db.UniqueConstraint('group_id', 'day', 'slot'),)


class QuizRound(db.Model):
    """One go at a quiz game (R15, quizzes.py): a higher-or-lower run, a
    who-said-it question… `state_json` holds what it shows and its answers;
    `earned` the kernels it paid (within each game's daily cap)."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    day = db.Column(db.Date, nullable=False)
    state_json = db.Column(db.Text, nullable=False, default='{}')
    status = db.Column(db.String(8), nullable=False, default='open')     # open | done
    score = db.Column(db.Integer, nullable=False, default=0)             # right calls (a streak's length)
    earned = db.Column(db.Integer, nullable=False, default=0)
    source = db.Column(db.String(10))                                    # 'site' | 'discord'
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    finished_at = db.Column(db.DateTime)


class PoolFilm(db.Model):
    """A well-known film from TMDB (R15, film_pool.py): trivia's wider pool
    and its look-alike wrong answers. Refreshed weekly; who directed it, its
    tagline and cast are looked up only when a question needs them."""
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    year = db.Column(db.Integer)
    genres = db.Column(db.Text)
    popularity = db.Column(db.Float)
    vote_count = db.Column(db.Integer)
    poster_url = db.Column(db.String(500))
    refreshed_at = db.Column(db.DateTime)
    director = db.Column(db.String(200))
    tagline = db.Column(db.String(500))
    cast_json = db.Column(db.Text)                            # JSON: [{name, character}, …] (top billed)
    overview = db.Column(db.Text)                             # TMDB's plot summary (emoji plot, R15)
    details_at = db.Column(db.DateTime)


class EmojiPlot(db.Model):
    """A film's plot as emojis (R15, the Emoji plot game): asked of the AI once
    per film and kept. key: film_pool's ('film:<id>' / 'tmdb:<id>')."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    emojis = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())


class TriviaAnswer(db.Model):
    """One member's answer to a question of the day — one try each."""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('trivia_question.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    choice = db.Column(db.Integer, nullable=False)
    correct = db.Column(db.Boolean, nullable=False)
    source = db.Column(db.String(10))                         # 'site' | 'discord'
    answered_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    question = db.relationship('TriviaQuestion', lazy=True)
    __table_args__ = (db.UniqueConstraint('question_id', 'user_id'),)


class SavedSearch(db.Model):
    """A Browse search someone wants alerts for (R10a): when a theatre books a
    film that fits it, they get an alert (see notify.alert_saved_searches).
    `params_json`: the filters (notify.search_params), never a date window."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))    # the club's theatres; None = every theatre
    params_json = db.Column(db.Text, nullable=False)
    label = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    user = db.relationship('User', lazy=True)
    hits = db.relationship('SavedSearchHit', lazy=True, cascade='all, delete-orphan', backref='search')


class SavedSearchHit(db.Model):
    """A film already fitting a saved search at a theatre, so it alerts once.
    Forgotten when the film has been gone a few days (a later booking alerts
    again)."""
    id = db.Column(db.Integer, primary_key=True)
    search_id = db.Column(db.Integer, db.ForeignKey('saved_search.id'), nullable=False, index=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'), nullable=False)
    seen_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    __table_args__ = (db.UniqueConstraint('search_id', 'movie_id', 'theatre_id'),)


class Notification(db.Model):
    """A personal alert (R8), e.g. a film on your watchlist got showings. Kept
    for the bell; also sent by Discord DM / email (and push) as your
    notification setting says, bundled per scrape run (see notify.py)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)       # 'showings' | 'announced' | 'on_sale' | 'search'
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'))
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'))
    payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: core._utcnow_naive())
    ready_at = db.Column(db.DateTime)       # the scrape run finished: send it
    read_at = db.Column(db.DateTime)
    cleared_at = db.Column(db.DateTime)     # cleared from the bell; kept so it isn't sent again
    channels = db.Column(db.String(40), default='')       # where to send it, decided when made
    discord_at = db.Column(db.DateTime)
    email_at = db.Column(db.DateTime)
    push_at = db.Column(db.DateTime)
    user = db.relationship('User', lazy=True)
    movie = db.relationship('Movie', lazy=True)
    theatre = db.relationship('Theatre', lazy=True)


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
