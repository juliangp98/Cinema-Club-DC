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
    """Docker's own DNS forwarder failed about 1 lookup in 5 on the NAS; the
    router answered every time. The backend (outside names only) skips the
    forwarder: its own resolv.conf asks the router, then the caching resolver
    (the `dns` service, at a fixed address on its own network). The bot needs
    Docker's names (`backend`), so it keeps the forwarder: the resolver, then
    the router."""
    src = (ROOT / 'docker-compose.yml').read_text()
    subnet = re.search(r'subnet: (\d+\.\d+\.\d+)\.0/24', src).group(1)
    fixed = re.search(r'ipv4_address: (\S+)', src).group(1)
    assert fixed.startswith(subnet + '.')
    block = lambda name: re.search(rf'^  {name}:\n(.*?)(?=^  \w|\Z)', src, re.M | re.S).group(1)
    backend, bot = block('backend'), block('bot')
    assert './dns/resolv.backend.conf:/etc/resolv.conf:ro' in backend and 'dns:\n' not in backend
    resolv = (ROOT / 'dns' / 'resolv.backend.conf').read_text()
    assert re.findall(r'^nameserver (\S+)', resolv, re.M) == ['192.168.0.1', fixed]
    assert re.search(rf'dns:\n\s+- {re.escape(fixed)}\n\s+- 192\.168\.0\.1', bot)
    for b in (backend, bot):
        assert '- dns' in b and re.search(r'networks:\n\s+- default\n\s+- lookups', b)
    # The project's default network is left as it was: replacing it needs every
    # container off it, and on the NAS the Cloudflare tunnel stays attached.
    assert not re.search(r'^  default:', src.split('\nnetworks:\n', 1)[1], re.M)
    conf = (ROOT / 'dns' / 'unbound.conf.in').read_text()
    for line in ('serve-expired: yes', 'forward-addr: @UPSTREAM@', 'module-config: "iterator"'):
        assert line in conf
    assert 'COPY dns/unbound.conf.in' in (ROOT / 'Dockerfile.dns').read_text()
