"""Enrichment's calls to TMDB and OMDb (Oct 2026): one pooled session that
retries a failed connection — the NAS's router drops some DNS lookups under a
backfill's load — and a --refresh that picks up where a cut-short run stopped."""
import pytest

from helpers import setup_db


def test_one_pooled_session_that_retries():
    import enrich
    adapter = enrich._http.get_adapter('https://api.themoviedb.org/3/movie/1')
    assert enrich._http.get_adapter('http://www.omdbapi.com/') is adapter          # one pool for both
    r = adapter.max_retries
    assert r.connect == 3 and 429 in r.status_forcelist and r.backoff_factor == 1


def test_a_lookup_that_fails_once_is_retried(monkeypatch):
    """The real retry path: the first connection attempt can't resolve the
    host, the second gets through."""
    import socket
    import urllib3.util.connection as conn
    import enrich
    calls = []

    def flaky(address, *a, **k):
        calls.append(address)
        if len(calls) == 1:
            raise socket.gaierror(-3, 'Temporary failure in name resolution')
        raise ConnectionRefusedError('reached the network (good enough for the test)')
    monkeypatch.setattr(conn, 'create_connection', flaky)
    monkeypatch.setattr('urllib3.util.retry.Retry.sleep', lambda self, response=None: None)
    with pytest.raises(Exception):
        enrich._http.get('https://api.themoviedb.org/3/movie/1', timeout=1)
    assert len(calls) == 4                                                       # 1 try + 3 retries
    assert calls[0][0] == 'api.themoviedb.org'


def test_refresh_picks_up_where_it_stopped(monkeypatch):
    import backfill_enrichment as B
    from app import app, db, Movie
    setup_db()
    with app.app_context():
        done = Movie(title='DONE', tmdb_id=1, original_language='en')
        todo = Movie(title='TODO', tmdb_id=2)
        db.session.add_all([done, todo])
        db.session.commit()
    asked = []
    monkeypatch.setattr(B, 'enrich_by_tmdb_id', lambda tid, title='': asked.append(tid) or {'original_language': 'fr'})
    monkeypatch.setattr(B.time, 'sleep', lambda s: None)
    B.refresh_matched()
    assert 1 not in asked and 2 in asked                                          # only what wasn't refreshed
    with app.app_context():
        assert Movie.query.filter_by(title='TODO').first().original_language == 'fr'
    asked.clear()
    B.refresh_matched(everything=True)
    assert {1, 2} <= set(asked)
