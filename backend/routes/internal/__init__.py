"""The Discord bot's API (X-Internal-Token): everything the bot reads and writes,
by area. Each module registers its routes on `app` when imported.

Routes (and their own helpers) moved out of app.py in R9b and were split by
area in the sprint wrap-up; shared helpers and the models come from app."""
from routes.internal import common, posts, schedule, threads, people, games, admin, servers  # noqa: F401 — each registers its routes
