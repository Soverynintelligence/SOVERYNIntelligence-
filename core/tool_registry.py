"""
Tool Registry for SOVERYN 2.0
Manages all available tools for agents
"""
from typing import Dict, List, Any
from core.tool_base import Tool

class ToolRegistry:
    """Registry of available tools for agents"""
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """Register a tool"""
        self._tools[tool.name] = tool
        print(f"✓ Registered tool: {tool.name}")
    
    def unregister(self, name: str) -> None:
        """Remove a tool"""
        if name in self._tools:
            del self._tools[name]
            print(f"✓ Unregistered tool: {name}")
    
    def get(self, name: str) -> Tool:
        """Get a tool by name"""
        return self._tools.get(name)
    
    def has(self, name: str) -> bool:
        """Check if tool exists"""
        return name in self._tools
    
    def get_definitions(self) -> List[Dict[str, Any]]:
        """Get all tool definitions for LLM function calling"""
        return [tool.to_schema() for tool in self._tools.values()]
    
    async def execute(self, name: str, params: Dict[str, Any]) -> str:
        """
        Execute a tool by name with parameters.
        Returns string result or error message.
        """
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"
        
        try:
            result = await tool.execute(**params)
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}"
    
    @property
    def tool_names(self) -> List[str]:
        """List of registered tool names"""
        return list(self._tools.keys())
    
    def __len__(self) -> int:
        return len(self._tools)