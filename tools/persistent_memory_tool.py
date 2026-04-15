"""
Persistent Memory Tool - Wraps SOVERYN Persistent Memory for agent use
"""
from core.tool_base import Tool
from soveryn_memory.persistent_memory import SoverynPersistentMemory
from typing import Any, Dict

class PersistentMemoryTool(Tool):
    """Search and retrieve from persistent memory system"""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.memory = SoverynPersistentMemory()
    
    @property
    def name(self) -> str:
        return "search_memory"
    
    @property
    def description(self) -> str:
        return """Search through conversation history and memories. Use this when the user references past conversations or when you need context from previous discussions."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memory (e.g., 'SOVERYN architecture', 'conversation about Corvettes')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of results to return (default 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, query: str = "", limit: int = 10, **kwargs) -> str:
        """Search persistent memory"""
        try:
            if not query or not query.strip():
                return "Memory search requires a query. Please specify what you're looking for."
            
            # Search conversations
            conversations = await self.memory.search_conversations(
                agent=self.agent_name,
                query=query,
                limit=limit
            )
            
            if not conversations:
                return f"No memories found for: {query}"
            
            # Format results
            result = f"Found {len(conversations)} relevant memories:\n\n"
            
            for i, conv in enumerate(conversations[:limit], 1):
                role = conv['role'].upper()
                content = conv['content'][:200]  # Truncate long messages
                timestamp = conv['timestamp'][:10]  # Just the date
                
                result += f"{i}. [{timestamp}] {role}: {content}...\n"
            
            return result
            
        except Exception as e:
            return f"Memory error: {e}"


class SelfReflectionTool(Tool):
    """Allow agents to reflect on their own tool usage"""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.memory = SoverynPersistentMemory()
    
    @property
    def name(self) -> str:
        return "self_reflect"
    
    @property
    def description(self) -> str:
        return """Analyze your own tool usage patterns and performance. Use this to understand how you've been working and identify areas for improvement."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 7)",
                    "default": 7
                }
            }
        }
    
    async def execute(self, days: int = 7, **kwargs) -> str:
        """Generate self-reflection insights"""
        try:
            insights = await self.memory.reflect_on_tool_usage(
                agent=self.agent_name,
                days=days
            )
        
            # Check if insights is None or empty
            if not insights:
                return f"No tool usage data available for the past {days} days."
        
            # Format insights safely with .get()
            result = f"Self-Reflection Analysis (past {days} days):\n\n"
            result += f"Total tool calls: {insights.get('total_tool_calls', 0)}\n"
            result += f"Most used tool: {insights.get('most_used_tool', 'None')}\n\n"
        
            tool_usage = insights.get('tool_usage', {})
            if tool_usage:
                result += "Tool Usage Breakdown:\n"
                for tool_name, stats in tool_usage.items():
                    result += f"  - {tool_name}: {stats.get('count', 0)} calls "
                    result += f"(success rate: {stats.get('success_rate', 0):.1%}, "
                    result += f"avg {stats.get('avg_duration_ms', 0):.0f}ms)\n"
        
            recent_errors = insights.get('recent_errors', [])
            if recent_errors:
                result += f"\nRecent errors: {len(recent_errors)}\n"
                for err in recent_errors[:3]:
                    result += f"  - {err.get('tool', 'unknown')}: {err.get('error', '')[:100]}\n"
        
            return result
        
        except Exception as e:
            return f"Self-reflection error: {e}"