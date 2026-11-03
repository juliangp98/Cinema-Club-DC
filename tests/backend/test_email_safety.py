"""Names people choose go into emails as text, never as HTML (R9d), and a
subject is always one line."""
from helpers import client, setup_db


def test_a_join_request_email_shows_the_name_as_text(monkeypatch):
    import app as A
    setup_db()
    sent = []
    monkeypatch.setattr(A, 'send_email', lambda to, subject, body: sent.append((to, subject, body)))
    with A.app.app_context():
        admin = A.User(name='Admin', email='admin@t.dev', is_active=True)
        sneaky = A.User(name='<img src=x onerror=alert(1)>', email='s@t.dev', is_active=True)
        g = A.Group(name='<b>Club</b>', slug='club-x', is_public=True)
        A.db.session.add_all([admin, sneaky, g])
        A.db.session.flush()
        A.db.session.add(A.GroupMembership(user_id=admin.id, group_id=g.id, role='admin', status='active'))
        A.db.session.commit()
        sid = sneaky.id
    assert client(sid).post('/api/groups/club-x/join').status_code == 202
    [(to, subject, body)] = sent
    assert to == 'admin@t.dev'
    assert '<img' not in body and '&lt;img src=x onerror=alert(1)&gt;' in body
    assert '<b>Club</b>' not in body and '&lt;b&gt;Club&lt;/b&gt;' in body


def test_subjects_are_one_line(monkeypatch):
    import app as A
    seen = []
    monkeypatch.setattr(A, 'SMTP_EMAIL', '')
    monkeypatch.setattr('builtins.print', lambda *a, **k: seen.append(' '.join(map(str, a))))
    A.send_email('x@t.dev', 'Hello\r\nBcc: everyone@t.dev', '<p>hi</p>')
    assert any('Subject: Hello Bcc: everyone@t.dev' in line for line in seen)


def test_an_email_carries_a_plain_text_copy(monkeypatch):
    """Mail providers trust a message more with a plain-text copy (and its Date
    and Message-ID); the link is written out in it."""
    import email
    import app as A
    sent = []

    class Server:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def sendmail(self, frm, to, raw):
            sent.append(raw)
    monkeypatch.setattr(A, 'SMTP_EMAIL', 'club@t.dev')
    monkeypatch.setattr(A, 'SMTP_PASSWORD', 'secret')
    monkeypatch.setattr(A.smtplib, 'SMTP_SSL', Server)
    assert A.email_signin_link('x@t.dev', 'https://club.test/auth/verify?token=abc', 'login') is True
    msg = email.message_from_string(sent[0])
    assert msg['Date'] and msg['Message-ID'].endswith('@t.dev>')
    plain, html = [p.get_payload(decode=True).decode() for p in msg.get_payload()]
    assert 'Sign In: https://club.test/auth/verify?token=abc' in plain and '<' not in plain
    assert '<a ' in html


def test_sign_in_says_so_when_the_email_cant_be_sent(monkeypatch):
    """A refused email isn't "check your inbox": the site says it couldn't send
    it. Before, the error only reached the server's log."""
    import app as A
    import routes.auth
    setup_db()
    with A.app.app_context():
        A.db.session.add(A.User(name='Early', email='early@t.dev', is_active=True))
        A.db.session.commit()
    monkeypatch.setattr(A, 'SMTP_EMAIL', 'club@t.dev')
    monkeypatch.setattr(A, 'SMTP_PASSWORD', 'revoked')

    def refuse(*a, **k):
        raise OSError('535 Username and Password not accepted')
    monkeypatch.setattr(A.smtplib, 'SMTP_SSL', refuse)
    monkeypatch.setattr(routes.auth, '_discord_oauth_enabled', lambda: True)
    r = A.app.test_client().post('/api/auth/login', json={'email': ' Early@T.dev '})
    assert r.status_code == 503
    assert r.json['error'] == "We couldn't send the email just now. Try again in a few minutes or sign in with Discord."


def test_account_check_hands_over_a_working_link(capsys):
    """account_check.py --link: an admin's way in for someone whose emails never arrive."""
    import re
    import sys
    import app as A
    import account_check
    setup_db()
    with A.app.app_context():
        A.db.session.add(A.User(name='Early', email='early@t.dev', is_active=True))
        A.db.session.commit()
    sys.argv = ['account_check.py', 'EARLY@t.dev', '--link']
    account_check.main()
    out = capsys.readouterr().out
    assert 'active: yes' in out and 'Discord linked: no' in out
    token = re.search(r'token=([\w-]+)', out).group(1)
    c = A.app.test_client()
    assert c.post('/api/auth/verify', json={'token': token}).json['user']['email'] == 'early@t.dev'


def test_a_failed_lookup_is_tried_again_but_a_refused_password_isnt(monkeypatch):
    """On the NAS, smtp.gmail.com's name lookup sometimes fails for a moment:
    that's tried again (twice, after 1 s and 3 s). A refused login isn't:
    another try wouldn't change Gmail's mind."""
    import smtplib
    import socket
    import app as A
    tries, waits = [], []

    class Server:
        def __init__(self, *a, **k):
            tries.append(1)
            if len(tries) <= fail_first:
                raise error

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def sendmail(self, *a):
            pass
    monkeypatch.setattr(A, 'SMTP_EMAIL', 'club@t.dev')
    monkeypatch.setattr(A, 'SMTP_PASSWORD', 'secret')
    monkeypatch.setattr(A.smtplib, 'SMTP_SSL', Server)
    monkeypatch.setattr(A.time, 'sleep', waits.append)
    error, fail_first = socket.gaierror(-3, 'Temporary failure in name resolution'), 2
    assert A.send_email('x@t.dev', 'Hi', '<p>hi</p>') is True and len(tries) == 3 and waits == [1, 3]
    tries.clear(), waits.clear()
    error, fail_first = smtplib.SMTPAuthenticationError(535, b'Username and Password not accepted'), 9
    assert A.send_email('x@t.dev', 'Hi', '<p>hi</p>') is False and len(tries) == 1 and waits == []
    assert [A.email_failure(e) for e in (socket.gaierror(-3, 'x'), smtplib.SMTPAuthenticationError(535, b'x'),
                                         TimeoutError())] == ['lookup', 'password', 'network']


def test_account_check_says_what_kind_of_failure_it_was(monkeypatch, capsys):
    import socket
    import account_check
    monkeypatch.setattr(account_check, 'SMTP_EMAIL', 'club@t.dev')
    monkeypatch.setattr(account_check, 'SMTP_PASSWORD', 'secret')

    def lookup_fails(*a, **k):
        raise socket.gaierror(-3, 'Temporary failure in name resolution')
    monkeypatch.setattr(account_check.smtplib, 'SMTP_SSL', lookup_fails)
    assert account_check.smtp_check() is False
    out = capsys.readouterr().out
    assert 'Gmail could not be reached' in out and 'The password wasn' in out and 'DNS' in out
