"""
Claude Bridge Tool - Invite Claude for consultation
"""
from core.tool_base import Tool
from typing import Any, Dict
import anthropic
import os

class ClaudeBridgeTool(Tool):
    """Consult with Claude (external AI) for specialized insights"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            self.client = None
    
    @property
    def name(self) -> str:
        return "invite_claude_perspective"
    
    @property
    def description(self) -> str:
        return """Use this tool to actually send a message to Claude and receive a real response. 
        This is a live connection — you must call this tool to communicate with Claude. 
        Describing or imagining the conversation is not the same as calling this tool."""
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or question to consult Claude about"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context about the discussion"
                }
            },
            "required": []
        }
    async def execute(self, topic: str = "general introduction", context: str = "", **kwargs) -> str:
        try:
            if not self.client:
                return "Claude bridge not configured (missing API key)"
        
            # Use default topic if none provided
            if not topic:
                topic = "general introduction"
            
            # Build consultation prompt
            prompt = f"Topic: {topic}\n\n"
            if context:
                prompt += f"Context: {context}\n\n"
            prompt += "Please provide your perspective and any relevant frameworks or strategies."
            
            # Call Claude API
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            response = message.content[0].text
            return f"Claude's perspective:\n{response}"
            
        except Exception as e:
            return f"Error consulting Claude: {e}"