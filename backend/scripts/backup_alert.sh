#!/usr/bin/env bash
# backup_alert.sh — backup freshness and failure alerting for T05.4.
#
# This script does not access the database itself.  The backup job must call
# `record-success` only after its dump and integrity checks pass, or call
# `record-failure` on any error.  `check` detects missing/stale success markers
# so a silently disabled backup job is alerted as well.
set -u

BASE_DIR="${BACKUP_ALERT_BASE:-/workspace/hpc-perf-platform}"
STATE_DIR="${BACKUP_ALERT_STATE_DIR:-$BASE_DIR/backup-alert.state}"
ALERT_LOG="${BACKUP_ALERT_LOG:-$BASE_DIR/backup-alert.log}"
LOCK_FILE="${BACKUP_ALERT_LOCK:-$BASE_DIR/backup-alert.lock}"
MAX_AGE="${BACKUP_ALERT_MAX_AGE:-21600}"       # RPO gate: six hours.
CHECK_INTERVAL="${BACKUP_ALERT_INTERVAL:-300}"
ALERT_COOLDOWN="${BACKUP_ALERT_COOLDOWN:-3600}"
WEBHOOK_URL="${BACKUP_ALERT_WEBHOOK_URL:-}"
PROBE_TIMEOUT="${BACKUP_ALERT_PROBE_TIMEOUT:-5}"

SUCCESS_MARKER="$STATE_DIR/last_success_epoch"
SUCCESS_META="$STATE_DIR/last_success_meta"
SUCCESS_ARTIFACT="$STATE_DIR/last_success_artifact"
SUCCESS_SHA256="$STATE_DIR/last_success_sha256"
FAILURE_MARKER="$STATE_DIR/last_failure_epoch"
FAILURE_META="$STATE_DIR/last_failure_meta"
LAST_ALERT="$STATE_DIR/last_alert_epoch"

now() { date +%s; }
clock() { date '+%Y-%m-%d %H:%M:%S %Z'; }

# Compute the sha256 of a file as a clean hex digest. The tr strips any
# non-hex prefix some sha256sum builds emit for backslash Windows paths, so
# the stored value is a valid 64-char digest on both CentOS and Git Bash.
sha256_of() {
  sha256sum "$1" 2>/dev/null | awk '{print $1}' | tr -cd '0-9a-fA-F'
}

log_line() {
  mkdir -p "$STATE_DIR" "$(dirname "$ALERT_LOG")" || return 1
  printf '[%s] %s\n' "$(clock)" "$*" >> "$ALERT_LOG"
}

write_atomic() {
  local target="$1" value="$2" tmp
  mkdir -p "$STATE_DIR" || return 1
  tmp="${target}.tmp.$$"
  printf '%s\n' "$value" > "$tmp" || return 1
  mv -f "$tmp" "$target"
}

read_number() {
  local file="$1" value
  if [ -r "$file" ]; then
    value=$(head -n 1 "$file" 2>/dev/null || true)
    case "$value" in
      ''|*[!0-9]*) printf '0' ;;
      *) printf '%s' "$value" ;;
    esac
  else
    printf '0'
  fi
}

alert() {
  local event="$1" message="$2" current previous
  current=$(now)
  previous=$(read_number "$LAST_ALERT")
  if [ "$previous" -gt 0 ] && [ $((current - previous)) -lt "$ALERT_COOLDOWN" ]; then
    log_line "ALERT_SUPPRESSED event=$event cooldown=${ALERT_COOLDOWN}s message=$message"
    return 0
  fi
  write_atomic "$LAST_ALERT" "$current" || return 1
  log_line "ALERT event=$event message=$message"
  if [ -n "$WEBHOOK_URL" ]; then
    if ! curl -fsS --max-time "$PROBE_TIMEOUT" -X POST -H 'Content-Type: application/json' \
      --data "{\"event\":\"$event\",\"message\":\"$message\",\"epoch\":$current}" \
      "$WEBHOOK_URL" >/dev/null 2>&1; then
      log_line "WEBHOOK_ERROR event=$event url=$WEBHOOK_URL"
    else
      log_line "WEBHOOK_SENT event=$event"
    fi
  fi
}

