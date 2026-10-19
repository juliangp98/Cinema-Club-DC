"""✨ Ask on the Help page (7f): help_ai.py answers from the Help guide.

Club members only (guests, visitors and strangers who sign up keep the
keyword search): it
spends the club's shared AI allowance, which the chatbot, poll drafts and AI
search use too. Cached answers are free; fresh ones are ASKS_PER_HOUR each."""
import time

from app import _ai, ai_blocked, app, current_user, jsonify, request, require_auth

ASKS_PER_HOUR = 20
_asks = {}                  # user id -> recent fresh asks (per server process)


@app.route('/api/help/ask', methods=['POST'])
@require_auth
def help_ask():
    """{q} → {ai, topics: [topic ids], answer: text with guide links, or None}."""
    import help_ai
    user = current_user()
    blocked = ai_blocked(user)                     # club members only (SEO, Oct 2026)
    if blocked:
        return blocked
    q = str((request.json or {}).get('q') or '').strip()
    if len(help_ai.words(q)) < 2:
        return jsonify({'error': 'Ask a little more — a few words about what you want to do.'}), 400
    if hit := help_ai.cached(q[:300]):              # asked before (by anyone): free
        return jsonify(hit)
    now = time.monotonic()
    recent = [t for t in _asks.get(user.id, []) if now - t < 3600]
    if len(recent) >= ASKS_PER_HOUR:
        return jsonify({'ai': False, 'topics': help_ai.retrieve(q)[:3], 'answer': None,
                        'note': "That's a lot of questions this hour — here are the closest topics."})
    _ai()                                          # the shared AI, with its model-switch notices
    result = help_ai.ask(q[:300])
    if result['ai'] and not result['cached']:
        _asks[user.id] = recent + [now]
    if not result['ai']:
        result['note'] = "The AI isn't available right now — here are the closest topics."
    return jsonify(result)
