#!/bin/bash
# Stylo Backend 停止脚本
# 用法: ./stop.sh

PROJECT_DIR="/home/zzz/stylo-backend"
PID_FILE="$PROJECT_DIR/uvicorn.pid"

cd "$PROJECT_DIR"

PID=""
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID="$(cat "$PID_FILE")"
elif pgrep -f "uvicorn main:app" >/dev/null 2>&1; then
    PID="$(pgrep -f "uvicorn main:app" | head -1)"
fi

if [ -z "$PID" ]; then
    echo "没有在跑的 uvicorn main:app 进程"
    rm -f "$PID_FILE"
    exit 0
fi

echo "停止 uvicorn (PID $PID)..."
kill "$PID"

for i in $(seq 1 10); do
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

if kill -0 "$PID" 2>/dev/null; then
    echo "进程未响应，强制 kill -9"
    kill -9 "$PID"
fi

rm -f "$PID_FILE"
echo "已停止"
