#!/bin/bash
# Stylo Backend - /upload 和 /task/{task_id} 接口测试脚本
# 用法: ./test_async_upload.sh
# 请在 ~/stylo-backend 目录下运行，且确保 FastAPI 服务已经在另一个终端用
# uvicorn main:app --reload 跑起来了（默认监听 localhost:8000）

set -e

BASE_URL="http://localhost:8000"
VIDEO_FILE="uploads/20260611_163958.mp4"
IMAGE_FILE="uploads/20260627_152252.jpg"

echo "===================================================="
echo "测试 1: 上传视频，检查接口是否立即返回（不应该等待数分钟）"
echo "===================================================="

START_TIME=$(date +%s)
VIDEO_RESPONSE=$(curl -s -X POST "$BASE_URL/upload" -F "file=@$VIDEO_FILE")
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo "响应: $VIDEO_RESPONSE"
echo "耗时: ${ELAPSED} 秒"

if [ "$ELAPSED" -gt 10 ]; then
    echo "⚠️  警告: 响应耗时超过 10 秒，可能没有真正异步化，请检查 BackgroundTasks 是否生效"
else
    echo "✅ 响应速度正常，看起来是异步返回的"
fi

VIDEO_TASK_ID=$(echo "$VIDEO_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['task_id'])")
echo "视频任务 ID: $VIDEO_TASK_ID"
echo ""

echo "===================================================="
echo "测试 2: 立即查询视频任务状态（应该是 processing）"
echo "===================================================="
curl -s "$BASE_URL/task/$VIDEO_TASK_ID"
echo ""
echo ""

echo "===================================================="
echo "测试 3: 上传图片，检查接口是否立即返回"
echo "===================================================="

START_TIME=$(date +%s)
IMAGE_RESPONSE=$(curl -s -X POST "$BASE_URL/upload" -F "file=@$IMAGE_FILE")
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo "响应: $IMAGE_RESPONSE"
echo "耗时: ${ELAPSED} 秒"

if [ "$ELAPSED" -gt 10 ]; then
    echo "⚠️  警告: 响应耗时超过 10 秒"
else
    echo "✅ 响应速度正常"
fi

IMAGE_TASK_ID=$(echo "$IMAGE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['task_id'])")
echo "图片任务 ID: $IMAGE_TASK_ID"
echo ""

echo "===================================================="
echo "测试 4: 立即查询图片任务状态（应该是 processing）"
echo "===================================================="
curl -s "$BASE_URL/task/$IMAGE_TASK_ID"
echo ""
echo ""

echo "===================================================="
echo "测试 5: 等待并轮询视频任务，直到完成或失败（最多等 6 分钟）"
echo "===================================================="
for i in $(seq 1 36); do
    sleep 10
    STATUS_RESPONSE=$(curl -s "$BASE_URL/task/$VIDEO_TASK_ID")
    STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
    echo "[第 $i 次查询, 已等待 $((i*10)) 秒] 状态: $STATUS"

    if [ "$STATUS" == "completed" ]; then
        echo "✅ 视频任务处理完成！"
        echo "完整响应: $STATUS_RESPONSE"
        break
    elif [ "$STATUS" == "failed" ]; then
        echo "❌ 视频任务处理失败！"
        echo "完整响应: $STATUS_RESPONSE"
        break
    fi
done
echo ""

echo "===================================================="
echo "测试 6: 等待并轮询图片任务，直到完成或失败（最多等 3 分钟）"
echo "===================================================="
for i in $(seq 1 18); do
    sleep 10
    STATUS_RESPONSE=$(curl -s "$BASE_URL/task/$IMAGE_TASK_ID")
    STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
    echo "[第 $i 次查询, 已等待 $((i*10)) 秒] 状态: $STATUS"

    if [ "$STATUS" == "completed" ]; then
        echo "✅ 图片任务处理完成！"
        echo "完整响应: $STATUS_RESPONSE"
        break
    elif [ "$STATUS" == "failed" ]; then
        echo "❌ 图片任务处理失败！这条路径（单图输入）是这次改造新加的，如果失败，请检查 visual_pipeline.py 对图片输入的适配逻辑"
        echo "完整响应: $STATUS_RESPONSE"
        break
    fi
done
echo ""

echo "===================================================="
echo "测试 7: 查询一个不存在的 task_id，应该返回 404"
echo "===================================================="
curl -s -w "\nHTTP状态码: %{http_code}\n" "$BASE_URL/task/nonexistent_task_id_12345"
echo ""

echo "===================================================="
echo "所有测试完成"
echo "===================================================="
