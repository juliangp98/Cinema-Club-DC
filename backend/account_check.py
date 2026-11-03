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

Usage:
    # Local
    cd backend && ./venv/bin/python account_check.py person@example.com
    # Inside the production container
    sudo docker exec cinemaclub-backend python account_check.py person@example.com
"""

import argparse
import secrets
import smtplib
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
    ap.add_argument('--repeat', type=int, default=1, help='with --smtp: try this many times, a second apart')
    args = ap.parse_args()
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
