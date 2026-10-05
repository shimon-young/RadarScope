#!/usr/bin/env bash
# ============================================================
#  RadarScope - server stop script (Linux)
#  Usage: ./stop_server.sh [port]   (default 8125)
# ============================================================
set -uo pipefail
PORT="${1:-8125}"

stopped=0
if [ -f logs/server.pid ]; then
    PID=$(cat logs/server.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "[RADAR] stopping pid $PID (from logs/server.pid)"
        kill "$PID"
        stopped=1
    fi
    rm -f logs/server.pid
fi

# fallback: anything still listening on the port
for pid in $(ss -lptn "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u); do
    echo "[RADAR] stopping pid $pid on port $PORT"
    kill "$pid" 2>/dev/null || true
    stopped=1
done

[ "$stopped" = "0" ] && echo "[RADAR] no server is listening on port $PORT."
exit 0
