"""Discord gives the bot 3 seconds to answer a click, a form or a command; a
slow backend call before answering shows "This interaction failed" (that's how
an admin's Skip on a game post broke while a scrape held the database). So
every handler Discord calls answers first — defers, or replies — and only then
asks the backend: deferring gives it 15 minutes."""
import ast
import re
from pathlib import Path

BOT = Path(__file__).resolve().parents[2] / 'bot'
SOURCES = [BOT / 'bot.py', *sorted((BOT / 'features').glob('*.py'))]      # every command lives in a feature module

# A form has to open as the very first answer, so it can't wait behind a defer:
# /quote's Fix looks the quote up (one quick read) before opening its form.
OPENS_A_FORM = {'quote_edit'}


def _decorators(fn):
    return [ast.unparse(d) for d in fn.decorator_list]


def _wired(tree):
    """Names hooked up as callbacks: `select.callback = self.on_genres`."""
    return {ast.unparse(n.value).removeprefix('self.') for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == 'callback' for t in n.targets)
            and isinstance(n.value, (ast.Name, ast.Attribute))}


def _entry(fn, wired=()):
    """A handler Discord calls directly (not a command's autocomplete, which
    answers by returning its choices)."""
    decs = _decorators(fn)
    if any(re.match(r'\w+\.autocomplete\(', d) and not d.startswith('app_commands.') for d in decs):
        return False
    return (fn.name in ('callback', 'on_submit') or fn.name in wired
            or any('command(' in d or 'ui.button' in d or 'ui.select' in d for d in decs))


def _first(fn, test):
    return min((n.lineno for n in ast.walk(fn) if test(n)), default=None)


def _is_api_call(n):
    return (isinstance(n, ast.Await) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
            and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == 'api')


def _is_answer(n):
    return isinstance(n, ast.Attribute) and ast.unparse(n).startswith('interaction.response.')


def _helper_calls(fn, before):
    """Names of functions/methods `fn` awaits before line `before` (self.save(…), send_x(…))."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call) and (before is None or n.lineno < before):
            f = n.value.func
            name = f.attr if isinstance(f, ast.Attribute) and ast.unparse(f.value) in ('self', 'cls') else \
                f.id if isinstance(f, ast.Name) else None
            if name:
                out.append(name)
    return out


def _late(fn, defs, depth=0):
    """Line of a backend call reached before `fn` answers Discord (following
    helpers it hands the interaction to first), or None."""
    answer = _first(fn, _is_answer)
    api = _first(fn, _is_api_call)
    if api and (answer is None or answer > api):
        return api
    if depth < 2:
        for name in _helper_calls(fn, answer):
            for helper in defs.get(name, []):
                if helper is not fn and helper.name not in OPENS_A_FORM \
                        and 'interaction' in [a.arg for a in helper.args.args] and _late(helper, defs, depth + 1):
                    return _late(helper, defs, depth + 1)
    return None


def test_every_handler_answers_discord_before_asking_the_backend():
    tree = ast.Module(body=[n for src in SOURCES for n in ast.parse(src.read_text()).body], type_ignores=[])
    defs = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.AsyncFunctionDef):
            defs.setdefault(fn.name, []).append(fn)
    wired = _wired(tree)
    late = [f'{fn.name} (line {fn.lineno}): asks the backend at line {_late(fn, defs)} before answering'
            for fns in defs.values() for fn in fns
            if _entry(fn, wired) and fn.name not in OPENS_A_FORM and _late(fn, defs)]
    assert late == []
