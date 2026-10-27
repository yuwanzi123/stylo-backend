#!/bin/bash
# Stylo Backend 启动脚本
# 用法: ./start.sh
# 作用: 激活 conda stylo 环境 + 启动 uvicorn（若已在跑则跳过）

set -e

PROJECT_DIR="/home/zzz/stylo/stylo-backend"
CONDA_ENV="stylo"
HOST="0.0.0.0"
PORT="8000"
LOG_FILE="$PROJECT_DIR/uvicorn.log"
PID_FILE="$PROJECT_DIR/uvicorn.pid"

cd "$PROJECT_DIR"

# 已在跑就不重复启动
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "uvicorn 已在跑 (PID $(cat "$PID_FILE"))，跳过启动"
    exit 0
fi
if pgrep -f "uvicorn main:app" >/dev/null 2>&1; then
    echo "检测到已有 uvicorn main:app 进程，跳过启动："
    pgrep -af "uvicorn main:app"
    exit 0
fi

echo "激活 conda 环境: $CONDA_ENV"
source /home/zzz/miniconda3/etc/profile.d/conda.sh
conda activate "$CONDA_ENV"

echo "启动 uvicorn ($HOST:$PORT)..."
nohup python3 -m uvicorn main:app --host "$HOST" --port "$PORT" \
    > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 2
if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "启动成功，PID $(cat "$PID_FILE")，日志: $LOG_FILE"
    TS_IP=$(tailscale ip -4 2>/dev/null | head -1)
    if [ -n "$TS_IP" ]; then
        echo "Tailscale 访问地址: http://$TS_IP:$PORT"
    fi
    echo "局域网访问地址: http://$(hostname -I | awk '{print $1}'):$PORT"
else
    echo "启动失败，查看日志: $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
