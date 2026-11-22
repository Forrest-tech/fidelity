#!/bin/bash
# Smoke test of a running Fidelity container: health, first-run admin, sign-in, an admin page.
#   deploy/docker/smoke_test.sh http://127.0.0.1:8000 [container]
# Sign-in has a bot check (ALTCHA proof-of-work): it is solved with the altcha library inside the container.
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
CTR="${2:-}"
solve() {
  local SOLVER='import sys,json,altcha; c=altcha.Challenge.from_dict(json.load(sys.stdin)); print(altcha.Payload(c, altcha.solve_challenge(c)).to_base64())'
  if [ -n "$CTR" ]; then curl -fsS "$BASE/api/v1/auth/challenge" | docker exec -i "$CTR" python -c "$SOLVER"
  else curl -fsS "$BASE/api/v1/auth/challenge" | python3 -c "$SOLVER"; fi
}
for i in $(seq 1 60); do curl -fsS "$BASE/api/v1/health" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$BASE/api/v1/health" >/dev/null
echo "health ok"
curl -fsS "$BASE/api/v1/setup" | grep -q '"needs_setup":true'
curl -fsS -X POST "$BASE/api/v1/setup" -H 'Content-Type: application/json' \
  -d '{"email":"smoke-admin@example.com","password":"smoke-test-password","altcha":"'"$(solve)"'"}' >/dev/null
curl -fsS "$BASE/api/v1/setup" | grep -q '"needs_setup":false'
echo "first administrator created; setup locked"
JAR="$(mktemp)"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE/api/v1/auth/login" -d 'username=smoke-admin@example.com&password=smoke-test-password')
[ "$code" = "400" ] || { echo "sign-in without the bot check was not refused ($code)"; exit 1; }
curl -fsS -c "$JAR" -X POST "$BASE/api/v1/auth/login" --data-urlencode 'username=smoke-admin@example.com' --data-urlencode 'password=smoke-test-password' --data-urlencode "altcha=$(solve)" >/dev/null
curl -fsS -b "$JAR" "$BASE/api/v1/me" | grep -q '"role":"admin"'
curl -fsS -b "$JAR" "$BASE/api/v1/storage/dropbox" | grep -q '"connected":false'
curl -fsS "$BASE/" | grep -qi '<div id="root"'
echo "sign-in, admin page and web interface ok"
