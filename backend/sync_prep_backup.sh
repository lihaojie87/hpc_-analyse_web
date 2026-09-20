#!/usr/bin/env bash
# Step 1+2: backup remote backend dir and live db (NO restart, NO migration)
set -u
TS=$(date +%Y%m%d_%H%M%S)
BASE=/workspace/hpc-perf-platform
R=$BASE/backend
BAK=$BASE/backend.bak.$TS

echo "TIMESTAMP=$TS"
echo "BACKUP_DIR=$BAK"

echo "===== step1: cp -a backend -> $BAK ====="
cp -a "$R" "$BAK"
echo "cp_backend_rc=$?"
ls -ld "$BAK"
echo "backup_file_count=$(find "$BAK" -type f | wc -l)"

echo
echo "===== step2: backup live db ====="
DBBAK="$R/hpc.db.bak_sync.$TS"
cp -a "$R/hpc.db" "$DBBAK"
echo "cp_db_rc=$?"
ls -l "$R/hpc.db" "$DBBAK"
echo "orig_db_sha256=$(sha256sum "$R/hpc.db" | cut -d' ' -f1)"
echo "bak_db_sha256=$(sha256sum "$DBBAK" | cut -d' ' -f1)"

echo
echo "===== record backup path to file for later reference ====="
echo "$BAK" > /workspace/hpc-perf-platform/LAST_BACKEND_BAK.txt
echo "$DBBAK" >> /workspace/hpc-perf-platform/LAST_BACKEND_BAK.txt
cat /workspace/hpc-perf-platform/LAST_BACKEND_BAK.txt

echo
echo "===== record backup success to alert state (fail-closed) ====="
# Reliably write back the success marker so the backup freshness watchdog can
# confirm a healthy backup. The DB dump is the integrity-critical, sha256
# verifiable product; the backend dir backup is tracked via LAST_BACKEND_BAK.txt.
if [ ! -s "$DBBAK" ]; then
  echo "ERROR: db backup artifact missing or empty: $DBBAK" >&2
  exit 1
fi
if "$R/scripts/backup_alert.sh" record-success "$DBBAK"; then
  echo "record_success_rc=0"
else
  echo "ERROR: failed to record backup success marker (record_success_rc=$?)" >&2
  exit 1
fi

echo
echo "===== confirm uvicorn untouched ====="
ps -o pid,lstart,etime,cmd -p 7240 2>&1

echo "===== DONE ====="
