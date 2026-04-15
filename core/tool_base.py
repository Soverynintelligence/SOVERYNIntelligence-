"""
Base Tool class for SOVERYN 2.0
All tools inherit from this
"""
from abc import ABC, abstractmethod
from typing import Any, Dict

class Tool(ABC):
    """Base class for all SOVERYN tools"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """What the tool does"""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema for tool parameters"""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """
        Execute the tool with given parameters.
        Returns string result (for consistency with LLM expectations)
        """
        pass
    
    def to_schema(self) -> Dict[str, Any]:
        """Convert tool to OpenAI/Gemini function calling format"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }