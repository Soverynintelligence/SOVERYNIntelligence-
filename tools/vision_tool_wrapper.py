"""
Vision Tool - Wraps your existing image analysis
"""
from core.tool_base import Tool
from vision_tool import analyze_image
from typing import Any, Dict

class VisionTool(Tool):
    """Analyze images from camera or uploaded files"""
    
    @property
    def name(self) -> str:
        return "analyze_image"
    
    @property
    def description(self) -> str:
        return "Analyze an image and describe what you see. Use when user mentions an image or asks about visual content."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Path to the image file"
                }
            },
            "required": ["image_path"]
        }
    
    async def execute(self, image_path: str, **kwargs) -> str:
        """Analyze image using your existing vision tool"""
        try:
            # Use your existing analyze_image function
            result = analyze_image(image_path)
            return f"Image analysis: {result}"
        except Exception as e:
            return f"Vision error: {e}"