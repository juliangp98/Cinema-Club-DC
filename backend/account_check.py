"""
Someone can't sign in: check their account, test the email, or hand them a
sign-in link yourself.

  account_check.py person@example.com          what we know: the account (active?
                                                which clubs, Discord linked?) and
                                                their recent sign-in requests
  account_check.py person@example.com --send   send them a real sign-in email and
                                                say whether the mail server took it
  account_check.py person@example.com --link   print a one-time sign-in link (15
                                                minutes) to pass on to them yourself
  account_check.py --smtp                      only test the mail settings: log in
                                                to Gmail's SMTP server, send nothing
  account_check.py --smtp --repeat 20          …20 times, a second apart: how often
                                                name lookups or the network fail
  account_check.py --dns --repeat 30           where lookups fail: the usual way (IPv4,
                                                and IPv4 + IPv6), and straight to the
                                                caching resolver and the router

Usage:
    # Local
    cd backend && ./venv/bin/python account_check.py person@example.com
    # Inside the production container
    sudo docker exec cinemaclub-backend python account_check.py person@example.com
"""

import argparse
import re
import secrets
import smtplib
import socket
import struct
import time
from datetime import timedelta

from app import (FRONTEND_URL, SMTP_EMAIL, SMTP_PASSWORD, GroupMembership, LoginToken, User, _utcnow_naive, app, db,
                 email_failure, email_signin_link, prepare_db)

# What each kind of failure means, and what to do about it.
ADVICE = {
    'password': ('Gmail refused the login: the app password was changed or revoked. Make a new one (Google account →'
                 ' Security → App passwords), put it in SMTP_PASSWORD in .env.production and rebuild the backend.'),
    'lookup': ("The server couldn't look up smtp.gmail.com's address (DNS). The password wasn't tried. If this keeps"
               ' happening, the NAS or router is failing name lookups: see "DNS" in docs/deploying.md.'),
    'network': ("Couldn't reach Gmail's mail server (the network, not the password). Try again in a minute."),
}


def smtp_check():
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print('✗ SMTP_EMAIL / SMTP_PASSWORD are not set: emails are only printed to the log.')
        return False
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
        print(f'✓ Gmail accepted the login for {SMTP_EMAIL}.')
        return True
    except Exception as e:
        kind = email_failure(e)
        print(f"✗ {'Gmail refused the login' if kind == 'password' else 'Gmail could not be reached'} for {SMTP_EMAIL}: {e}")
        print(f'  {ADVICE[kind]}')
        return False


# ─── Where do name lookups fail? ──────────────────────────────────────────────

def _ask(server, name, qtype, timeout=2.0):
    """One DNS question sent straight to `server` (no Docker, no cache in
    between): 'ok', 'no answer', 'SERVFAIL', 'timeout'…"""
    qid = secrets.randbelow(65536)
    packet = (struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0)
              + b''.join(bytes([len(p)]) + p.encode() for p in name.split('.')) + b'\0' + struct.pack('>HH', qtype, 1))
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(packet, (server, 53))
        while True:
            data, _ = s.recvfrom(4096)
            if data[:2] == packet[:2]:
                break
    except socket.timeout:
        return 'timeout'
    except OSError as e:
        return f'error: {e}'
    finally:
        s.close()
    rcode, answers = data[3] & 0x0F, struct.unpack('>H', data[6:8])[0]
    return {0: 'ok' if answers else 'no answer', 2: 'SERVFAIL', 3: 'no such name', 5: 'refused'}.get(rcode, f'rcode {rcode}')


def _usual(name, family):
    """A lookup the way the app makes one (through Docker's forwarder), without the retry."""
    import net_retry
    try:
        net_retry._original(name, 465, family, socket.SOCK_STREAM)
        return 'ok'
    except socket.gaierror as e:
        return e.strerror or str(e)


def _servers():
    """The DNS servers Docker forwards to (the caching resolver, then the router)."""
    try:
        for line in open('/etc/resolv.conf'):
            if 'ExtServers' in line:
                return re.findall(r'\d+\.\d+\.\d+\.\d+', line)
    except OSError:
        pass
    return ['172.29.53.53', '192.168.0.1']


