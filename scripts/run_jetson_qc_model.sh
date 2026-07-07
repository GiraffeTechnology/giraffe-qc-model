#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/giraffe/work/giraffe-qc-model
PY="$ROOT/.conda311/bin/python"
ALEMBIC="$ROOT/.conda311/bin/alembic"
UVICORN="$ROOT/.conda311/bin/uvicorn"
ENV_FILE="$ROOT/scripts/jetson_qc_model_env.sh"
RUN_DIR="$ROOT/artifacts/jetson_deploy"
PID_FILE="$RUN_DIR/uvicorn.pid"
LOG_FILE="$RUN_DIR/uvicorn.log"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

usage() {
  echo "Usage: $0 {migrate|start|stop|restart|status|logs|smoke}"
}

load_env() {
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  mkdir -p "$RUN_DIR" "$SAMPLE_STORE_DIR" "$CAPTURE_DIR" "$EDGE_CV_OUTPUT_DIR"
}

is_running() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

migrate() {
  load_env
  cd "$ROOT"
  "$ALEMBIC" upgrade head
}

start() {
  load_env
  cd "$ROOT"
  if is_running; then
    echo "already running pid=$(cat "$PID_FILE")"
    return 0
  fi
  "$ALEMBIC" upgrade head
  nohup "$UVICORN" src.api.main:app --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
  echo "$!" > "$PID_FILE"
  sleep 2
  if ! is_running; then
    echo "uvicorn failed to start; log follows"
    tail -n 80 "$LOG_FILE" || true
    exit 1
  fi
  echo "started pid=$(cat "$PID_FILE") url=http://127.0.0.1:$PORT"
}

stop() {
  if ! is_running; then
    echo "not running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid"
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "stopped"
      return 0
    fi
    sleep 0.2
  done
  echo "pid $pid still running"
  exit 1
}

status() {
  load_env
  if is_running; then
    echo "running pid=$(cat "$PID_FILE") url=http://127.0.0.1:$PORT"
  else
    echo "not running"
  fi
}

smoke() {
  load_env
  "$PY" - <<'PY'
import json
import urllib.request

checks = {}
for path in ["/health", "/", "/admin", "/admin/studio", "/admin/bundles", "/api/edge-cv/devices"]:
    url = "http://127.0.0.1:8000" + path
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read(120).decode("utf-8", "replace")
            checks[path] = {"status": r.status, "body_prefix": body}
    except Exception as exc:
        checks[path] = {"error": type(exc).__name__ + ": " + str(exc)}
print(json.dumps(checks, indent=2, sort_keys=True))
PY
}

cmd="${1:-}"
case "$cmd" in
  migrate) migrate ;;
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  logs) tail -n 120 "$LOG_FILE" ;;
  smoke) smoke ;;
  *) usage; exit 2 ;;
esac
