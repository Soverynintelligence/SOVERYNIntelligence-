"""
Image Generation Tool — uses Google Imagen 3 via the Gemini API.
Falls back to ComfyUI if the API key is not set.
"""
import os
import base64
import time
import urllib.request
import urllib.parse
import json
from pathlib import Path
from core.tool_base import Tool
from typing import Any, Dict

COMFYUI_URL = "http://127.0.0.1:8188"
COMFYUI_CHECKPOINTS = Path("/home/jon-deoliveira/ComfyUI/models/checkpoints")
OUTPUT_DIR = Path("/home/jon-deoliveira/soveryn_complete/static/generated")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Preference order — first match wins
_CHECKPOINT_PREFERENCE = [
    "juggernaut",
    "realvis",
    "dreamshaper",
    "sdxl_lightning",
    "sd_xl_refiner",
    "sd_xl_base",
    "v1-5",
]

def _best_checkpoint() -> str:
    """Return the best available checkpoint filename."""
    try:
        available = [
            f.name for f in COMFYUI_CHECKPOINTS.iterdir()
            if f.suffix in ('.safetensors', '.ckpt') and f.name != 'put_checkpoints_here'
        ]
    except Exception:
        return "sd_xl_base_1.0.safetensors"

    for pref in _CHECKPOINT_PREFERENCE:
        for name in available:
            if pref.lower() in name.lower():
                print(f"[ImageGen] Selected checkpoint: {name}")
                return name

    return available[0] if available else "sd_xl_base_1.0.safetensors"


def _imagen3(prompt: str) -> str:
    """Generate image via Google Imagen 3. Returns local URL or error string."""
    api_key = os.getenv("GOOGLE_AI_API_KEY", "")
    if not api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={api_key}"
    payload = json.dumps({
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1}
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        img_bytes = base64.b64decode(b64)
        filename = f"imagen_{int(time.time())}.png"
        out_path = OUTPUT_DIR / filename
        out_path.write_bytes(img_bytes)
        return f"/static/generated/{filename}"
    except Exception as e:
        print(f"[ImageGen] Imagen 3 error: {e}")
        return None


def _comfyui(prompt: str, negative_prompt: str, width: int, height: int, steps: int) -> str:
    """Fallback: generate via local ComfyUI."""
    import uuid
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=3)
    except Exception:
        return "Image generation unavailable — ComfyUI is not running and Imagen API failed."

    ckpt = _best_checkpoint()
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {
            "text": negative_prompt, "clip": ["1", 1]
        }},
        "4": {"class_type": "EmptyLatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1
        }},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": int(time.time()) % 2**32,
            "steps": steps, "cfg": 6.5, "sampler_name": "dpmpp_2m_sde",
            "scheduler": "karras", "denoise": 1.0
        }},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "soveryn"}}
    }
    client_id = str(uuid.uuid4())
    payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{COMFYUI_URL}/prompt", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        prompt_id = json.loads(r.read())["prompt_id"]

    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(2)
        with urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=5) as r:
            history = json.loads(r.read())
        if prompt_id in history:
            for node_output in history[prompt_id].get("outputs", {}).values():
                images = node_output.get("images", [])
                if images:
                    img = images[0]
                    # Download image from ComfyUI and save to static/generated/
                    # so the browser can load it without reaching localhost:8188
                    view_url = (
                        f"{COMFYUI_URL}/view?filename={urllib.parse.quote(img['filename'])}"
                        f"&subfolder={img.get('subfolder','')}&type={img.get('type','output')}"
                    )
                    try:
                        filename = f"comfy_{int(time.time())}.png"
                        out_path = OUTPUT_DIR / filename
                        with urllib.request.urlopen(view_url, timeout=30) as img_r:
                            out_path.write_bytes(img_r.read())
                        return f"/static/generated/{filename}"
                    except Exception as e:
                        print(f"[ImageGen] Failed to copy ComfyUI image: {e}")
                        return view_url  # fallback to direct URL
    return "Image generation timed out."


class ImageGenTool(Tool):

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Generate an image from a text prompt. "
            "Only use when explicitly asked to generate, create, or show an image. "
            "Do not use for casual conversation, reactions, or unsolicited decoration."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to generate — be descriptive. Include style, lighting, mood."
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What to avoid (used for ComfyUI fallback only)",
                    "default": "blurry, low quality, watermark, text, ugly, deformed"
                },
                "width": {"type": "integer", "default": 1024},
                "height": {"type": "integer", "default": 1024},
                "steps": {"type": "integer", "default": 30}
            },
            "required": ["prompt"]
        }

    async def execute(self, prompt: str, negative_prompt: str = "blurry, low quality, watermark, text, ugly, deformed",
                      width: int = 1024, height: int = 1024, steps: int = 30, **kw) -> str:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, prompt, negative_prompt, width, height, steps)

    def _run(self, prompt: str, negative_prompt: str, width: int, height: int, steps: int) -> str:
        print(f"[ImageGen] Trying Imagen 3 for: {prompt[:60]}...")
        url = _imagen3(prompt)
        if url:
            print(f"[ImageGen] Imagen 3 success: {url}")
            return url
        print("[ImageGen] Imagen 3 unavailable, falling back to ComfyUI")
        return _comfyui(prompt, negative_prompt, width, height, steps)
