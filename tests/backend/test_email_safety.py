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
