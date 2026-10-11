"""R6a shared AI (backend/ai.py) against a fake Groq."""
from helpers import H, client, Checks, WORK


def test_ai():
    checks = Checks()
    check = checks.check
    import sys, json
    from app import app, db, migrate, BotSetting, ActivityEvent, INTERNAL_API_TOKEN
    import ai
    from fake_groq import Fake
    H = {'X-Internal-Token': INTERNAL_API_TOKEN}
    c = app.test_client()
    with app.app_context():
        db.create_all(); migrate()
    fake = Fake(['llama-3.3-70b-versatile', 'qwen/qwen3-32b', 'openai/gpt-oss-120b', 'meta-llama/llama-guard-4-12b', 'whisper-large-v3'])
    ai._client = fake
    def reset():
        ai._state.update(primary=None, fallback=None, how={}, available=[], checked_at=0.0); ai._extras.clear()
    def events():
        with app.app_context():
            return [json.loads(e.payload_json)['message'] for e in ActivityEvent.query.filter_by(kind='llm_switch')]

    print('--- choosing models ---')
    r = c.post('/api/internal/ai/chat', json={'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 50}, headers=H)
    s = c.get('/api/internal/ai/status', headers=H).json
    check('first use picks the preferred family, fallback from another', r.json == {'text': 'reply from qwen/qwen3-32b'}
          and s['primary'] == 'qwen/qwen3-32b' and ai.family(s['fallback']) != 'qwen', s)
    check('non-chat models are skipped', not any(m in s['available'] for m in ('meta-llama/llama-guard-4-12b', 'whisper-large-v3')))
    check('the owner hears about it once', len(events()) == 1 and 'primary `qwen/qwen3-32b`' in events()[0], events())
    reset(); c.get('/api/internal/ai/status', headers=H)
    check('…not again from a second server process making the same choice', len(events()) == 1)

    print('--- fallbacks ---')
    fake.limited = {'qwen/qwen3-32b'}
    r = c.post('/api/internal/ai/chat', json={'messages': [{'role': 'user', 'content': 'hi'}]}, headers=H)
    check('rate-limited primary → fallback answers', r.status_code == 200 and r.json['text'] == f"reply from {s['fallback']}", r.json)
    fake.limited = {'qwen/qwen3-32b', s['fallback']}
    r = c.post('/api/internal/ai/chat', json={'messages': [{'role': 'user', 'content': 'hi'}]}, headers=H)
    check('both limited → 429 with when it will be back', r.status_code == 429 and abs(r.json['retry_after'] - 672.5) < 0.01, r.json)
    fake.limited = set(); fake.gone = {'qwen/qwen3-32b'}
    r = c.post('/api/internal/ai/chat', json={'messages': [{'role': 'user', 'content': 'hi'}]}, headers=H)
    s2 = c.get('/api/internal/ai/status', headers=H).json
    check('a retired model is replaced on the spot', r.status_code == 200 and s2['primary'] != 'qwen/qwen3-32b' and s2['primary'], s2)
    check('…and the owner is told', len(events()) == 2)
    fake.gone = set()

    print('--- /llm overrides (saved settings) ---')
    with app.app_context():
        db.session.add(BotSetting(key='llm_primary', value='llama-3.3-70b-versatile')); db.session.commit()
    s3 = c.post('/api/internal/ai/refresh', json={'reason': 'test'}, headers=H).json
    check('a pinned model is used while Groq serves it', s3['primary'] == 'llama-3.3-70b-versatile' and s3['how']['primary'] == 'override', s3)
    fake.empty = {'openai/gpt-oss-120b'}
    reset(); s4 = c.get('/api/internal/ai/status', headers=H).json
    check('models that answer with nothing are skipped', s4['fallback'] != 'openai/gpt-oss-120b', s4)
    checks.done()
