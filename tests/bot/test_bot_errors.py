"""One wording for failed calls to the site, whatever the command: the
server couldn't be reached; use the club's server first; you're read-only;
the command's own words for a missing thing; else the server's reason."""
import asyncio

from helpers import FakeInteraction, patch_bot_api, setup_db


def run(coro):
    return asyncio.run(coro)


def test_failure_wording():
    from api import ApiError
    setup_db()
    b = patch_bot_api()
    assert b.api_failure(ConnectionError('down')) == b.UNREACHABLE_MSG
    assert b.api_failure(ApiError(404, '{"error": "no_account"}')) == b.NO_ACCOUNT_MSG
    assert b.api_failure(ApiError(403, '{"error": "read_only"}')) == b.READ_ONLY_MSG
    assert b.api_failure(ApiError(404, '{}'), missing='Gone.') == 'Gone.'
    assert b.api_failure(ApiError(500, '{}'), 'Lookup failed ({status}).') == 'Lookup failed (500).'
    assert b.api_failure(ApiError(400, '{"error": "Pick one of the notes."}')) == 'Pick one of the notes.'
    assert b.api_failure(ApiError(502, 'not json')) == "That didn't work (502)."
    assert b.api_failure(ApiError(500, '{}'), 'No {title} here ({status}).') == 'No {title} here (500).'   # braces kept


def test_replies_go_where_the_conversation_is():
    from api import ApiError
    setup_db()
    b = patch_bot_api()
    fresh = FakeInteraction()
    run(b.reply_failure(fresh, ApiError(404, '{"error": "no_account"}'), '/x'))
    assert fresh.last == ('message', b.NO_ACCOUNT_MSG, {'ephemeral': True})          # first reply
    deferred = FakeInteraction()
    run(deferred.response.defer())
    run(b.reply_failure(deferred, OSError('down'), '/x', ephemeral=False))
    assert deferred.last == ('followup', b.UNREACHABLE_MSG, {'ephemeral': False})    # after a defer


def test_commands_use_it_when_the_server_is_down(monkeypatch):
    setup_db()
    b = patch_bot_api()

    async def down(*a, **k):
        raise ConnectionError('down')
    monkeypatch.setattr(b.api, 'get', down)
    for cmd in (b.kernels_cmd, b.play_cmd):
        it = FakeInteraction()
        run(cmd.callback(it))
        assert it.last == ('followup', b.UNREACHABLE_MSG, {'ephemeral': True})
