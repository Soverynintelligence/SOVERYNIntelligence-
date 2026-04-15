"""
eMeet Pixy Camera Control Tool
Controls pan, tilt, zoom via standard UVC v4l2 controls.

Ranges (from lsusb/v4l2-ctl):
  pan:  -540000 to 540000 arcseconds  (-150° to 150°)
  tilt: -324000 to 324000 arcseconds  (-90° to 90°)
  zoom: 100 to 150
"""
import subprocess
import os
from core.tool_base import Tool
from typing import Any, Dict


PIXY_VENDOR_ID = "328f"
DEGREES_TO_ARCSEC = 3600  # UVC uses 1/3600 degree units


def _find_pixy_device() -> str:
    """Find the /dev/video* device for the eMeet Pixy."""
    try:
        # Walk /sys/class/video4linux to match by USB vendor
        base = "/sys/class/video4linux"
        if os.path.exists(base):
            for dev in sorted(os.listdir(base)):
                dev_path = os.path.join(base, dev)
                # Resolve symlink and check parent USB path
                real = os.path.realpath(dev_path)
                if PIXY_VENDOR_ID in real:
                    return f"/dev/{dev}"
    except Exception:
        pass
    # Fallback: try video0 through video4
    for i in range(5):
        candidate = f"/dev/video{i}"
        if os.path.exists(candidate):
            try:
                result = subprocess.run(
                    ["v4l2-ctl", "--info", "-d", candidate],
                    capture_output=True, text=True, timeout=3
                )
                if "emeet" in result.stdout.lower() or "pixy" in result.stdout.lower():
                    return candidate
            except Exception:
                pass
    return "/dev/video0"  # last resort


def _v4l2_set(device: str, ctrl: str, value: int) -> str:
    """Run v4l2-ctl to set a control. Returns output or error."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", f"--set-ctrl={ctrl}={value}", "-d", device],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return "ok"
        return result.stderr.strip() or "error"
    except Exception as e:
        return str(e)


class PixyControlTool(Tool):

    @property
    def name(self) -> str:
        return "control_camera"

    @property
    def description(self) -> str:
        return (
            "Move the eMeet Pixy camera physically. "
            "action: 'pan' (left/right — MUST include value in degrees, -150 to 150), "
            "'tilt' (up/down — MUST include value in degrees, -90 to 90), "
            "'zoom' (100-150 — MUST include value), "
            "'center' (return to home position, no value needed), "
            "'look_at' (pan and tilt together — MUST provide both pan_deg and tilt_deg). "
            "Positive pan = right, negative = left. Positive tilt = up, negative = down. "
            "Example: to look right use action='pan' value=45. NEVER call pan or tilt without a value."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["pan", "tilt", "zoom", "center", "look_at"],
                    "description": "What to do"
                },
                "value": {
                    "type": "number",
                    "description": "Degrees for pan/tilt (-150 to 150 for pan, -90 to 90 for tilt), or zoom level (100-150)"
                },
                "pan_deg": {
                    "type": "number",
                    "description": "Pan degrees for look_at action"
                },
                "tilt_deg": {
                    "type": "number",
                    "description": "Tilt degrees for look_at action"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, value: float = None, pan_deg: float = 0, tilt_deg: float = 0) -> str:
        device = _find_pixy_device()

        if action in ("pan", "tilt", "zoom") and value is None:
            return f"Error: '{action}' requires a value parameter. Fix and retry once: TOOL_CALL: control_camera(action='{action}', value=45). Do not call request_perception until camera move succeeds."

        if value is None:
            value = 0

        if action == "center":
            r1 = _v4l2_set(device, "pan_absolute", 0)
            r2 = _v4l2_set(device, "tilt_absolute", 0)
            if r1 == "ok" and r2 == "ok":
                return "Camera centered."
            return f"Center result — pan: {r1}, tilt: {r2}"

        elif action == "pan":
            deg = max(-150, min(150, float(value)))
            arcsec = int(deg * DEGREES_TO_ARCSEC)
            r = _v4l2_set(device, "pan_absolute", arcsec)
            if r == "ok":
                direction = "right" if deg > 0 else "left" if deg < 0 else "center"
                return f"Panned {abs(deg):.0f}° {direction}."
            return f"Pan error: {r}"

        elif action == "tilt":
            deg = max(-90, min(90, float(value)))
            arcsec = int(deg * DEGREES_TO_ARCSEC)
            r = _v4l2_set(device, "tilt_absolute", arcsec)
            if r == "ok":
                direction = "up" if deg > 0 else "down" if deg < 0 else "center"
                return f"Tilted {abs(deg):.0f}° {direction}."
            return f"Tilt error: {r}"

        elif action == "zoom":
            level = max(100, min(150, int(value)))
            r = _v4l2_set(device, "zoom_absolute", level)
            if r == "ok":
                return f"Zoom set to {level}."
            return f"Zoom error: {r}"

        elif action == "look_at":
            p_deg = max(-150, min(150, float(pan_deg)))
            t_deg = max(-90, min(90, float(tilt_deg)))
            r1 = _v4l2_set(device, "pan_absolute", int(p_deg * DEGREES_TO_ARCSEC))
            r2 = _v4l2_set(device, "tilt_absolute", int(t_deg * DEGREES_TO_ARCSEC))
            if r1 == "ok" and r2 == "ok":
                return f"Camera moved to pan={p_deg:.0f}°, tilt={t_deg:.0f}°."
            return f"look_at result — pan: {r1}, tilt: {r2}"

        return f"Unknown action: {action}"
