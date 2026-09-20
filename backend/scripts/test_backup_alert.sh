#!/usr/bin/env bash
# Deterministic local tests for backup_alert.sh. No database or network required.
set -u
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SCRIPT="$ROOT/backup_alert.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export BACKUP_ALERT_BASE="$TMP"
export BACKUP_ALERT_STATE_DIR="$TMP/state"
export BACKUP_ALERT_LOG="$TMP/alert.log"
export BACKUP_ALERT_LOCK="$TMP/alert.lock"
export BACKUP_ALERT_MAX_AGE=2
export BACKUP_ALERT_COOLDOWN=0

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert_contains() { grep -F "$2" "$1" >/dev/null 2>&1 || fail "missing '$2' in $1"; }

bash -n "$SCRIPT" || fail 'syntax check'
if "$SCRIPT" check >/dev/null 2>&1; then fail 'missing marker unexpectedly healthy'; fi
assert_contains "$TMP/alert.log" 'event=backup_missing'

printf 'test dump\n' > "$TMP/dump"
"$SCRIPT" record-success "$TMP/dump" || fail 'record-success failed'
"$SCRIPT" check || fail 'fresh marker not healthy'
sleep 3
if "$SCRIPT" check >/dev/null 2>&1; then fail 'stale marker unexpectedly healthy'; fi
assert_contains "$TMP/alert.log" 'event=backup_stale'

"$SCRIPT" record-failure 'simulated pg_dump failure' || fail 'record-failure should log and return success'
assert_contains "$TMP/alert.log" 'event=backup_failure'

export BACKUP_ALERT_COMMAND='printf generated > "$BACKUP_ALERT_BASE/generated.dump"'
"$SCRIPT" run || fail 'run command failed'
[ -s "$TMP/generated.dump" ] || fail 'run did not generate artifact'
"$SCRIPT" check || fail 'run success marker not healthy'

printf 'PASS: backup alert script tests\n'
