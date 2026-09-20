#!/usr/bin/env bash
# =====================================================================
# start_backend.sh — 幂等启动 FastAPI/uvicorn 生产后端
#
# ⚠️ 必须先注入 /workspace/hpc-perf-platform/.env：
#     app/db/session.py 在【模块导入期】就执行 create_async_engine(_url())，
#     需要 settings(HPC_JWT_SECRET / HPC_DATABASE_URL ...)。若缺 .env，
#     uvicorn 会在 import 阶段抛 ValidationError 立即崩溃（历史上因此导致
#     过约 100 秒服务中断）。本脚本 source 该 .env 后再启动，并轮询健康
#     检查；失败时打印日志尾部并以非 0 退出，避免“静默坏部署”。
#
# 用法：sh /workspace/hpc-perf-platform/start_backend.sh
# 幂等：重复执行会先停掉上一次的 uvicorn（pidfile / pgrep / 端口侦测）再拉起。
# =====================================================================
set -u

BASE=/workspace/hpc-perf-platform
BACKEND_DIR="$BASE/backend"
ENV_FILE="$BASE/.env"
PIDFILE="$BASE/uvicorn.pid"
LOG="$BACKEND_DIR/uvicorn.log"
HOST=127.0.0.1
PORT=8000
HEALTH_URL="http://$HOST:$PORT/health/live"
TIMEOUT=30

log() { echo "[start_backend] $*"; }

# 通过监听端口反查 PID（ss 优先，netstat 兜底）
port_pid() {
  local out p
  out=$( (ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ":$PORT[[:space:]]" )
  p=$(printf '%s\n' "$out" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)
  if [ -z "$p" ]; then
    p=$(printf '%s\n' "$out" | awk '{print $NF}' | sed -n 's#^\([0-9][0-9]*\)/.*#\1#p' | head -1)
  fi
  printf '%s' "$p"
}

# ---- 1) 停掉旧 uvicorn（不硬编码 PID）----
STOPPED=""
CAND="$(cat "$PIDFILE" 2>/dev/null) $(pgrep -f 'uvicorn app.main:app' 2>/dev/null | tr '\n' ' ') $(port_pid)"
for pid in $CAND; do
  case "$pid" in ''|*[!0-9]*) continue;; esac
  if kill -0 "$pid" 2>/dev/null; then
    log "stopping old uvicorn pid=$pid"
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

# ---- 2) 注入 .env ----
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
  log "loaded env from $ENV_FILE (HPC_ENV=${HPC_ENV:-unset})"
else
  log "WARNING: $ENV_FILE not found — backend import will likely fail (missing settings)"
fi

# ---- 3) 启动 ----
cd "$BACKEND_DIR" || { log "ERROR: cannot cd $BACKEND_DIR"; exit 90; }
: > "$LOG"
setsid nohup .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" >> "$LOG" 2>&1 < /dev/null &
sleep 1
NEWPID=$(pgrep -f 'uvicorn app.main:app' 2>/dev/null | head -1)
if [ -z "$NEWPID" ]; then
  log "FAIL: uvicorn process not found after launch"
  log "----- tail -50 $LOG -----"; tail -50 "$LOG"; exit 1
fi
echo "$NEWPID" > "$PIDFILE"
log "launched uvicorn pid=$NEWPID; waiting for $HEALTH_URL (timeout ${TIMEOUT}s)"

# ---- 4) 健康轮询 ----
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
  log "OK: uvicorn pid=$NEWPID healthy in ${ELAPSED}s"
  exit 0
fi

log "FAIL: $HEALTH_URL not healthy after ${ELAPSED}s (last code=${CODE:-none})"
log "----- tail -50 $LOG -----"
tail -50 "$LOG"
exit 1
