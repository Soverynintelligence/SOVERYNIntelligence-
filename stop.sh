#!/bin/bash
# SOVERYN shutdown — kills app.py and all aetheria_stream.py processes

echo "[SOVERYN] Stopping Aetheria consciousness loop..."
pkill -f "aetheria_stream.py" 2>/dev/null && echo "[SOVERYN] Aetheria loop stopped." || echo "[SOVERYN] Aetheria loop was not running."

echo "[SOVERYN] Stopping SOVERYN server..."
pkill -f "app.py" 2>/dev/null && echo "[SOVERYN] SOVERYN server stopped." || echo "[SOVERYN] SOVERYN server was not running."

sleep 1

# Confirm everything is down
REMAINING=$(ps aux | grep -E 'app\.py|aetheria_stream\.py' | grep -v grep | wc -l)
if [ "$REMAINING" -eq 0 ]; then
    echo "[SOVERYN] All processes stopped cleanly."
else
    echo "[SOVERYN] WARNING: $REMAINING process(es) still running — may need manual kill."
    ps aux | grep -E 'app\.py|aetheria_stream\.py' | grep -v grep
fi
