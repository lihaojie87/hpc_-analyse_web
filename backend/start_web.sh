#!/usr/bin/env bash
# =====================================================================
# start_web.sh — 幂等启动 /web Flask（SPA 静态 + 反向代理）
#
# ⚠️ 说明：/web/app.py 把 /api、/health、/docs、/openapi.json 反向代理到
#     http://127.0.0.1:8000（后端 uvicorn）。因此健康探针
#     http://127.0.0.1:80/health/live 会透传到后端；请先确保后端可用
#     （先跑 start_backend.sh）。
#
# 用法：sh /web/start_web.sh
# 幂等：重复执行会先停掉上一次的 /web/app.py（pidfile / pgrep / 端口侦测）再拉起。
# 不改动 /web/app.py 与 /web/dist。
# =====================================================================
set -u

WEB_DIR=/web
APP="$WEB_DIR/app.py"
PIDFILE="$WEB_DIR/web.pid"
LOG="$WEB_DIR/app.log"
PORT=80
HEALTH_URL="http://127.0.0.1:$PORT/health/live"
TIMEOUT=30

log() { echo "[start_web] $*"; }

port_pid() {
  local out p
  out=$( (ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ":$PORT[[:space:]]" )
  p=$(printf '%s\n' "$out" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)
  if [ -z "$p" ]; then
    p=$(printf '%s\n' "$out" | awk '{print $NF}' | sed -n 's#^\([0-9][0-9]*\)/.*#\1#p' | head -1)
  fi
  printf '%s' "$p"
}

# ---- 1) 停掉旧 Flask ----
STOPPED=""
CAND="$(cat "$PIDFILE" 2>/dev/null) $(pgrep -f "$APP" 2>/dev/null | tr '\n' ' ') $(port_pid)"
for pid in $CAND; do
  case "$pid" in ''|*[!0-9]*) continue;; esac
  if kill -0 "$pid" 2>/dev/null; then
    log "stopping old /web/app.py pid=$pid"
    kill "$pid" 2>/dev/null
    STOPPED="$STOPPED $pid"
  fi
done
for _ in $(seq 1 15); do
  alive=""
  for pid in $STOPPED; do kill -0 "$pid" 2>/dev/null && alive="$alive $pid"; done
  [ -z "$alive" ] && break
  sleep 1
done
for pid in $STOPPED; do
  if kill -0 "$pid" 2>/dev/null; then log "force kill pid=$pid"; kill -9 "$pid" 2>/dev/null; fi
done
rm -f "$PIDFILE"

# ---- 2) 启动 ----
[ -f "$APP" ] || { log "ERROR: $APP not found"; exit 90; }
: > "$LOG"
cd "$WEB_DIR" || { log "ERROR: cannot cd $WEB_DIR"; exit 90; }
setsid nohup python3 "$APP" >> "$LOG" 2>&1 < /dev/null &
sleep 1
NEWPID=$(pgrep -f "$APP" 2>/dev/null | head -1)
if [ -z "$NEWPID" ]; then
  log "FAIL: /web/app.py process not found after launch"
  log "----- tail -50 $LOG -----"; tail -50 "$LOG"; exit 1
fi
echo "$NEWPID" > "$PIDFILE"
log "launched /web/app.py pid=$NEWPID; waiting for $HEALTH_URL (timeout ${TIMEOUT}s)"

# ---- 3) 健康轮询 ----
START=$(date +%s)
CODE=""
for _ in $(seq 1 "$TIMEOUT"); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$HEALTH_URL" 2>/dev/null)
  [ "$CODE" = "200" ] && break
  if ! kill -0 "$NEWPID" 2>/dev/null; then log "process $NEWPID exited early"; break; fi
  sleep 1
done
ELAPSED=$(( $(date +%s) - START ))

if [ "$CODE" = "200" ]; then
  log "OK: /web/app.py pid=$NEWPID healthy in ${ELAPSED}s"
  exit 0
fi

log "FAIL: $HEALTH_URL not healthy after ${ELAPSED}s (last code=${CODE:-none})"
log "----- tail -50 $LOG -----"
tail -50 "$LOG"
exit 1
