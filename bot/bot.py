"""Cinema Club DC Discord bot.

Posts a Monday digest in #movies (the main notification: who's going, watchlist
tags, rare screenings, new showtimes), announces schedule drops for theatres
members opt into with /announcements, DMs the owner about scraper errors and chatbot
model changes, and serves slash commands — films (/showtimes, /movie, /foryou, /find,
/surprise, /theatre), plans (/rsvp, /discuss, /watch, /notifications), games (/play,
/leaderboard, /poll list|vote|make), people (/profile, /club, /link) and extras
(/digest, /announcements, /quote, /help, /llm) — and DMs members "did you go?" after
screenings they RSVP'd to.
Members choose what they share from the site (RSVPs, "who's in?" invites,
polls and results); those posts stay in step with the site. Each screening's
discussion can have a thread in #movies, mirrored with the site.
All data comes from the Flask backend's /api/internal/* endpoints — the bot
never touches the database directly.

The bot is split by feature in features/ (shared, chat, alerts, schedule,
threads, profile, polls, admin, games, club, servers); each registers its own
buttons and loops. This file starts it, and gathers their names in one place
(for the tests).
"""

import os

from features import shared                       # first: it loads the env the others read
from features import chat, alerts, schedule, threads, profile, polls, admin, games, club, servers  # noqa: F401 — they register themselves
from features.shared import *                  # noqa: F401,F403
from features.chat import *                    # noqa: F401,F403
from features.alerts import *                  # noqa: F401,F403
from features.schedule import *                # noqa: F401,F403
from features.threads import *                 # noqa: F401,F403
from features.profile import *                 # noqa: F401,F403
from features.polls import *                   # noqa: F401,F403
from features.admin import *                   # noqa: F401,F403
from features.games import *                   # noqa: F401,F403
from features.club import *                    # noqa: F401,F403
from features.servers import *                 # noqa: F401,F403
from features.shared import DISCORD_BOT_TOKEN, client

# What the bot needs from its environment (docs/discord-bot.md): it can't
# start without the token; the rest is named once if unset.
BOT_SETTINGS = (
    ('INTERNAL_API_TOKEN', "every command fails: the backend won't answer the bot"),
    ('DISCORD_CHANNEL_ID', 'no schedule drops, digests or game posts in a channel'),
    ('GROQ_API_KEY', 'no chat replies, emoji plots or AI poll drafts'),
)


def report_settings(env=os.environ, out=print):
    gaps = [(name, why) for name, why in BOT_SETTINGS if not env.get(name, '').strip()]
    if gaps:
        out('\n'.join(['⚠️  Settings not set (see docs/discord-bot.md):']
                      + [f'   {name:<20} {why}' for name, why in gaps]))
    return gaps


if __name__ == '__main__':
    if not DISCORD_BOT_TOKEN:
        raise SystemExit('DISCORD_BOT_TOKEN is not set (see docs/discord-bot.md)')
    report_settings()
    client.run(DISCORD_BOT_TOKEN)
