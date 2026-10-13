#!/bin/zsh
# The regression suite.
#   tests/run.sh                 everything: backend + bot (pytest), then the site's components (vitest)
#   tests/run.sh -k discord      only Python tests whose names match
#   tests/run.sh backend/test_search.py
#   tests/run.sh frontend        only the component tests (frontend/tests)
# Makes its own environments (tests/.venv, frontend/node_modules) the first time.
cd ${0:A:h}

frontend() {
  ( cd ../frontend
    [[ -x node_modules/.bin/vitest ]] || npm ci --silent || exit 1
    node_modules/.bin/vitest run "$@" )
}

if [[ "$1" == frontend ]]; then shift; frontend "$@"; exit $?; fi
if [[ ! -x .venv/bin/pytest ]]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
.venv/bin/pytest "$@" || exit $?
(( $# )) || frontend
