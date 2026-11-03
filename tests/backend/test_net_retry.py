"""Name lookups on the NAS fail now and then, in bursts ("Temporary failure
in name resolution"), whatever resolver answers: every lookup the backend and
bot make is tried again a few times, a moment apart. A name that doesn't
exist fails at once."""
import ast
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_a_failed_lookup_is_tried_again(monkeypatch):
    import net_retry
    calls, waits = [], []

    def flaky(*a, **k):
        calls.append(a)
        if len(calls) < 3:
            raise socket.gaierror(socket.EAI_AGAIN, 'Temporary failure in name resolution')
        return [('found',)]
    monkeypatch.setattr(net_retry, '_original', flaky)
    monkeypatch.setattr(net_retry.time, 'sleep', waits.append)
    assert net_retry.getaddrinfo('smtp.gmail.com', 465) == [('found',)] and len(calls) == 3 and waits == [0.3, 1.0]


def test_a_name_that_doesnt_exist_fails_at_once(monkeypatch):
    import net_retry
    calls = []

    def nowhere(*a, **k):
        calls.append(a)
        raise socket.gaierror(socket.EAI_NONAME, 'Name or service not known')
    monkeypatch.setattr(net_retry, '_original', nowhere)
    try:
        net_retry.getaddrinfo('nowhere.invalid', 80)
    except socket.gaierror as e:
        assert e.errno == socket.EAI_NONAME
    assert len(calls) == 1


def test_it_gives_up_after_about_three_seconds(monkeypatch):
    import net_retry
    waits = []

    def down(*a, **k):
        raise socket.gaierror(socket.EAI_AGAIN, 'Temporary failure in name resolution')
    monkeypatch.setattr(net_retry, '_original', down)
    monkeypatch.setattr(net_retry.time, 'sleep', waits.append)
    try:
        net_retry.getaddrinfo('smtp.gmail.com', 465)
        raise AssertionError('should have failed')
    except socket.gaierror:
        pass
    assert sum(waits) <= 3.5


def test_the_backend_and_bot_retry_the_same_way():
    """Two copies (the images don't share code): the same code, and both installed at start."""
    def code(path):
        tree = ast.parse(path.read_text())
        tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        return ast.dump(tree)
    assert code(ROOT / 'backend' / 'net_retry.py') == code(ROOT / 'bot' / 'net_retry.py')
    assert 'net_retry.install()' in (ROOT / 'backend' / 'app.py').read_text()
    assert 'net_retry.install()' in (ROOT / 'bot' / 'bot.py').read_text()
