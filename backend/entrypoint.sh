#!/bin/bash
set -e

# Run database migrations and seed data on startup
python -c "
from app import app, db, migrate, seed_theatres, seed_admin
with app.app_context():
    db.create_all()
    migrate()
    seed_theatres()
    seed_admin()
print('Database initialized.')
"

# Start Gunicorn
# Threads: AI calls (the chatbot, poll drafts) take seconds; they mustn't hold up page loads.
# Each worker keeps the public pages pre-built (see start_warming in app.py).
export WARM_PUBLIC_CACHE=1
exec gunicorn -w 2 --threads 4 -b 0.0.0.0:5001 --timeout 120 app:app
