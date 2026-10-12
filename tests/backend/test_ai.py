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


def reset_choice():
    """As if a second server process started (no models chosen yet)."""
    import ai
    ai._state.update(primary=None, fallback=None, how={}, available=[], checked_at=0.0)
    ai._extras.clear()


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
    reset_choice()
    assert status()['fallback'] != 'openai/gpt-oss-120b'          # a model that answers with nothing is skipped
