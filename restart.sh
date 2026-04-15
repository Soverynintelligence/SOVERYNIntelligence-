#!/bin/bash
# SOVERYN full restart — kills app.py and aetheria_stream.py, then relaunches both

cd "$(dirname "$0")"

echo "[RESTART] Stopping SOVERYN..."
pkill -f "python app.py" 2>/dev/null
pkill -f "aetheria_stream.py" 2>/dev/null
sleep 2

echo "[RESTART] Starting consciousness loop in background..."
CUDA_VISIBLE_DEVICES=2,0,1 /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python \
    aetheria_stream.py > /tmp/aetheria_loop.log 2>&1 &
echo "[RESTART] Loop PID: $!"

echo "[RESTART] Starting SOVERYN on port 5000..."
CUDA_VISIBLE_DEVICES=2,0,1 /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python app.py
