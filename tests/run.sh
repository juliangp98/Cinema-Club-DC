#!/bin/zsh
# The regression suite.
#   tests/run.sh                 everything
#   tests/run.sh -k discord      only tests whose names match
#   tests/run.sh backend/test_search.py
# Makes its own environment (tests/.venv) the first time.
cd ${0:A:h}
if [[ ! -x .venv/bin/pytest ]]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/pytest "$@"
