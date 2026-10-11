#!/bin/zsh
# Runs every test suite on a fresh copy of the base database.
#   tests/run.sh            all suites
#   tests/run.sh r7b        only suites whose name contains "r7b"
# Each suite prints PASS/FAIL lines; this summarizes them.
ROOT=${0:A:h:h}
WORK=$(mktemp -d -t cinemaclub-tests)
trap 'rm -rf $WORK' EXIT
setopt null_glob
cd $ROOT/backend
total_fail=0
for t in $ROOT/tests/backend/test_*.py; do
  name=${${t:t}%.py}; name=${name#test_}
  [[ -n "$1" && "$name" != *$1* ]] && continue
  cp $ROOT/tests/fixtures/base.db $WORK/$name.db
  out=$(DATABASE_URL=sqlite:///$WORK/$name.db INTERNAL_API_TOKEN=test-token GROQ_API_KEY=fake SMTP_EMAIL= \
        venv/bin/python $t 2>&1)
  pass=$(print -r -- "$out" | grep -c '^PASS'); fail=$(print -r -- "$out" | grep -c '^FAIL')
  print "$name: $pass pass, $fail fail"
  if [[ $fail -gt 0 || $pass -eq 0 || "$out" == *Traceback* ]]; then
    print -r -- "$out" | grep -E '^FAIL|Error|Traceback|line [0-9]+' | head -12
    total_fail=$((total_fail + 1))
  fi
done
exit $(( total_fail > 0 ))
