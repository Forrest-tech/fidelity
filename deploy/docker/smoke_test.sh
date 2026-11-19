#!/bin/bash
# Smoke test of a running Fidelity container: health, first-run admin, sign-in, an admin page.
#   deploy/docker/smoke_test.sh http://127.0.0.1:8000
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
for i in $(seq 1 60); do curl -fsS "$BASE/api/v1/health" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$BASE/api/v1/health" >/dev/null
echo "health ok"
curl -fsS "$BASE/api/v1/setup" | grep -q '"needs_setup":true'
curl -fsS -X POST "$BASE/api/v1/setup" -H 'Content-Type: application/json' \
  -d '{"email":"smoke-admin@example.com","password":"smoke-test-password"}' >/dev/null
curl -fsS "$BASE/api/v1/setup" | grep -q '"needs_setup":false'
echo "first administrator created; setup locked"
JAR="$(mktemp)"
curl -fsS -c "$JAR" -X POST "$BASE/api/v1/auth/login" -d 'username=smoke-admin@example.com&password=smoke-test-password' >/dev/null
curl -fsS -b "$JAR" "$BASE/api/v1/me" | grep -q '"role":"admin"'
curl -fsS -b "$JAR" "$BASE/api/v1/storage/dropbox" | grep -q '"connected":false'
curl -fsS "$BASE/" | grep -qi '<div id="root"'
echo "sign-in, admin page and web interface ok"