def dns_check(rounds, name='smtp.gmail.com'):
    servers = _servers()
    checks = [('the usual way, IPv4 only', lambda: _usual(name, socket.AF_INET)),
              ('the usual way, IPv4 and IPv6', lambda: _usual(name, socket.AF_UNSPEC))]
    for ip in servers:
        checks += [(f'{ip} directly, IPv4', lambda ip=ip: _ask(ip, name, 1)),
                   (f'{ip} directly, IPv6', lambda ip=ip: _ask(ip, name, 28))]
    tally = {label: {} for label, _ in checks}
    print(f'Looking up {name} {rounds} times, a second apart (servers: {", ".join(servers)})…')
    for n in range(rounds):
        if n:
            time.sleep(1)
        for label, check in checks:
            got = check()
            tally[label][got] = tally[label].get(got, 0) + 1
    for label, counts in tally.items():
        print(f"  {label:<34} " + ' · '.join(f'{v} {k}' for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    return tally


def find(email):
    """The account for an address, matching however it was typed or stored."""
    email = email.strip().lower()
    return email, (User.query.filter_by(email=email).first()
                   or User.query.filter(db.func.lower(db.func.trim(User.email)) == email).first())


def describe(email, user):
    if not user:
        print(f'✗ No account has the email {email}.')
        print('  They can sign up with it on the site, or sign in with Discord if they used that before.')
        return
    print(f'Account #{user.id}: {user.name}')
    print(f"  email stored as: {user.email!r}" + ('' if user.email == email else '  ← differs from what was typed'))
    print(f"  active: {'yes' if user.is_active else 'NO (an invite never accepted?): sign-in emails are refused'}")
    print(f"  Discord linked: {'yes' if user.discord_user_id else 'no'} · guest: {'yes' if user.is_guest else 'no'}")
    clubs = GroupMembership.query.filter_by(user_id=user.id).all()
    print('  clubs: ' + (', '.join(f'{m.group.name} ({m.status}, {m.role})' for m in clubs) or 'none'))
    tokens = (LoginToken.query.filter(LoginToken.email == email)
              .order_by(LoginToken.created_at.desc()).limit(5).all())
    if not tokens:
        print('  sign-in requests: none in the last day (old ones are cleared).')
    for t in tokens:
        state = 'used' if t.used_at else 'expired' if t.expires_at < _utcnow_naive() else 'not used yet'
        print(f'  sign-in request {t.created_at:%b %d %H:%M} UTC ({t.purpose}): {state}')
    window = _utcnow_naive() - timedelta(minutes=15)
    if sum(1 for t in tokens if t.created_at > window) >= 5:
        print('  ⚠ five requests in 15 minutes: the site refuses more until that passes.')


def issue(email, user, send):
    from routes.auth import _hash_token, SIGNIN_LINK_TTL
    token = secrets.token_urlsafe(32)
    db.session.add(LoginToken(token_hash=_hash_token(token), email=user.email, purpose='login',
                              expires_at=_utcnow_naive() + SIGNIN_LINK_TTL))
    db.session.commit()
    link = f'{FRONTEND_URL}/auth/verify?token={token}'
    if send:
        ok = email_signin_link(user.email, link, 'login')
        print('✓ The mail server took the email. If it never arrives, ask them to check spam / junk.' if ok
              else '✗ The email could not be sent (the reason is above).')
    else:
        print(f'One-time sign-in link for {user.name} (works once, for 15 minutes):\n  {link}')


def main():
    ap = argparse.ArgumentParser(description='Check an account that can’t sign in.')
    ap.add_argument('email', nargs='?')
    ap.add_argument('--send', action='store_true', help='send them a real sign-in email')
    ap.add_argument('--link', action='store_true', help='print a one-time sign-in link to pass on')
    ap.add_argument('--smtp', action='store_true', help='only test the mail settings')
    ap.add_argument('--dns', action='store_true', help='find where name lookups fail')
    ap.add_argument('--repeat', type=int, default=1, help='with --smtp or --dns: try this many times, a second apart')
    args = ap.parse_args()
    if args.dns:
        dns_check(max(1, args.repeat))
        return
    if args.smtp or not args.email:
        import time
        results = []
        for n in range(max(1, args.repeat)):
            if n:
                time.sleep(1)
            results.append(smtp_check())
        if len(results) > 1:
            print(f'{sum(results)} of {len(results)} worked.')
        return
    prepare_db()
    with app.app_context():
        email, user = find(args.email)
        describe(email, user)
        if user and (args.send or args.link):
            if not user.is_active:
                print('Not sending: the account is inactive.')
                return
            if args.send and not smtp_check():
                return
            issue(email, user, args.send)


if __name__ == '__main__':
    main()
