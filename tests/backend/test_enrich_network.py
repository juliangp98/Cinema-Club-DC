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
    """Only films not refreshed yet — and a film OMDb didn't answer for stays
    'not refreshed' so the next run tries it again."""
    from datetime import datetime
    import backfill_enrichment as B
    from app import app, db, Movie
    setup_db()
    with app.app_context():
        db.session.add_all([Movie(title='DONE', tmdb_id=1, details_refreshed_at=datetime(2026, 10, 13)),
                            Movie(title='TODO', tmdb_id=2), Movie(title='REFUSED', tmdb_id=3)])
        db.session.commit()
    asked = []
    monkeypatch.setattr(B, 'enrich_by_tmdb_id',
                        lambda tid, title='': asked.append(tid) or {'original_language': 'fr', 'omdb_ok': tid != 3})
    monkeypatch.setattr(B.time, 'sleep', lambda s: None)
    B.refresh_matched()
    assert 1 not in asked and {2, 3} <= set(asked)
    with app.app_context():
        assert Movie.query.filter_by(title='TODO').first().details_refreshed_at is not None
        assert Movie.query.filter_by(title='REFUSED').first().details_refreshed_at is None     # next time
    asked.clear()
    B.refresh_matched()
    assert 2 not in asked and 3 in asked
    asked.clear()
    B.refresh_matched(everything=True)
    assert {1, 2, 3} <= set(asked)


def test_omdbs_daily_limit_stops_the_run(monkeypatch):
    """OMDb's 401 ('Request limit reached!'): no more OMDb calls for a while,
    the film isn't marked refreshed, and --refresh stops with the rest to go."""
    import backfill_enrichment as B
    import enrich
    from app import app, db, Movie
    setup_db()

    class Resp:
        status_code, content = 401, b'{"Response":"False","Error":"Request limit reached!"}'

        def json(self):
            return {'Response': 'False', 'Error': 'Request limit reached!'}
    calls = []
    monkeypatch.setattr(enrich, '_omdb_key', lambda: 'k')
    monkeypatch.setattr(enrich._http, 'get', lambda *a, **k: calls.append(1) or Resp())
    monkeypatch.setattr(enrich, '_omdb_refused_at', [None])
    assert enrich.enrich_from_omdb('Vertigo', 1958) is enrich.OMDB_FAILED and enrich.omdb_limited()
    assert enrich.enrich_from_omdb('Psycho', 1960) is enrich.OMDB_FAILED and len(calls) == 1      # left alone
    with app.app_context():
        db.session.add_all([Movie(title=f'F{i}', tmdb_id=i) for i in (1, 2, 3)])
        db.session.commit()
    asked = []
    monkeypatch.setattr(B, 'enrich_by_tmdb_id', lambda tid, title='': asked.append(tid))
    B.refresh_matched()
    assert asked == []                                                            # stopped before spending more


def test_no_such_film_on_omdb_counts_as_answered(monkeypatch):
    import enrich
    monkeypatch.setattr(enrich, 'tmdb_details', lambda tid: {'tmdb_title': 'Obscure', 'genres': 'drama'})
    monkeypatch.setattr(enrich, 'enrich_from_omdb', lambda *a, **k: None)
    assert enrich.enrich_by_tmdb_id(5)['omdb_ok'] is True
    monkeypatch.setattr(enrich, 'enrich_from_omdb', lambda *a, **k: enrich.OMDB_FAILED)
    r = enrich.enrich_by_tmdb_id(5)
    assert r['omdb_ok'] is False and r['genres'] == 'drama'                       # TMDB's details still used
