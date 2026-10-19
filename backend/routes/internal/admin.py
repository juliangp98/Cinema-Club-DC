"""The bot's admin settings: the AI models (/llm) and the settings the bot keeps here.
"""
from app import BotSetting, DiscordServer, _ai, app, db, jsonify, request
from routes.internal.common import require_internal


# Keys the bot may store; anything else is rejected.
BOT_SETTING_KEYS = {'llm_primary', 'llm_fallback'}


@app.route('/api/internal/ai/chat', methods=['POST'])
@require_internal
def internal_ai_chat():
    """The bot's chatbot: {messages, max_tokens} → {text}; 429 with retry_after
    when the daily token cap is spent; 503 when no model can answer."""
    ai = _ai()
    data = request.json or {}
    try:
        text = ai.chat(data.get('messages') or [], max_tokens=min(int(data.get('max_tokens') or 300), 2000))
    except ai.RateLimited as e:
        return jsonify({'error': 'rate_limited', 'retry_after': e.retry_after_sec}), 429
    except ai.Unavailable as e:
        return jsonify({'error': 'unavailable', 'detail': str(e)}), 503
    except Exception as e:
        print(f'ai chat failed: {e}')
        return jsonify({'error': 'failed', 'detail': str(e)[:200]}), 502
    return jsonify({'text': text})


@app.route('/api/internal/ai/status')
@require_internal
def internal_ai_status():
    ai = _ai()
    s = ai.status()
    if not s['primary']:
        s = ai.refresh('first use')
    return jsonify(s)


@app.route('/api/internal/ai/refresh', methods=['POST'])
@require_internal
def internal_ai_refresh():
    """Re-pick models now (e.g. after /llm changes an override)."""
    return jsonify(_ai().refresh((request.json or {}).get('reason') or 'requested'))


@app.route('/api/internal/settings')
@require_internal
def internal_settings():
    keys = [k for k in (request.args.get('keys') or '').split(',') if k in BOT_SETTING_KEYS]
    rows = {r.key: r.value for r in BotSetting.query.filter(BotSetting.key.in_(keys)).all()} if keys else {}
    return jsonify({k: rows.get(k, '') for k in keys})


@app.route('/api/internal/settings', methods=['POST'])
@require_internal
def internal_settings_update():
    data = request.json or {}
    key, value = data.get('key'), (data.get('value') or '').strip()[:200]
    if key not in BOT_SETTING_KEYS:
        return jsonify({'error': 'Unknown setting'}), 400
    # The AI is the whole site's: only the home server changes it (/llm).
    server = db.session.get(DiscordServer, str(data.get('guild_id') or ''))
    if data.get('guild_id') and not (server and server.home):
        return jsonify({'error': 'home_only'}), 403
    row = db.session.get(BotSetting, key) or BotSetting(key=key)
    row.value = value
    db.session.add(row)
    db.session.commit()
    return jsonify({key: value})
