#!/usr/bin/env bash
# ============================================================
#  RadarScope - server start script (Linux)
#
#  Usage:
#    ./start_server.sh             LAN mode (default)  0.0.0.0:8125
#    ./start_server.sh lan 9000    LAN mode, custom port
#    ./start_server.sh local       local mode  127.0.0.1:8125, auto-open browser
#    ./start_server.sh local 9000  local mode, custom port
#
#  Python resolution order:
#    1) $RADAR_PYTHON
#    2) <repo>/env/bin/python       (packaged conda-pack layout)
#    3) python3 on PATH
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-lan}"
PORT="${2:-8125}"

if [ "$MODE" = "local" ]; then
    HOST="127.0.0.1"
    OPEN="--open"
    MODE_DESC="单机模式"
else
    HOST="0.0.0.0"
    OPEN=""
    MODE_DESC="局域网模式"
fi

if [ -n "${RADAR_PYTHON:-}" ]; then PY="$RADAR_PYTHON"
elif [ -x "env/bin/python" ]; then PY="$PWD/env/bin/python"
else
    echo "[ERROR] Python environment not found at $PWD/env/bin/python" >&2
    echo "        This package ships without a Python environment." >&2
    echo "        First-time setup: run setup_env.sh in the package root," >&2
    echo "        or set RADAR_PYTHON to an existing interpreter." >&2
    exit 1
fi

mkdir -p logs

# --- 权重状态检查（ckpt 在仓库根） ---
CKPT_MAIN="缺失"; CKPT_PLUS="未装"
[ -f "../ckpt/checkpoint_radar_pretrain.pth" ] && CKPT_MAIN="就绪"
[ -f "../ckpt/checkpoint_radar_plus_finetuned_on_merlin.pth" ] && CKPT_PLUS="就绪"

# --- 探测本机局域网 IP ---
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$LOCAL_IP" ] && LOCAL_IP="<本机IP>"

echo "============================================================"
echo "  RadarScope v2.0.0 - 服务启动"
echo "============================================================"
echo "  模式        : $MODE  [ $MODE_DESC ]"
echo "  绑定地址    : $HOST:$PORT"
echo "  访问地址    : http://127.0.0.1:$PORT/"
if [ "$MODE" = "lan" ]; then
    echo "  局域网访问  : http://$LOCAL_IP:$PORT/  [ 网内设备浏览器直接访问 ]"
fi
echo "  Python      : $PY"
echo "  主模型权重  : $CKPT_MAIN"
echo "  微调版权重  : $CKPT_PLUS"
echo "  日志文件    : $PWD/logs/server.log"
echo "------------------------------------------------------------"
if [ "$MODE" = "lan" ]; then
    echo "  [注意] 局域网模式无鉴权，仅限可信网络内使用！"
fi
echo ""
echo "  [RADAR] 正在启动后台服务，模型加载约需 10-30 秒..."

nohup "$PY" service.py --host "$HOST" --port "$PORT" $OPEN >> logs/server.log 2>&1 &
echo $! > logs/server.pid
echo "  [RADAR] 服务已启动 (PID $(cat logs/server.pid))"
echo "  [RADAR] 停止服务: ./stop_server.sh   查看实时日志: tail -f logs/server.log"
echo ""
