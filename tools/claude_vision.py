"""
Claude Vision — sends images to Claude API for analysis.
Replaces the local Qwen2-VL-7B vision agent.
"""
import base64
import os
from pathlib import Path
import anthropic

_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def analyze_image_claude(image_path: str, prompt: str = "Describe this image in detail.") -> str:
    """Send an image to Claude API and return a description."""
    try:
        path = Path(image_path)
        if not path.exists():
            return f"Image not found: {image_path}"

        suffix = path.suffix.lower()
        media_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.gif': 'image/gif',
        }
        media_type = media_type_map.get(suffix, 'image/jpeg')

        with open(image_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')

        client = _get_client()
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }]
        )
        return message.content[0].text

    except Exception as e:
        return f"Claude vision error: {e}"
