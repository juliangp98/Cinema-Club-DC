"""Go easy on em dashes (docs/contributing.md, Writing): one where it reads
best, never two in one string members read: the backend's messages, the
bot's replies, embeds and /help. Docstrings don't count, nor does a dash at
either end of a string (a placeholder, like "— none —"), nor an AI's system
prompt (a *SYSTEM* name: what the model reads, not members). Film quotes are
quoted as said."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {'venv', 'instance', 'migrations', '__pycache__'}
VERBATIM = {ROOT / 'bot' / 'quotes.py'}


def inner(text):
    t = text.strip()
    return sum(1 for i, c in enumerate(t) if c == '—' and 0 < i < len(t) - 1)


def strings(path):
    tree = ast.parse(path.read_text())
    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            skip.add(id(body[0].value))                  # a docstring
        if isinstance(node, ast.Assign) and any('system' in getattr(t, 'id', '').lower() for t in node.targets):
            skip.update(id(n) for n in ast.walk(node.value))   # an AI's system prompt
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and id(node) not in skip:   # an f-string: its text parts together
            skip.update(id(v) for v in node.values)
            yield node.lineno, ''.join(v.value for v in node.values if isinstance(v, ast.Constant))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


def test_no_string_has_more_than_one_em_dash():
    found = []
    for top in ('backend', 'bot'):
        for path in (ROOT / top).rglob('*.py'):
            if SKIP & set(path.relative_to(ROOT).parts) or path in VERBATIM:
                continue
            found += [f'{path.relative_to(ROOT)}:{line}: {s.strip()[:80]}' for line, s in strings(path) if inner(s) > 1]
    assert found == []
