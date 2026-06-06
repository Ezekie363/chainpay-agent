#!/bin/bash
set -e
cd "$(dirname "$0")"

# 杀掉占用 8000 端口的旧进程
pkill -f "uvicorn server.main" 2>/dev/null || true
sleep 0.5

# 后台启动数据服务端
PYTHONPATH=. .venv/bin/uvicorn server.main:app --port 8000 &
SERVER_PID=$!

# 等服务端就绪
sleep 2

echo ""

# 前台启动 Agent（Ctrl+C 退出时自动关服务端）
trap "kill $SERVER_PID 2>/dev/null" EXIT
PYTHONPATH=. .venv/bin/python main.py
