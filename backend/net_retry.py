"""Name lookups on the NAS fail now and then, in bursts of a few seconds
("Temporary failure in name resolution"), even with the caching resolver
answering (docs/deploying.md, "DNS"). Every outside call this process makes
(Gmail, TMDB, OMDb, the AI, web push) looks its server up through
socket.getaddrinfo: install() makes a failed lookup try again a few times,
a moment apart, before giving up. Only that temporary failure is retried:
a name that doesn't exist fails at once. The bot has the same (bot/net_retry.py:
the two images don't share code)."""
import socket
import time

WAITS = (0.3, 1.0, 2.0)          # seconds before each new try: about 3 s in all
_original = socket.getaddrinfo


def getaddrinfo(*args, **kwargs):
    for wait in WAITS:
        try:
            return _original(*args, **kwargs)
        except socket.gaierror as e:
            if e.errno != socket.EAI_AGAIN:
                raise
            time.sleep(wait)
    return _original(*args, **kwargs)


def install():
    socket.getaddrinfo = getaddrinfo
