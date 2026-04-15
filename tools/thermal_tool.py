"""
Thermal Tool — GPU temperature monitoring and fan speed control.
Tinker uses this to check temps and boost fans when the rig runs hot.

Fan control requires nvidia-settings and a running X display.
Temperature reads use nvidia-smi (no display needed).
"""
import subprocess
from core.tool_base import Tool
from typing import Any, Dict


# Safety limits
FAN_MIN = 30    # never set below 30% (prevents coil whine / bearing stress at near-0)
FAN_MAX = 100
TEMP_WARNING  = 80   # °C — log warning
TEMP_CRITICAL = 88   # °C — auto-boost recommendation


def _run(cmd: list, timeout: int = 5) -> tuple[str, str]:
    """Run a shell command, return (stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return "", "Command timed out"
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return "", str(e)


def _get_temps() -> list[dict]:
    """Read all GPU temps via nvidia-smi."""
    out, err = _run([
        'nvidia-smi',
        '--query-gpu=index,name,temperature.gpu,fan.speed,power.draw,memory.used,memory.total',
        '--format=csv,noheader,nounits'
    ])
    if not out:
        return [{"error": err or "nvidia-smi unavailable"}]
    gpus = []
    for line in out.split('\n'):
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 7:
            gpus.append({
                "index":      parts[0],
                "name":       parts[1],
                "temp_c":     int(parts[2]) if parts[2].isdigit() else None,
                "fan_pct":    parts[3],
                "power_w":    parts[4],
                "vram_used":  parts[5],
                "vram_total": parts[6],
            })
    return gpus


def _set_fan(gpu_index: int, speed_pct: int) -> str:
    """Set fan speed for a GPU. Requires nvidia-settings + X display."""
    speed_pct = max(FAN_MIN, min(FAN_MAX, speed_pct))
    import os
    env = os.environ.copy()
    if 'DISPLAY' not in env:
        env['DISPLAY'] = ':0'

    # Enable manual fan control
    _, err = _run(['nvidia-settings',
                   '-a', f'[gpu:{gpu_index}]/GPUFanControlState=1'], timeout=5)
    if err and 'assigned' not in err.lower():
        return f"Could not enable fan control on GPU {gpu_index}: {err}"

    # Find fan indices for this GPU (usually matches GPU index but can differ)
    out, err = _run(['nvidia-settings',
                     '-q', f'[fan:{gpu_index}]/GPUTargetFanSpeed'], timeout=5)

    # Set the speed
    _, err2 = _run(['nvidia-settings',
                    '-a', f'[fan:{gpu_index}]/GPUTargetFanSpeed={speed_pct}'], timeout=5)
    if err2 and 'assigned' not in err2.lower():
        return f"Fan set failed on GPU {gpu_index}: {err2}"

    return f"GPU {gpu_index} fan set to {speed_pct}%"


def _reset_fan(gpu_index: int) -> str:
    """Return GPU fan to automatic control."""
    _, err = _run(['nvidia-settings',
                   '-a', f'[gpu:{gpu_index}]/GPUFanControlState=0'], timeout=5)
    if err and 'assigned' not in err.lower():
        return f"Could not reset fan on GPU {gpu_index}: {err}"
    return f"GPU {gpu_index} fan returned to auto"


class ThermalTool(Tool):
    """Monitor GPU temperatures and control fan speeds."""

    @property
    def name(self) -> str:
        return "thermal"

    @property
    def description(self) -> str:
        return (
            "Monitor GPU temperatures and control fan speeds. "
            "Actions: 'status' — read all GPU temps and fan speeds; "
            "'set_fan' — set fan speed % on a specific GPU (requires gpu_index and speed_pct); "
            "'boost_all' — set all GPU fans to speed_pct (default 80%); "
            "'auto' — return all fans to automatic control."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "set_fan", "boost_all", "auto"],
                    "description": "What to do"
                },
                "gpu_index": {
                    "type": "integer",
                    "description": "GPU index (0, 1, 2) — only for set_fan"
                },
                "speed_pct": {
                    "type": "integer",
                    "description": "Fan speed percentage (30-100) — for set_fan and boost_all"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str = "status",
                      gpu_index: int = None, speed_pct: int = 80) -> str:
        if action == "status":
            gpus = _get_temps()
            if not gpus or "error" in gpus[0]:
                return f"[THERMAL] Error: {gpus[0].get('error', 'unknown')}"
            lines = ["[THERMAL STATUS]"]
            for g in gpus:
                temp = g.get("temp_c")
                flag = ""
                if temp and temp >= TEMP_CRITICAL:
                    flag = " ⚠️ CRITICAL"
                elif temp and temp >= TEMP_WARNING:
                    flag = " ⚠️ WARM"
                lines.append(
                    f"  GPU {g['index']} ({g['name']}): "
                    f"{temp}°C | Fan: {g['fan_pct']}% | "
                    f"Power: {g['power_w']}W | "
                    f"VRAM: {g['vram_used']}/{g['vram_total']}MB{flag}"
                )
            return "\n".join(lines)

        elif action == "set_fan":
            if gpu_index is None:
                return "[THERMAL] set_fan requires gpu_index"
            result = _set_fan(gpu_index, speed_pct)
            return f"[THERMAL] {result}"

        elif action == "boost_all":
            gpus = _get_temps()
            results = []
            for g in gpus:
                if "error" not in g:
                    results.append(_set_fan(int(g["index"]), speed_pct))
            return "[THERMAL] " + " | ".join(results) if results else "[THERMAL] No GPUs found"

        elif action == "auto":
            gpus = _get_temps()
            results = []
            for g in gpus:
                if "error" not in g:
                    results.append(_reset_fan(int(g["index"])))
            return "[THERMAL] " + " | ".join(results) if results else "[THERMAL] No GPUs found"

        return f"[THERMAL] Unknown action: {action}"
