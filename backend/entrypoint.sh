#!/bin/bash
set -e

# Run database migrations and seed data on startup
python -c "
from app import prepare_db
import config_check
prepare_db()
print('Database initialized.')
config_check.report()
"

# Start Gunicorn
# Threads: AI calls (the chatbot, poll drafts) take seconds; they mustn't hold up page loads.
# Each worker keeps the public pages pre-built (see start_warming in app.py).
export WARM_PUBLIC_CACHE=1
exec gunicorn -w 2 --threads 4 -b 0.0.0.0:5001 --timeout 120 app:app
