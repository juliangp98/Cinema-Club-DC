"""The shared AI (backend/ai.py) against a fake Groq: choosing models,
falling back, replacing retired ones, and the /llm overrides."""
import json

import pytest

from helpers import H, client, setup_db

MODELS = ['llama-3.3-70b-versatile', 'qwen/qwen3-32b', 'openai/gpt-oss-120b', 'meta-llama/llama-guard-4-12b', 'whisper-large-v3']
HI = {'messages': [{'role': 'user', 'content': 'hi'}]}


@pytest.fixture
def fake():
    import ai
    from fake_groq import Fake
    setup_db()
    ai._client = Fake(MODELS)
    return ai._client


def reset_choice(shared=False):
    """As if a second server process started (no models chosen yet) — and,
    with `shared`, as if no process had ever chosen."""
    import ai
    ai._state.update(primary=None, fallback=None, how={}, available=[], checked_at=0.0, loaded_at=0.0)
    ai._extras.clear()
    if shared:
        from app import app, db, BotSetting
        with app.app_context():
            BotSetting.query.filter(BotSetting.key.in_(('ai_models', 'ai_check_at'))).delete()
            db.session.commit()


def owner_notices():
    from app import app, ActivityEvent
    with app.app_context():
        return [json.loads(e.payload_json)['message'] for e in ActivityEvent.query.filter_by(kind='llm_switch')]


def status():
    return client().get('/api/internal/ai/status', headers=H).json


def chat():
    return client().post('/api/internal/ai/chat', json=HI, headers=H)


def test_first_use_picks_models_and_tells_the_owner_once(fake):
    import ai
    r = client().post('/api/internal/ai/chat', json={**HI, 'max_tokens': 50}, headers=H)
    s = status()
    assert r.json == {'text': 'reply from qwen/qwen3-32b'}
    assert s['primary'] == 'qwen/qwen3-32b' and ai.family(s['fallback']) != 'qwen'
    assert not any(m in s['available'] for m in ('meta-llama/llama-guard-4-12b', 'whisper-large-v3'))   # not chat models
    assert len(owner_notices()) == 1 and 'primary `qwen/qwen3-32b`' in owner_notices()[0]
    reset_choice()
    status()
    assert len(owner_notices()) == 1           # another process making the same choice says nothing


def test_a_rate_limited_primary_falls_back(fake):
    fallback = status()['fallback']
    fake.limited = {'qwen/qwen3-32b'}
    r = chat()
    assert r.status_code == 200 and r.json['text'] == f'reply from {fallback}'
    fake.limited = {'qwen/qwen3-32b', fallback}
    r = chat()
    assert r.status_code == 429 and abs(r.json['retry_after'] - 672.5) < 0.01      # when it'll be back


def test_a_retired_model_is_replaced_and_the_owner_told(fake):
    status()
    fake.gone = {'qwen/qwen3-32b'}
    assert chat().status_code == 200
    s = status()
    assert s['primary'] and s['primary'] != 'qwen/qwen3-32b'
    assert len(owner_notices()) == 2


def test_overrides_and_empty_answers(fake):
    from app import app, db, BotSetting
    status()
    with app.app_context():
        db.session.add(BotSetting(key='llm_primary', value='llama-3.3-70b-versatile'))
        db.session.commit()
    s = client().post('/api/internal/ai/refresh', json={'reason': 'test'}, headers=H).json
    assert s['primary'] == 'llama-3.3-70b-versatile' and s['how']['primary'] == 'override'
    fake.empty = {'openai/gpt-oss-120b'}
    reset_choice(shared=True)
    assert status()['fallback'] != 'openai/gpt-oss-120b'          # a model that answers with nothing is skipped


def test_the_choice_is_shared_so_a_second_process_never_rechecks(fake):
    """The site runs as two processes; once one has chosen, the other uses its
    choice — no catalogue listing, no test calls — for its first chat."""
    status()
    reset_choice()                                     # the other process, starting fresh
    fake.calls.clear()
    r = chat()
    assert r.json == {'text': 'reply from qwen/qwen3-32b'}
    assert [c[0] for c in fake.calls] == ['qwen/qwen3-32b']                       # only the chat itself


def test_pinned_models_answer_at_once_and_are_checked_behind_the_scenes(fake, monkeypatch):
    import ai
    reset_choice(shared=True)
    monkeypatch.setattr(ai, 'ENV_PRIMARY', 'llama-3.3-70b-versatile')
    checks = []
    monkeypatch.setattr(ai, 'check_soon', checks.append)
    assert chat().json == {'text': 'reply from llama-3.3-70b-versatile'}
    assert checks == ['first use'] and [c[0] for c in fake.calls] == ['llama-3.3-70b-versatile']


def test_starting_up_prepares_the_choice_in_the_background(fake, monkeypatch):
    import time
    import ai
    from app import app
    checks = []
    monkeypatch.setattr(ai, 'check_soon', checks.append)
    with app.app_context():
        reset_choice(shared=True)
        ai.prepare()                                   # nothing chosen anywhere: check
        assert checks == ['first use']
        ai.refresh('test')                             # chosen (and shared)…
        reset_choice()
        ai.prepare()                                   # …a new process adopts it without checking
        assert ai._state['primary'] == 'qwen/qwen3-32b' and checks == ['first use']
        ai._state['checked_at'] = ai._state['loaded_at'] = time.time() - 2 * ai.REFRESH_EVERY_SEC
        ai._save_shared()
        reset_choice()
        ai.prepare()                                   # a day old: checked again
        assert checks == ['first use', 'daily check']


def test_only_one_process_checks_at_a_time():
    from app import app, _ai_claim_check
    setup_db()
    with app.app_context():
        assert _ai_claim_check() is True
        assert _ai_claim_check() is False             # the other process, moments later
