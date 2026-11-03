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


def test_names_go_through_the_caching_resolver_then_the_router():
    """The router fails about 1 lookup in 6 on the NAS: the backend and bot ask
    the caching resolver (the `dns` service, at a fixed address inside the
    project's network) first, and the router only if it's down."""
    src = (ROOT / 'docker-compose.yml').read_text()
    subnet = re.search(r'subnet: (\d+\.\d+\.\d+)\.0/24', src).group(1)
    fixed = re.search(r'ipv4_address: (\S+)', src).group(1)
    assert fixed.startswith(subnet + '.')
    for service in ('backend', 'bot'):
        block = re.search(rf'^  {service}:\n(.*?)(?=^  \w|\Z)', src, re.M | re.S).group(1)
        assert re.search(rf'dns:\n\s+- {re.escape(fixed)}\n\s+- 192\.168\.0\.1', block), service
        assert '- dns' in block, f'{service} starts after the resolver'
        assert re.search(r'networks:\n\s+- default\n\s+- lookups', block), f'{service} joins the resolver\'s network'
    # The project's default network is left as it was: replacing it needs every
    # container off it, and on the NAS something else stays attached.
    assert not re.search(r'^  default:', src.split('\nnetworks:\n', 1)[1], re.M)
    conf = (ROOT / 'dns' / 'unbound.conf.in').read_text()
    for line in ('serve-expired: yes', 'forward-addr: @UPSTREAM@', 'module-config: "iterator"'):
        assert line in conf
    assert 'COPY dns/unbound.conf.in' in (ROOT / 'Dockerfile.dns').read_text()
