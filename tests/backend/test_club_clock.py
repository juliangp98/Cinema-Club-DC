"""The club's clock: showtimes are stored as the theatres' wall-clock times and
compared with datetime.now(), so the backend and bot containers run on DC time.
On the image's default (UTC), tonight's 8 PM show counted as started at 4 PM,
the question of the day changed at 8 PM and scheduled posts went out early."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_backend_and_bot_run_on_dc_time():
    for name in ('Dockerfile.backend', 'Dockerfile.bot'):
        src = (ROOT / name).read_text()
        assert re.search(r'^ENV TZ=America/New_York$', src, re.M), f'{name} must set TZ=America/New_York'


def test_the_compose_file_doesnt_override_it():
    src = (ROOT / 'docker-compose.yml').read_text()
    assert not re.search(r'\bTZ=', src.replace('TZ=America/New_York', ''))
