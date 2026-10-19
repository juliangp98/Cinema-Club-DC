"""Bringing the database up to date on start: tables, ADD COLUMN migrations,
one-time backfills (each marked done in BotSetting), the theatres from the
scraper registry, and a fresh install's first admin. prepare_db() runs it all
— the server (entrypoint.sh, `python app.py`) and the scripts call it.
Moved out of app.py in the sprint wrap-up; app re-exports these names."""
import os
import re

from app import BotSetting, DiscordServerMember, HOME_GROUP_ID, Group, GroupMembership, Movie, Theatre, User, app, db


def migrate():
    """Idempotent migrations for SQLite (ADD COLUMN only)."""
    stmts = [
        "ALTER TABLE user ADD COLUMN bio TEXT DEFAULT ''",
        "ALTER TABLE user ADD COLUMN favorite_genres TEXT DEFAULT ''",
        "ALTER TABLE user ADD COLUMN taste_public BOOLEAN DEFAULT 0",
        "ALTER TABLE 'group' ADD COLUMN trivia_post VARCHAR(8) DEFAULT 'never'",
        "ALTER TABLE 'group' ADD COLUMN bingo_card_post VARCHAR(8) DEFAULT 'never'",
        "ALTER TABLE 'group' ADD COLUMN bingo_wins_post VARCHAR(8) DEFAULT 'never'",
        "ALTER TABLE movie ADD COLUMN original_language VARCHAR(8)",
        "ALTER TABLE movie ADD COLUMN details_refreshed_at DATETIME",
        # R15: home bingo — diary entries fill film squares
        "ALTER TABLE 'group' ADD COLUMN bingo_home BOOLEAN DEFAULT 0",
        "ALTER TABLE letterboxd_entry ADD COLUMN genres TEXT",
        "ALTER TABLE letterboxd_entry ADD COLUMN runtime INTEGER",
        "ALTER TABLE letterboxd_entry ADD COLUMN details_at DATETIME",
        # R15: trivia difficulty and sources (film_pool.py)
        "ALTER TABLE trivia_question ADD COLUMN difficulty VARCHAR(8)",
        "ALTER TABLE trivia_question ADD COLUMN tmdb_id INTEGER",
        "ALTER TABLE 'group' ADD COLUMN trivia_source VARCHAR(8) DEFAULT 'both'",
        "ALTER TABLE 'group' ADD COLUMN quizzes_json TEXT",
        "ALTER TABLE user ADD COLUMN letterboxd_clues BOOLEAN DEFAULT 1",
        "ALTER TABLE letterboxd_entry ADD COLUMN review TEXT",
        "ALTER TABLE pool_film ADD COLUMN overview TEXT",
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
        "ALTER TABLE 'group' ADD COLUMN trivia_anytime BOOLEAN DEFAULT 0",
        "ALTER TABLE 'group' ADD COLUMN bingo_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN letterboxd_sync BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN letterboxd_checkin VARCHAR(10) DEFAULT 'ask'",
        "ALTER TABLE user ADD COLUMN letterboxd_ratings BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN letterboxd_synced_at DATETIME",
        "ALTER TABLE 'group' ADD COLUMN notes_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN tour_seen_at DATETIME",
        "ALTER TABLE user ADD COLUMN tours_json TEXT",              # 7f: page tours
        # R7a: theatre maps, calendar subscriptions
        "ALTER TABLE theatre ADD COLUMN latitude FLOAT",
        "ALTER TABLE theatre ADD COLUMN longitude FLOAT",
        "ALTER TABLE user ADD COLUMN calendar_token VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_user_calendar_token ON user (calendar_token)",
        "ALTER TABLE group_membership ADD COLUMN calendar_token VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_membership_calendar_token ON group_membership (calendar_token)",
        # R8: alerts
        "ALTER TABLE user ADD COLUMN notify_prefs TEXT",
        # Phase 8: a show gone from the venue's site is off sale (likely sold out), not cancelled
        "ALTER TABLE showtime ADD COLUMN off_sale_at DATETIME",
        "ALTER TABLE scrape_run ADD COLUMN off_sale_showtimes INTEGER DEFAULT 0",
        # Letterboxd watchlist import
        "ALTER TABLE watchlist ADD COLUMN source VARCHAR(12)",
        "ALTER TABLE user ADD COLUMN letterboxd_watch_on BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN letterboxd_watch_alerts BOOLEAN",
        "ALTER TABLE user ADD COLUMN letterboxd_watch_imported_at DATETIME",
        # The bot in other servers: quotes added in a club's server show only there
        "ALTER TABLE quote ADD COLUMN group_id INTEGER REFERENCES 'group'(id)",
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
    _migrate_trivia_slots()
    __import__('taste').migrate_legacy_genres()
    # Films refreshed before the marker existed: done if OMDb clearly answered (it gave ratings).
    if not db.session.get(BotSetting, 'details_marker_backfilled'):
        db.session.execute(db.text("UPDATE movie SET details_refreshed_at = CURRENT_TIMESTAMP WHERE details_refreshed_at IS NULL "
                                   "AND original_language IS NOT NULL AND ratings_json IS NOT NULL"))
        db.session.add(BotSetting(key='details_marker_backfilled', value='1'))
        db.session.commit()
    # SEO (Oct 2026): with the site open to search engines, the Discord
    # server's club becomes invite-only — not listed on the Clubs page, and
    # strangers can't ask to join (an admin can change it in Club settings).
    if not db.session.get(BotSetting, 'discord_club_private_done'):
        db.session.execute(db.text("UPDATE 'group' SET is_public = 0 WHERE id = :g"), {'g': HOME_GROUP_ID})
        db.session.add(BotSetting(key='discord_club_private_done', value='1'))
        db.session.commit()
    # Phase 8: until now a show gone from a venue's site was marked cancelled
    # (hidden, RSVPs dropped). No venue we scrape ever said "cancelled", so
    # every one of those was off sale — usually sold out. Bring them back as that.
    if not db.session.get(BotSetting, 'off_sale_backfill_done'):
        db.session.execute(db.text("UPDATE showtime SET off_sale_at = CURRENT_TIMESTAMP, is_sold_out = 1, "
                                   "is_cancelled = 0 WHERE is_cancelled = 1"))
        db.session.add(BotSetting(key='off_sale_backfill_done', value='1'))
        db.session.commit()
    # R14: "post the question of the day in Discord" (a yes/no) is now Always.
    db.session.execute(db.text("UPDATE 'group' SET trivia_post = 'always' WHERE trivia_discord = 1"))
    db.session.execute(db.text("UPDATE 'group' SET trivia_discord = 0 WHERE trivia_discord = 1"))
    db.session.commit()
    _migrate_user_email_nullable()
    _backfill_title_normalized()
    _migrate_server_members()
    # The bot in other servers: quotes members added so far were added in the
    # home server, so they're the home club's; the original list stays shared.
    if not db.session.get(BotSetting, 'quotes_per_club_done'):
        db.session.execute(db.text("UPDATE quote SET group_id = :g WHERE added_by IS NOT NULL AND group_id IS NULL"),
                           {'g': HOME_GROUP_ID})
        db.session.add(BotSetting(key='quotes_per_club_done', value='1'))
        db.session.commit()


def _migrate_server_members():
    """discord_server_member was one server's list (keyed by Discord id); now
    it's per server. Rebuild it once, keeping today's rows as the home
    server's (guild None until the bot reports its id)."""
    cols = [r[1] for r in db.session.execute(db.text("PRAGMA table_info(discord_server_member)"))]
    if not cols or 'guild_id' in cols:
        return
    _backup_sqlite('pre-server-members')
    db.session.execute(db.text("ALTER TABLE discord_server_member RENAME TO discord_server_member_old"))
    db.session.commit()
    DiscordServerMember.__table__.create(db.engine)
    db.session.execute(db.text("INSERT INTO discord_server_member (guild_id, discord_user_id, seen_at) "
                               "SELECT NULL, discord_user_id, seen_at FROM discord_server_member_old"))
    db.session.execute(db.text("DROP TABLE discord_server_member_old"))
    db.session.commit()


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


def _migrate_trivia_slots():
    """R10d first kept one question per club per day; anytime questions need
    UNIQUE(group_id, day, slot). Rebuild an older trivia_question, keeping its
    rows as the club's daily questions."""
    cols = [r[1] for r in db.session.execute(db.text("PRAGMA table_info(trivia_question)"))]
    if not cols or 'slot' in cols:
        return
    db.session.execute(db.text("DROP TABLE IF EXISTS trivia_question_new"))
    db.session.execute(db.text("""
        CREATE TABLE trivia_question_new (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES 'group'(id),
            day DATE NOT NULL,
            slot VARCHAR(30) NOT NULL DEFAULT 'daily',
            asked_by INTEGER REFERENCES user(id),
            kind VARCHAR(20) NOT NULL,
            prompt TEXT NOT NULL,
            options_json TEXT NOT NULL,
            answer INTEGER NOT NULL,
            movie_id INTEGER REFERENCES movie(id),
            ref VARCHAR(200),
            discord_message_id VARCHAR(30),
            created_at DATETIME,
            difficulty VARCHAR(8),
            tmdb_id INTEGER,
            UNIQUE (group_id, day, slot)
        )
    """))
    db.session.execute(db.text("""
        INSERT INTO trivia_question_new (id, group_id, day, slot, kind, prompt, options_json, answer, movie_id, ref,
                                         discord_message_id, created_at)
        SELECT id, group_id, day, 'daily', kind, prompt, options_json, answer, movie_id, ref, discord_message_id, created_at
        FROM trivia_question"""))
    db.session.execute(db.text("DROP TABLE trivia_question"))
    db.session.execute(db.text("ALTER TABLE trivia_question_new RENAME TO trivia_question"))
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


def prepare_db():
    """Bring the database up to date — tables, migrations, theatres, the first
    admin. Every way in runs it: the server (entrypoint.sh, `python app.py`)
    and the scripts (scraper.py, backfill_enrichment.py), so a script run
    against a database the new code hasn't started on yet doesn't fail on a
    missing column. Safe to run any number of times."""
    with app.app_context():
        db.create_all()
        migrate()
        seed_theatres()
        seed_admin()


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
            is_public=False,                 # the Discord server's club: invite-only
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
