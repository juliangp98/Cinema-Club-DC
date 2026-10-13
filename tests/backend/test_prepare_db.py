"""Every way in brings the database up to date (Oct 2026): the server and
the scripts run prepare_db(), so a scrape or backfill against a database the
new code hasn't started on yet doesn't fail on a missing column."""
import sqlite3


def test_prepare_db_adds_whats_missing_and_is_safe_to_rerun():
    from app import app, db, prepare_db
    from helpers import setup_db
    setup_db()
    with app.app_context():
        path = db.engine.url.database
        db.session.remove()
        db.engine.dispose()
    con = sqlite3.connect(path)
    con.execute('ALTER TABLE movie DROP COLUMN original_language')         # as if from before R13
    con.commit()
    con.close()
    prepare_db()
    prepare_db()
    with app.app_context():
        cols = {r[1] for r in db.session.execute(db.text('PRAGMA table_info(movie)'))}
    assert 'original_language' in cols


def test_the_scripts_prepare_the_database_first(monkeypatch):
    import app as A
    import backfill_enrichment as B
    calls = []
    monkeypatch.setattr(B, 'prepare_db', lambda: calls.append('backfill'))
    monkeypatch.setattr(B, 'consolidate_catalog', lambda: {'retitled': 0, 'merged': 0, 'labelled': 0})
    monkeypatch.setattr(B, 'lookup_unmatched', lambda force=False: None)
    monkeypatch.setattr('sys.argv', ['backfill_enrichment.py'])
    B.main()
    assert calls == ['backfill']
    src = open(A.__file__.replace('app.py', 'scraper.py')).read()
    assert 'prepare_db()' in src and open(A.__file__.replace('app.py', 'entrypoint.sh')).read().count('prepare_db()') == 1
