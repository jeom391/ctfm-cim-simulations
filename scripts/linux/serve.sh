#!/usr/bin/env bash
# Run the web app with the real AIHWKit engine (WSL/Linux): API + worker from the same
# engine venv and the same storage root. Open http://127.0.0.1:8000 from Windows or Linux.
#
#   bash scripts/linux/serve.sh start   # starts in the background, prints engine availability
#   bash scripts/linux/serve.sh status
#   bash scripts/linux/serve.sh stop    # stops both process groups; stored results are kept
#
# CTFM_ENGINE_ROOT (default /opt/ctfm-engines) holds the venv from setup_aihwkit.sh.
# CTFM_SERVE_ROOT (default $CTFM_ENGINE_ROOT/serve) holds storage/ and the logs.
set -u
ROOT=${CTFM_ENGINE_ROOT:-/opt/ctfm-engines}
RUN=${CTFM_SERVE_ROOT:-$ROOT/serve}
PY="$ROOT/aihwkit-venv/bin/python"
REPO=$(cd "$(dirname "$0")/../.." && pwd)
PORT=${PORT:-8000}

stop() {
  for name in api worker; do
    pid=$(cat "$RUN/$name.pid" 2>/dev/null) || continue
    kill -TERM -- "-$pid" 2>/dev/null
  done
  sleep 2
  for name in api worker; do
    pid=$(cat "$RUN/$name.pid" 2>/dev/null) || continue
    kill -KILL -- "-$pid" 2>/dev/null; rm -f "$RUN/$name.pid"
  done
  echo "stopped (storage kept in $RUN/storage)"
}

case "${1:-}" in
  start)
    [ -x "$PY" ] || { echo "missing $PY; run scripts/linux/setup_aihwkit.sh first"; exit 1; }
    [ -f "$REPO/apps/web/dist/index.html" ] || echo "warning: apps/web/dist missing; run npm run build in apps/web"
    [ -f "$RUN/api.pid" ] && kill -0 "$(cat "$RUN/api.pid")" 2>/dev/null && { echo "already running"; exit 0; }
    mkdir -p "$RUN/storage/cache"
    # Reuse an existing MNIST download (the loader verifies the published checksums).
    cp -n "$ROOT"/mnist-cache/*.gz "$RUN/storage/cache/" 2>/dev/null || true
    export CTFM_STORAGE_ROOT="$RUN/storage" PYTHONUNBUFFERED=1 PYTHONUTF8=1
    cd "$REPO"
    setsid nohup "$PY" -m uvicorn ctfm_api.app:app --host 127.0.0.1 --port "$PORT" > "$RUN/api.log" 2>&1 < /dev/null &
    echo $! > "$RUN/api.pid"
    setsid nohup "$PY" -m ctfm_worker > "$RUN/worker.log" 2>&1 < /dev/null &
    echo $! > "$RUN/worker.pid"
    for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$PORT/api/v1/capabilities" > "$RUN/capabilities.json" 2>/dev/null && break; sleep 1; done
    [ -s "$RUN/capabilities.json" ] || { echo "API did not start; see $RUN/api.log"; stop; exit 1; }
    "$PY" -c "import json,sys;c=json.load(open(sys.argv[1]));print({k:v['available'] for k,v in c['engines'].items()})" "$RUN/capabilities.json"
    echo "open http://127.0.0.1:$PORT  (logs: $RUN/api.log, $RUN/worker.log)" ;;
  status)
    for name in api worker; do pid=$(cat "$RUN/$name.pid" 2>/dev/null); if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then echo "$name running ($pid)"; else echo "$name stopped"; fi; done ;;
  stop) stop ;;
  *) echo "usage: $0 start|status|stop"; exit 2 ;;
esac