record_success() {
  local artifact="${1:-}" epoch meta sum
  epoch=$(now)
  if [ -n "$artifact" ]; then
    if [ ! -e "$artifact" ]; then
      record_failure "success-marker rejected: artifact missing: $artifact"
      return 1
    fi
    if [ ! -s "$artifact" ]; then
      record_failure "success-marker rejected: artifact empty: $artifact"
      return 1
    fi
    if ! command -v sha256sum >/dev/null 2>&1; then
      record_failure "success-marker rejected: sha256sum unavailable to verify $artifact"
      return 1
    fi
    sum=$(sha256_of "$artifact")
    if [ -z "$sum" ]; then
      record_failure "success-marker rejected: sha256sum failed on $artifact"
      return 1
    fi
    write_atomic "$SUCCESS_ARTIFACT" "$artifact" || return 1
    write_atomic "$SUCCESS_SHA256" "$sum" || return 1
    meta="artifact=$artifact size=$(stat -c '%s' "$artifact" 2>/dev/null || wc -c < "$artifact") sha256=$sum"
  else
    meta="artifact=unspecified"
    # No single artifact is bound to this success; clear any stale artifact
    # binding so check_once will not re-verify a non-applicable product.
    write_atomic "$SUCCESS_ARTIFACT" "" || return 1
    write_atomic "$SUCCESS_SHA256" "" || return 1
  fi
  write_atomic "$SUCCESS_MARKER" "$epoch" || return 1
  write_atomic "$SUCCESS_META" "$meta" || return 1
  # A healthy success clears a previous failure marker and allows the next
  # independent failure to raise an alert immediately. Keep marker files in
  # place (rather than deleting them) so retention and audit tooling remain
  # stable across restarts.
  write_atomic "$FAILURE_MARKER" 0 || return 1
  write_atomic "$FAILURE_META" "cleared by success epoch=$epoch" || return 1
  write_atomic "$LAST_ALERT" 0 || return 1
  log_line "BACKUP_SUCCESS epoch=$epoch $meta"
}

record_failure() {
  local reason="${1:-backup command failed without a reason}" epoch
  epoch=$(now)
  write_atomic "$FAILURE_MARKER" "$epoch" || return 1
  write_atomic "$FAILURE_META" "$reason" || return 1
  log_line "BACKUP_FAILURE epoch=$epoch reason=$reason"
  alert "backup_failure" "$reason"
}

check_once() {
  local current success failure age reason art sum_expected sum_actual
  current=$(now)
  success=$(read_number "$SUCCESS_MARKER")
  failure=$(read_number "$FAILURE_MARKER")
  if [ "$failure" -gt "$success" ]; then
    reason=$(head -n 1 "$FAILURE_META" 2>/dev/null || printf 'backup job reported failure')
    alert "backup_failure" "$reason"
    return 2
  fi
  if [ "$success" -le 0 ]; then
    alert "backup_missing" "no successful backup marker has been recorded"
    return 2
  fi
  # Re-verify the recorded artifact against its stored sha256 so a removed or
  # tampered backup product is never reported healthy. This is defense-in-depth
  # beyond the caller's own integrity check at dump time.
  art=$(head -n 1 "$SUCCESS_ARTIFACT" 2>/dev/null || true)
  if [ -n "$art" ]; then
    sum_expected=$(head -n 1 "$SUCCESS_SHA256" 2>/dev/null || true)
    if [ ! -e "$art" ]; then
      reason="backup artifact missing: $art"
      alert "backup_missing" "$reason"
      return 2
    fi
    if [ -n "$sum_expected" ] && command -v sha256sum >/dev/null 2>&1; then
      sum_actual=$(sha256_of "$art")
      if [ "$sum_actual" != "$sum_expected" ]; then
        reason="backup artifact tampered: $art (expected ${sum_expected}, got ${sum_actual:-<none>})"
        alert "backup_tampered" "$reason"
        return 2
      fi
    fi
  fi
  age=$((current - success))
  if [ "$age" -gt "$MAX_AGE" ]; then
    alert "backup_stale" "last successful backup is ${age}s old (limit ${MAX_AGE}s)"
    return 2
  fi
  log_line "BACKUP_HEALTHY age=${age}s limit=${MAX_AGE}s"
  return 0
}

run_backup() {
  local command_text="${BACKUP_ALERT_COMMAND:-}" output rc
  if [ -z "$command_text" ]; then
    record_failure "BACKUP_ALERT_COMMAND is not configured"
    return 1
  fi
  output=$(bash -c "$command_text" 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    log_line "BACKUP_COMMAND_OK output=${output:-<empty>}"
    record_success
    return 0
  fi
  log_line "BACKUP_COMMAND_FAILED exit=$rc output=${output:-<empty>}"
  record_failure "backup command exit=$rc"
  return "$rc"
}

with_lock() {
  local mode="$1"
  mkdir -p "$(dirname "$LOCK_FILE")" || return 1
  # flock is available on the target CentOS image; fail closed if it is not.
  if ! command -v flock >/dev/null 2>&1; then
    log_line "ERROR flock is required for single-instance protection"
    return 1
  fi
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log_line "SKIP another backup-alert process holds the lock"
    return 0
  fi
  case "$mode" in
    check) check_once ;;
    run) run_backup ;;
    *) log_line "ERROR unsupported locked mode=$mode"; return 64 ;;
  esac
}

daemon_loop() {
  log_line "DAEMON_STARTED interval=${CHECK_INTERVAL}s max_age=${MAX_AGE}s"
  while :; do
    with_lock check || true
    sleep "$CHECK_INTERVAL"
  done
}

usage() {
  printf '%s\n' "usage: $0 {check|run|daemon|record-success [artifact]|record-failure [reason]}"
}

case "${1:-}" in
  check) with_lock check; exit $? ;;
  run) with_lock run; exit $? ;;
  daemon) daemon_loop; exit $? ;;
  record-success) record_success "${2:-}"; exit $? ;;
  record-failure) record_failure "${2:-backup command failed without a reason}"; exit $? ;;
  *) usage >&2; exit 64 ;;
esac
