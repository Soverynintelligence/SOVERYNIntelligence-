#!/bin/bash
# SOVERYN startup script
# Starts ComfyUI, SOVERYN server, and Aetheria consciousness loop

cd "$(dirname "$0")"

SOVERYN_LOG=/tmp/soveryn.log
AETHERIA_LOG=/tmp/aetheria_stream.log
PYTHON=/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python

# Start ComfyUI on Quadro pair (nvidia-smi 1,2), leave Blackwell (nvidia-smi 0) free for Aetheria
if curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo "[SOVERYN] ComfyUI already running — skipping."
else
    echo "[SOVERYN] Starting ComfyUI on port 8188..."
    CUDA_VISIBLE_DEVICES=1,2 /home/jon-deoliveira/miniconda3/envs/comfyui/bin/python \
        /home/jon-deoliveira/ComfyUI/main.py \
        --port 8188 \
        --listen 0.0.0.0 \
        --gpu-only \
        > /tmp/comfyui.log 2>&1 &
    COMFYUI_PID=$!
    echo "[SOVERYN] ComfyUI PID: $COMFYUI_PID"

    echo "[SOVERYN] Waiting for ComfyUI..."
    for i in $(seq 1 20); do
        sleep 2
        if curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
            echo "[SOVERYN] ComfyUI ready."
            break
        fi
    done
fi

# Start SOVERYN in background
echo "[SOVERYN] Starting SOVERYN on port 5000..."
CUDA_VISIBLE_DEVICES=0,1,2 $PYTHON app.py > $SOVERYN_LOG 2>&1 &
SOVERYN_PID=$!
echo "[SOVERYN] SOVERYN PID: $SOVERYN_PID"

# Wait for SOVERYN to be ready on port 5000
echo "[SOVERYN] Waiting for SOVERYN..."
for i in $(seq 1 60); do
    sleep 2
    if curl -s http://localhost:5000/status > /dev/null 2>&1; then
        echo "[SOVERYN] SOVERYN ready."
        break
    fi
    if ! kill -0 $SOVERYN_PID 2>/dev/null; then
        echo "[SOVERYN] SOVERYN process died — check $SOVERYN_LOG"
        exit 1
    fi
done

# Kill any stale Aetheria loops before starting a fresh one
pkill -f "aetheria_stream.py" 2>/dev/null
sleep 0.5

# Start Aetheria consciousness loop
echo "[SOVERYN] Starting Aetheria consciousness loop..."
$PYTHON aetheria_stream.py > $AETHERIA_LOG 2>&1 &
AETHERIA_PID=$!
echo "[SOVERYN] Aetheria loop PID: $AETHERIA_PID"

echo ""
echo "════════════════════════════════════════"
echo "  SOVERYN running   (PID $SOVERYN_PID)"
echo "  Aetheria loop     (PID $AETHERIA_PID)"
echo "  Logs:"
echo "    SOVERYN:  $SOVERYN_LOG"
echo "    Aetheria: $AETHERIA_LOG"
echo "    ComfyUI:  /tmp/comfyui.log"
echo "════════════════════════════════════════"
echo ""
echo "Following logs — Ctrl+C to detach (processes keep running)"
echo ""

# Tail both logs together
tail -f $SOVERYN_LOG $AETHERIA_LOG
